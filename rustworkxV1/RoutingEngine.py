import PhysicalNetwork
import JanusKB
import ConfigLoader
import rustworkx as rx
import heapq
import random

class RoutingEngine:
    def __init__(self, network: PhysicalNetwork, kb: JanusKB, config: ConfigLoader):
        self.network = network
        self.kb = kb
        self.config = config
    
    def diff_score(self, old_path, new_path):
        """
        Calcola la differenza simmetrica tra il vecchio e il nuovo path
        Se il vecchio path non esiste, restituisce 0
        """
        if old_path == []: 
            return 0
        set_old_path = set((u, v) for u, v in zip(old_path[:-1], old_path[1:]))
        set_new_path = set((u, v) for u, v in zip(new_path[:-1], new_path[1:]))

        return len(set_old_path.symmetric_difference(set_new_path))

    def get_valid_src_dst(self, flow_id): 
        """
        trova il src e dst del flow a cui non è ancora stato assegnato un path
        sceglie a caso tra i vari host che forniscono il servizio richiesto
        """
        src_candidate = []
        dst_candidate = []

        for host in self.config.hosts:
            if self.config.flows[flow_id].src_service in host.services:
                src_candidate.append(host)
            if self.config.flows[flow_id].dst_service in host.services:
                dst_candidate.append(host)
        
        if len(src_candidate) == 0 or len(dst_candidate) == 0:
            raise Exception(f"No src or dst service found for flow: {flow_id}")
        
        src = random.choice(src_candidate).id
        dst = random.choice(dst_candidate).id

        while src == dst:
            dst = random.choice(dst_candidate).id
        
        return src, dst

    def get_partition(self):
        """ottiene la partizione dei flussi che hanno già un path assegnato"""
        return self.kb.query_partition()

    def cr_routing(self, ok_flows, ko_flows):
        """
        Esegue il cr-routing per risolvere i ko-flows
        """
        
        
        if len(ko_flows) == 0:
            print("Nessun KoFlow trovato!")
            return ok_flows
        
        flowsNodes = {r.flow_id: self.config.paths[r.path_id].nodes for r in ko_flows}
        ko_flows.sort(key=lambda routing: self.config.flows[routing.flow_id].required_bw(self.config.pckt_size), reverse=True)

        temp_koflows = list(ko_flows)
        
        while len(temp_koflows) > 0:
            routing = temp_koflows.pop() #take the flow with the lowest packet rate among the KoFlows
            flowId = routing.flow_id
            
            old_path = flowsNodes[flowId]

            if old_path == []:
                src, dst = self.get_valid_src_dst(flowId)
                src = self.network.node_map[src] #map nodes stringId to int
                dst = self.network.node_map[dst] #map nodes stringId to int 
            else:
                src = self.network.node_map[old_path[0]] #map nodes stringId to int
                dst = self.network.node_map[old_path[-1]] #map nodes stringId to int
            

            Gpruned = self.network.pruning_per_bandwith(self.config.flows[flowId].required_bw(self.config.pckt_size))

            candidates = self.search_candidates(Gpruned, src, dst, flowId, old_path)
            if len(candidates) == 0:
                print(f"Not valid paths for flow: {flowId}")
            pathsIds = []
            index = 0

            while len(candidates) > 0:
                
                score, nodes = heapq.heappop(candidates)

                pathId = f"{flowId}_{index + 1}"
                pathsIds.append(pathId)
                self.kb.put_path(pathId, nodes[0], nodes[-1], nodes)    
                index += 1
            
            self.kb.put_candidates_paths(flowId, pathsIds)
            
        return self.kb.query_cr_routings(ko_flows, ok_flows)


    def search_candidates(self, graph_pruned, src, dst, flow_id, old_path=None): 
        """ 
            Trova tutti i path tra src e dst con al massimo 6 hop di distanza 
            restituisce una lista di path come ["id1", "id2", "id3"]
        """
        candidates = []

        print(f"candidates for flow: {flow_id} from {old_path} src={src} dst={dst} bw={self.config.flows[flow_id].required_bw(self.config.pckt_size)}")

        for path_idx in rx.all_simple_paths(graph_pruned, src, dst, cutoff=6):
            path = [self.network.inv_node_map[node_idx] for node_idx in path_idx]
            print(f"\t{path}")
            heapq.heappush(candidates, (self.diff_score(old_path, path), path))
        
        return candidates