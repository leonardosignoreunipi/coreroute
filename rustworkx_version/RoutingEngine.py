import PhysicalNetwork
import JanusKB
import ConfigLoader
import heapq
import random
import logging

logger = logging.getLogger(__name__)

def _priority_path_search(graph, source, target, old_edges, cutoff):
    """
    Yields (cost, path) for simple paths from source to target in strictly
    non-decreasing cost order.

    Edge costs: -1 if the edge belongs to old_edges (reused), +1 if new.
    Negative weights are safe because visited tracking prevents cycles — a
    simple path never revisits a node, so negative cycles are unreachable.

    Ordering guarantee (same logic as Dijkstra): a complete path is yielded
    only when popped from the heap. At that point every other entry in the
    heap has cost >= the one just popped, so no cheaper complete path can
    still be pending.
    """
    counter = 0
    heap = [(0, counter, (source,), {source})]

    while heap:
        cost, _, path_t, visited = heapq.heappop(heap)
        node = path_t[-1]

        if node == target:
            yield (cost, list(path_t))
            continue

        for neighbor in graph.neighbors(node):
            if neighbor in visited:
                continue
            edge_cost = -1 if (node, neighbor) in old_edges or (neighbor, node) in old_edges else 1
            new_cost = cost + edge_cost
            new_path = path_t + (neighbor,)
            # Push complete paths (target reached) unconditionally;
            # push partial paths only if still within the depth limit.
            if neighbor == target or len(new_path) < cutoff:
                counter += 1
                heapq.heappush(heap, (new_cost, counter, new_path, visited | {neighbor}))

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

            # candidates è già ordinata per diff_score (prodotta da _priority_path_search)
            for index, (_, nodes) in enumerate(candidates):
                pathId = f"{flowId}_{index + 1}"
                pathsIds.append(pathId)
                self.kb.put_path(pathId, nodes[0], nodes[-1], nodes)
            
            self.kb.put_candidates_paths(flowId, pathsIds)
            
        return self.kb.query_cr_routings(ko_flows, ok_flows)


    def search_candidates(self, graph_pruned, src, dst, flow_id, old_path=None):
        """
        Trova i candidati tra src e dst usando una ricerca a coda di priorità
        con costi {-1 riuso vecchio arco, +1 arco nuovo}. I path vengono prodotti
        già in ordine crescente di diff_score — nessun heap di post-ordinamento.
        """
        MAX_CUTOFF = 8
        MAX_ENUM   = 20

        # Converti old_path (string IDs) in un insieme di coppie di indici interi
        old_edges: set[tuple[int, int]] = set()
        if old_path and len(old_path) > 1:
            for u, v in zip(old_path[:-1], old_path[1:]):
                u_idx = self.network.node_map.get(u)
                v_idx = self.network.node_map.get(v)
                if u_idx is not None and v_idx is not None:
                    old_edges.add((u_idx, v_idx))

        candidates = []
        for cost, path_idx in _priority_path_search(graph_pruned, src, dst, old_edges, MAX_CUTOFF):
            if len(candidates) >= MAX_ENUM:
                break
            try:
                path = [self.network.inv_node_map[idx] for idx in path_idx]
            except KeyError as e:
                logger.error(f"Error mapping node indices to IDs: {e}")
                continue
            candidates.append((cost, path))

        logger.info(f"search_candidates: flow={flow_id} enumerated={len(candidates)} paths")
        return candidates