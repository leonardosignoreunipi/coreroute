import PhysicalNetwork
import JanusKB
import ConfigLoader
import rustworkx as rx

class RoutingEngine:
    def __init__(self, network: PhysicalNetwork, kb: JanusKB, config: ConfigLoader):
        self.network = network
        self.kb = kb
        self.config = config
    
    def diff_score(self, path1, path2): 
        set_path1 = set((u, v) for u, v in zip(path1[:-1], path1[1:]))
        set_path2 = set((u, v) for u, v in zip(path2[:-1], path2[1:]))
        return len(set_path1.symmetric_difference(set_path2))

    def get_partition(self):
        """ottiene la partizione dei routing"""
        return self.kb.query_partition()

    def cr_routing(self, ok_flows, ko_flows):
        if len(ko_flows) == 0:
            print("Nessun KoFlow trovato!")
            return ok_flows

        ko_flows.sort(key=lambda routing: self.config.flows[routing.flow_id].required_bw(self.config.pckt_size), reverse=True)

        flowsNodes = {r.flow_id: self.config.paths[r.path_id].nodes for r in ko_flows}

        temp_koflows = list(ko_flows)
        
        while len(temp_koflows) > 0:
            routing = temp_koflows.pop() #take the flow with the lowest packet rate among the KoFlows
            flowId = routing.flow_id
            
            old_path = flowsNodes[flowId]
            if (old_path == None):
                print("Non esiste alcun path per il flow: " + flowId)
                continue

            requiredBandwidth = self.config.flows[flowId].required_bw(self.config.pckt_size)
        
            Gpruned = self.network.pruning_per_bandwith(requiredBandwidth)

            src = self.network.node_map[old_path[0]] #map nodes stringId to int
            dst = self.network.node_map[old_path[-1]] #map nodes stringId to int

            candidates = self.search_candidates(Gpruned, src, dst, flowId)
            if len(candidates) == 0:
                print(f"Not valid paths for flow: {flowId}")
            pathsIds = []
            index = 0

            while len(candidates) > 0:
                
                nodes = candidates.pop(0)

                pathId = f"{flowId}_{index + 1}"
                pathsIds.append(pathId)
                self.kb.put_path(pathId, nodes[0], nodes[-1], nodes)    
                index += 1
            
            self.kb.put_candidates_paths(flowId, pathsIds)
            
        return self.kb.query_cr_routings(ko_flows, ok_flows)


    def search_candidates(self, graph_pruned, src, dst, flow_id): 
        """trova tutti i path tra src e dst con al massimo 6 hop di distanza restituisce una lista di path come ["id1", "id2", "id3"]
        """
        candidates = []

        print(f"candidates for flow: {flow_id}")

        for path_idx in rx.all_simple_paths(graph_pruned, src, dst, cutoff=10):
            path = [self.network.inv_node_map[node_idx] for node_idx in path_idx]
            print(f"\t{path}")
            candidates.append(path)
        
        return candidates