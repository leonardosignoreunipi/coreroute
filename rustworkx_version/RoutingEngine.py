import PhysicalNetwork
import JanusKB
import ConfigLoader
import random
import logging
import rustworkx as rx
import networkx as nx

logger = logging.getLogger(__name__)

class RoutingEngineError(Exception):
    """Custom exception for RoutingEngine-related errors."""
    pass

class RoutingEngine:
    def __init__(self, network: PhysicalNetwork, kb: JanusKB, config: ConfigLoader):
        if network is None:
            raise RoutingEngineError("Network cannot be None.")
        if kb is None:
            raise RoutingEngineError("Knowledge Base cannot be None.")
        if config is None:
            raise RoutingEngineError("Config cannot be None.")
        self.network = network
        self.kb = kb
        self.config = config
        self._cr_call_id = 0

    def diff_score(self, old_path: list[str], new_path: list[str]):
        """
        Calcola la differenza simmetrica tra il vecchio e il nuovo path
        Se il vecchio path non esiste, restituisce 0
        """
        if not old_path:
            return 0
        try:
            set_old_path = set((u, v) for u, v in zip(old_path[:-1], old_path[1:]))
            set_new_path = set((u, v) for u, v in zip(new_path[:-1], new_path[1:]))

        except Exception as e:
            logger.error(f"Error calculating diff score for old_path: {old_path}, new_path: {new_path}. Exception: {e}")
            raise RoutingEngineError(f"Error calculating diff score for old_path: {old_path}, new_path: {new_path}. Exception: {e}")

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
            raise RoutingEngineError(f"No src or dst service found for flow: {flow_id}")
        
        src = random.choice(src_candidate).id

        valid_dst = [h for h in dst_candidate if h.id != src]
        if not valid_dst:
            raise RoutingEngineError(f"No valid distinct dst for flow {flow_id}")
        dst = random.choice(valid_dst).id
        
        return src, dst

    def get_partition(self):
        """ottiene la partizione dei flussi che hanno già un path assegnato"""
        try:
            return self.kb.query_partition()
        except Exception as e:
            logger.error(f"Error retrieving partition: {e}")
            raise RoutingEngineError(f"Error retrieving partition: {e}")

    def cr_routing(self, ok_flows, ko_flows):
        """
        Esegue il cr-routing per risolvere i ko-flows
        """
        
        if len(ko_flows) == 0:
            logger.info("Nessun KoFlow trovato!")
            return ok_flows, []

        self._cr_call_id += 1
        call_id = self._cr_call_id

        flowsNodes = {r.flow_id: self.kb.get_path(r.path_id) for r in ko_flows}
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

            required_bw = self.config.flows[flowId].required_bw(self.config.pckt_size)
            graph_pruned = self.network.pruning_per_bandwidth(required_bw)
            candidates = self.search_candidates2(graph_pruned, src, dst, flowId, old_path, required_bw)

            if len(candidates) == 0:
                logger.warning(f"Not valid paths for flow: {flowId}")
            pathsIds = []

            for index, (_, nodes) in enumerate(candidates):
                pathId = f"{flowId}_c{call_id}_{index + 1}"
                pathsIds.append(pathId)
                self.kb.put_path(pathId, nodes[0], nodes[-1], nodes)
            
            self.kb.put_candidates_paths(flowId, pathsIds)
            
        return self.kb.query_cr_routings(ko_flows, ok_flows)

    
    def search_candidates(self, graph_pruned, src, dst, flow_id, old_path_str=None, required_bw=None):
        """
        This function finds candidates paths using Dijkstra's algorithm with a custom weight function that penalizes edges used in the old path.
        """

        MAX_CANDIDATES = 10

        if graph_pruned is None or src is None or dst is None or flow_id is None or required_bw is None:
            logger.error("Invalid input to search_candidates: graph_pruned, src, dst, flow_id, and required_bw must not be None.")
            raise RoutingEngineError("Invalid input to search_candidates: graph_pruned, src, dst, flow_id, and required_bw must not be None.")

        old_path_edges = set(zip(old_path_str[:-1], old_path_str[1:])) if old_path_str else set()
        edge_penalties = {}

        def weight_fn(edge_data):
            try:
                if edge_data['bw'] < required_bw:
                    return float('inf')
            except KeyError:
                logger.error("Link without bw field")
                raise RoutingEngineError("Link without bw field")

            u_str = edge_data["u"]
            v_str = edge_data["v"]
            u = self.network.node_map[u_str]
            v = self.network.node_map[v_str]

            if (u_str, v_str) in old_path_edges or (v_str, u_str) in old_path_edges:
                base_cost = 0.1
            else:
                base_cost = 1.0
            
            penalty = edge_penalties.get((u, v), 0.0) + edge_penalties.get((v, u), 0.0)

            return base_cost + penalty

        visited_paths = set()
        candidates = []
        index = 0
        stall_count = 0
        MAX_STALLS = MAX_CANDIDATES * 2

        while index < MAX_CANDIDATES and stall_count < MAX_STALLS:
            try:
                res = rx.dijkstra_shortest_paths(graph_pruned, src, dst, weight_fn=weight_fn)
                if dst not in res:
                    """path not found"""
                    break

                path_idx = res[dst]
                path_str = [self.network.inv_node_map[n] for n in path_idx]

                path_edges_str = tuple(zip(path_str[:-1], path_str[1:])) #uso tuple per rendere il path immutabile così può essere aggiunto al set
                path_edges_int = list(zip(path_idx[:-1], path_idx[1:]))

                if path_edges_str in visited_paths:
                    stall_count += 1
                    for (u, v) in path_edges_int:
                        edge_penalties[(u, v)] = edge_penalties.get((u, v), 0.0) + 10.0
                    continue

                visited_paths.add(path_edges_str)
                for (u, v) in path_edges_int:
                    edge_penalties[(u, v)] = edge_penalties.get((u, v), 0.0) + 2.0

                score = self.diff_score(old_path_str, path_str) if old_path_str else 0
                candidates.append((score, path_str))
                index += 1

            except Exception as e:
                logger.error(f"Dijkstra error {e}")
                raise RoutingEngineError(f"Dijkstra error {e}")

        candidates.sort(key=lambda x: x[0])
        logger.info(f"search_candidates: flow={flow_id} candidates_length={len(candidates)} paths")
        return candidates
    
    def search_candidates2(self, graph_pruned, src: int, dst: int, flow_id, old_path_str=None, required_bw=None):
        """
        This function finds candidate paths with nx.shortest_simple_paths (k-shortest-paths),
        favoring edges used in the old path (weight 0.1 vs 1.0) to minimize disruption.
        """
        MAX_CANDIDATES = 10

        old_path_edges = set()
        if old_path_str:
            old_path_idx = [self.network.node_map[n] for n in old_path_str]
            old_path_edges = set(zip(old_path_idx[:-1], old_path_idx[1:]))

        nxgraph = nx.Graph()
        nxgraph.add_nodes_from(graph_pruned.node_indices())
        for u, v in graph_pruned.edge_list():
            in_old = (u, v) in old_path_edges or (v, u) in old_path_edges
            nxgraph.add_edge(u, v, weight=0.1 if in_old else 1.0)

        candidates = []
        try:
            for c in nx.shortest_simple_paths(nxgraph, source=src, target=dst, weight='weight'):
                path_str = [self.network.inv_node_map[n] for n in c]
                score = self.diff_score(old_path_str, path_str)
                candidates.append((score, path_str))
                if len(candidates) >= MAX_CANDIDATES:
                    break
        except nx.NetworkXNoPath:
            logger.warning(f"No path found for flow {flow_id} from {src} to {dst}")
        candidates.sort(key=lambda x: x[0])
        logger.info(f"search_candidates2: flow={flow_id} candidates_length={len(candidates)} paths")
        return candidates