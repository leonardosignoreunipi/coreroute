import PhysicalNetwork
import JanusKB
import ConfigLoader
import heapq
import random
import logging
from collections import deque

logger = logging.getLogger(__name__)

def _bfs_simple_paths(graph, source, target, cutoff):
    """
    Generator that yields simple paths (lists of node indices) from source to target
    in BFS order (shortest paths first). Caller breaks after collecting enough candidates,
    so the full exponential enumeration is never triggered on dense graphs.
    """
    queue = deque([(source, [source], {source})])
    while queue:
        node, path, visited = queue.popleft()
        for neighbor in graph.neighbors(node):
            if neighbor in visited:
                continue
            new_path = path + [neighbor]
            if neighbor == target:
                yield new_path
            elif len(new_path) < cutoff:
                queue.append((neighbor, new_path, visited | {neighbor}))

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
            return ok_flows
        
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
            

            graph_pruned = self.network.pruning_per_bandwith(self.config.flows[flowId].required_bw(self.config.pckt_size))
            candidates = self.search_candidates(graph_pruned, src, dst, flowId, old_path)
            
            if len(candidates) == 0:
                logger.warning(f"Not valid paths for flow: {flowId}")
            pathsIds = []
            index = 0

            MAX_CANDIDATES = 20
            while len(candidates) > 0 and index < MAX_CANDIDATES:
                
                score, nodes = heapq.heappop(candidates)

                pathId = f"{flowId}_{index + 1}"
                pathsIds.append(pathId)
                self.kb.put_path(pathId, nodes[0], nodes[-1], nodes)    
                index += 1
            
            self.kb.put_candidates_paths(flowId, pathsIds)
            
        return self.kb.query_cr_routings(ko_flows, ok_flows)


    def search_candidates(self, graph_pruned, src, dst, flow_id, old_path=None):
        """
        Trova i migliori candidati tra src e dst usando BFS con early stop.
        Raccoglie al massimo MAX_ENUM path (i più corti prima), poi li ordina
        per diff_score rispetto al path precedente e restituisce una heap.
        """
        MAX_CUTOFF = 8 
        MAX_ENUM   = 20 

        candidates = []
        found = 0

        for path_idx in _bfs_simple_paths(graph_pruned, src, dst, MAX_CUTOFF):
            if found >= MAX_ENUM:
                break
            try:
                path = [self.network.inv_node_map[idx] for idx in path_idx]
            except KeyError as e:
                logger.error(f"Error mapping node indices to IDs: {e}")
                continue
            score = self.diff_score(old_path, path) if old_path else 0
            heapq.heappush(candidates, (score, path))
            found += 1

        logger.info(f"search_candidates: flow={flow_id} enumerated={found} paths")
        return candidates