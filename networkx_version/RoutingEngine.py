import PhysicalNetwork
import JanusKB
import ConfigLoader
import random
import logging
import networkx as nx
from Models import Routing
from PathRegistry import PathRegistry as pr


logger = logging.getLogger(__name__)

class RoutingEngineError(Exception):
    """Custom exception for RoutingEngine-related errors."""
    pass

class RoutingEngine:
    """
        Continuous-reasoning routing engine.

        Given the physical network, the Prolog KB and the loaded config, it
        reallocates the flows that currently have no valid path (ko-flows) by
        proposing candidate paths that respect bandwidth and minimize the
        reconfiguration cost with respect to the path each flow held before.
    """
    def __init__(self, network: PhysicalNetwork, kb: JanusKB, config: ConfigLoader):
        """
        Store the collaborators and build the PathRegistry deduplicator.
        Raises RoutingEngineError if network, kb or config is None.
        """
        
        if network is None or kb is None or config is None: 
            raise RoutingEngineError("network, kb and config cannot be None")
        self.network = network
        self.kb = kb
        self.config = config
        self._pr = pr(kb)

    def diff_score(self, old_path: list[str], new_path: list[str]):
        """
        Reconfiguration-cost heuristic between the old and the new path.

        Counts the directed edges (u, v) that differ between the two paths
        (symmetric difference). Direction is significant on purpose: each
        differing directed edge approximates one forwarding update the SDN
        controller must push to the routers to switch traffic direction.
            
        Returns 0 when there is no old path (new flow: nothing to reconfigure).
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

    def get_valid_src_dst(self, flow_id: str): 
        """
        Pick a source and a destination host for a flow with no assigned path.

        Scans the hosts, collects those offering the flow's src_service and
        dst_service, and chooses one of each at random, forcing src != dst.

        Returns:
            (src_id, dst_id): the ids of the chosen hosts.

        Raises RoutingEngineError if no host offers one of the services, or if
        the only candidates for src and dst coincide.
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

        valid_dst = [h for h in dst_candidate if h.id != src] #TODO operazione più efficente rispetto che scorrere tutta la lista
        if not valid_dst:
            raise RoutingEngineError(f"No valid distinct dst for flow {flow_id}")
        dst = random.choice(valid_dst).id
        
        return src, dst

    def get_partition(self):
        """
        Return the current flow partition from the Prolog KB as
        (ok_routings, ko_routings): flows that already have a valid path and
        flows that still need one. Wraps KB errors as RoutingEngineError.
        """
        try:
            return self.kb.query_partition()
        except Exception as e:
            logger.error(f"Error retrieving partition: {e}")
            raise RoutingEngineError(f"Error retrieving partition: {e}")

    def re_routing(self, ok_flows: list[Routing], ko_flows: list[Routing]):
        """
        Continuous-reasoning routing: reallocate the ko-flows.

        Ko-flows are processed from the lowest to the highest required
        bandwidth. For each one it prunes the graph to the links that satisfy
        the flow's bandwidth, computes disruption-biased candidate paths,
        deduplicates them through PathRegistry and stores them in the KB as the
        flow's path candidates. Finally it asks the KB to commit a consistent
        assignment.

        Args:
            ok_flows: routings that already hold a valid path.
            ko_flows: routings to (re)allocate.

        Returns:
            (new_valid_routings, failed_routings) from query_cr_routings.
            If ko_flows is empty, returns (ok_flows, []).
        """
        
        if len(ko_flows) == 0:
            logger.info("No koFlows")
            return ok_flows, []

        flowsNodes = {r.flow_id: self.kb.get_path_by_id(r.path_id) for r in ko_flows}
        ko_flows.sort(key=lambda routing: self.config.flows[routing.flow_id].required_bw(self.config.pckt_size), reverse=True)
        temp_koflows = list(ko_flows)

        self._pr.load_paths() #load all current paths from kb
        
        while len(temp_koflows) > 0:
            routing = temp_koflows.pop() #take the flow with the lowest packet rate among the KoFlows
            flowId = routing.flow_id

            old_path = flowsNodes[flowId]

            if old_path == []:
                src, dst = self.get_valid_src_dst(flowId)
            else:
                src = old_path[0]
                dst = old_path[-1]

            required_bw = self.config.flows[flowId].required_bw(self.config.pckt_size)
            graph_pruned = self.network.pruning_per_bandwidth(required_bw)
            
            candidates = self.biased_k_shortest_path(graph_pruned, src, dst, flowId, old_path)

            if len(candidates) == 0:
                logger.warning(f"Not valid paths for flow: {flowId}")
            pathsIds = []

            for (_, nodes) in candidates:
                path_id = self._pr.intern_path(nodes) # returns the existing id, or inserts(assertz) the path and mints a fresh id
                pathsIds.append(path_id)
            
            self.kb.put_candidates_paths(flowId, pathsIds)
            
        return self.kb.query_cr_routings(ko_flows, ok_flows)
    
    def biased_k_shortest_path(self, graph_pruned : nx.Graph, src: str, dst: str, flow_id: str, old_path : list[str] = None):
        """
        Enumerate up to MAX_CANDIDATES simple paths from src to dst on the
        (bandwidth-pruned) graph, biased to reuse the old path.

        Edges belonging to the old path get weight 0, all others weight 2, so
        shortest_simple_paths surfaces paths that reuse the previous route
        first, minimizing disruption. Each candidate is scored with diff_score
        and the list is returned sorted by ascending score (least disruptive
        first).

        Args:
            graph_pruned: read-only bandwidth-filtered view of the network.
            src, dst: endpoint node ids.
            flow_id: flow being routed (logging only).
            old_path: node list of the flow's previous path (None/empty if new).

        Returns:
            List of (score, path_nodes) tuples, sorted by score. Empty if no
            path exists between src and dst.
        """
        MAX_CANDIDATES = 10
        
        old_path_edges = set(zip(old_path[:-1], old_path[1:])) if old_path else set()
        
        def weight_fn (u, v, d): 
            if (u,v) in old_path_edges :
                return 0
            else: return 2
            
        candidates = []
        try:
            for c in nx.shortest_simple_paths(graph_pruned, source=src, target=dst, weight=weight_fn):
                score = self.diff_score(old_path, c)
                candidates.append((score, c))
                if len(candidates) >= MAX_CANDIDATES:
                    break
        except nx.NetworkXNoPath:
            logger.warning(f"No path found for flow {flow_id} from {src} to {dst}")
            
        candidates.sort(key=lambda x: x[0])
        
        logger.info(f"search_candidates2: flow={flow_id} candidates_length={len(candidates)} paths")
        
        return candidates