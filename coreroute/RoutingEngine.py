import PhysicalNetwork
import JanusKB
import ConfigLoader
import random
import logging
import networkx as nx
from Models import Routing
from PathRegistry import PathRegistry as pr
import time


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
        self._pr = pr()
        self.STRATEGY = self.biased_k_shortest_path_latency
        self.prolog_strategy = self.resolve_repair
        self.last_time_strategy = 0.0
        self.last_time_prolog_strategy = 0.0
        
    def path_latency(self, nodes: list[str]) -> float:
        """
        Total latency of a path. For each hop (u, v):
        serialisation (pckt_size / bw) + propagation (length / c)
        + qtime of the sending node. Mirrors hopLatency in routing_core.pl.

        Returns 0.0 for empty or single-node paths.
        """
        if not nodes or len(nodes) < 2:
            return 0.0
        pckt_size = self.config.pckt_size 
        c = self.config.speed_of_light
        total = 0.0
        for u, v in zip(nodes[:-1], nodes[1:]):
            edge = self.network.graph[u][v]
            d_trasm = pckt_size / edge["bw"]
            d_prop = edge["length"] / c
            qtime = self.network.graph.nodes[u].get("qtime", 0.0)
            total += d_trasm + d_prop + qtime
        return total

    def diff_score(self, old_path: list[str], new_path: list[str]):
        """
        Reconfiguration-cost heuristic between the old and the new path.

        Counts the directed edges (u, v) that differ between the two paths
        (symmetric difference). Direction is significant on purpose: each
        differing directed edge approximates one forwarding update the SDN
        controller must push to the routers to switch traffic direction.
        """
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

    def _generate_candidates(self, ko_flows: list[Routing]) -> int:
        """
        Stage 1 (candidate generation + KB write), shared by re_routing.
        Processes ko_flows smallest-bandwidth-first. Returns no_path_count
        (ko-flows with zero candidates).
        """
        flowsNodes = {r.flow_id: self.kb.get_path_by_id(r.path_id) for r in ko_flows}
        ko_flows.sort(key=lambda routing: self.config.flows[routing.flow_id].required_bw(self.config.pckt_size), reverse=True)
        temp_koflows = list(ko_flows)

        paths = self.kb.get_all_paths()
        self._pr.load_paths(paths) #load all current paths in a dictonary

        no_path_count = 0

        while len(temp_koflows) > 0:
            routing = temp_koflows.pop()
            flowId = routing.flow_id

            old_path = flowsNodes[flowId]

            if old_path == []:
                src, dst = self.get_valid_src_dst(flowId)
            else:
                src = old_path[0]
                dst = old_path[-1]

            required_bw = self.config.flows[flowId].required_bw(self.config.pckt_size)
            graph_pruned = self.network.pruning_per_bandwidth(required_bw)

            candidates = self.STRATEGY(graph_pruned, src, dst, flowId, old_path)

            if len(candidates) == 0:
                logger.warning(f"Not valid paths for flow: {flowId}")
                no_path_count += 1
            pathsIds = []

            for (_, nodes) in candidates:
                path_id, is_new = self._pr.intern_path(nodes) # returns the existing id or if not exists returns a fresh id
                if is_new: self.kb.put_path(path_id, nodes[0], nodes[-1], nodes)
                pathsIds.append(path_id)

            self.kb.put_candidates_paths(flowId, pathsIds)

        return no_path_count

    def re_routing(self, ok_flows: list[Routing], ko_flows: list[Routing]):
        """
        Continuous-reasoning routing: reallocate the ko-flows.

        Runs Stage 1, then resolves Stage 2 via self.prolog_strategy
        (default: resolve_repair; swappable to resolve_exhaustive_routing,
        same return shape either way -- no branching, like self.STRATEGY).

        Args:
            ok_flows: routings that already hold a valid path.
            ko_flows: routings to (re)allocate.

        Returns:
            (new_valid_routings, failed_routings, no_path_count). If
            ko_flows is empty, returns (ok_flows, [], 0).
        """

        if len(ko_flows) == 0:
            logger.info("No koFlows")
            self.last_time_strategy = 0.0
            self.last_time_prolog_strategy = 0.0
            return ok_flows, [], 0
        t0 = time.perf_counter()
        no_path_count = self._generate_candidates(ko_flows)
        self.last_time_strategy = time.perf_counter() - t0 #save time execution of the generation candidates strategy

        t0 = time.perf_counter()
        new_valid, failed = self.prolog_strategy(ko_flows, ok_flows)
        self.last_time_prolog_strategy = time.perf_counter() - t0 #save time execution of the rerouting strategy (repair or exhaustiveRouting)
        
        return new_valid, failed, no_path_count

    def resolve_repair(self, ko_flows: list[Routing], ok_flows: list[Routing]):
        """Default prolog_strategy: resolve via repair/4."""
        return self.kb.query_repair(ko_flows, ok_flows)

    def resolve_exhaustive_routing(self, ko_flows: list[Routing], ok_flows: list[Routing]):
        """Alternate prolog_strategy: exhaustiveRouting/3, then pick the best solution."""
        solutions = self.kb.query_exhaustive_routings(ko_flows, ok_flows)
        return self.select_best_exhaustive_solution(solutions, ko_flows, ok_flows)

    def select_best_exhaustive_solution(self, solutions: list[list[Routing]], ko_flows: list[Routing], ok_flows: list[Routing]):
        """
        Pick the best of exhaustiveRouting/3's per-permutation solutions.
        Priority: 1. fewest failed flows; 2. lowest total symmetric diff
        (failed flows score as full removal cost, diff_score(old, []));
        3. lowest average latency among routed flows.
        Returns (new_valid_routings, failed_routings), same shape as
        resolve_repair.
        """
        if not solutions:
            raise RoutingEngineError("select_best_exhaustive_solution: no solutions to choose from")

        ko_flow_ids = {r.flow_id for r in ko_flows}
        old_path_by_flow = {r.flow_id: self.kb.get_path_by_id(r.path_id) for r in ko_flows}
        path_nodes_cache: dict[str, list[str]] = {}

        def nodes_of(path_id):
            if path_id not in path_nodes_cache:
                path_nodes_cache[path_id] = self.kb.get_path_by_id(path_id)
            return path_nodes_cache[path_id]

        scored = []
        for solution in solutions:
            routed_by_flow = {r.flow_id: r for r in solution if r.flow_id in ko_flow_ids}
            failed_flow_ids = ko_flow_ids - routed_by_flow.keys()

            total_diff = 0
            latencies = []
            for flow_id in ko_flow_ids:
                old_path = old_path_by_flow[flow_id]
                if flow_id in routed_by_flow:
                    new_path = nodes_of(routed_by_flow[flow_id].path_id)
                    total_diff += self.diff_score(old_path, new_path)
                    latencies.append(self.path_latency(new_path))
                else:
                    total_diff += self.diff_score(old_path, [])

            avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
            scored.append((len(failed_flow_ids), total_diff, avg_latency, solution, failed_flow_ids))

        scored.sort(key=lambda s: (s[0], s[1], s[2]))
        _, _, _, best_solution, best_failed_ids = scored[0]

        new_valid = best_solution
        failed = [r for r in ko_flows if r.flow_id in best_failed_ids]
        return new_valid, failed

    def biased_k_shortest_path(self, graph_pruned : nx.Graph, src: str, dst: str, flow_id: str, old_path : list[str] = None):
        """
        Enumerate up to K simple paths from src to dst on the
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
        K = 10
        
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
                if len(candidates) >= K:
                    break
        except nx.NetworkXNoPath:
            logger.warning(f"No path found for flow {flow_id} from {src} to {dst}")
            
        candidates.sort(key=lambda x: x[0])
        
        logger.info(f"biased_k_shortest_path: flow={flow_id} candidates_length={len(candidates)} paths")
        
        return candidates
    
    
    def biased_k_shortest_path_latency(self, graph_pruned : nx.Graph, src: str, dst: str, flow_id: str, old_path : list[str] = None):
        """
        Same candidate generation as biased_k_shortest_path (K=10, W(0/2)
        biased toward the old path), but ordered by (diff_score, path_latency)
        instead of diff_score alone.

        Isolates the effect of the latency tie-break against
        biased_k_shortest_path: same candidate set, different ordering.

        Returns a list of (score, path_nodes) tuples, sorted by
        (score, latency). Empty if no path exists between src and dst.
        """
        K = 10
        
        old_path_edges = set(zip(old_path[:-1], old_path[1:])) if old_path else set()
        
        def weight_fn (u, v, d): 
            if (u,v) in old_path_edges :
                return 0
            else: return 2
            
        tmp_candidates = []
        try:
            for c in nx.shortest_simple_paths(graph_pruned, source=src, target=dst, weight=weight_fn):
                score = self.diff_score(old_path, c)
                latency = self.path_latency(c)
                tmp_candidates.append((score, latency, c))
                if len(tmp_candidates) >= K:
                    break
        except nx.NetworkXNoPath:
            logger.warning(f"No path found for flow {flow_id} from {src} to {dst}")
            return []
            
        tmp_candidates.sort(key=lambda x: (x[0], x[1]))
        
        logger.info(f"biased_k_shortest_path_latency: flow={flow_id} candidates_length={len(tmp_candidates)} paths")
        
        candidates = [(p[0], p[2]) for p in tmp_candidates]
        
        return candidates
    
    def latency_biased_paths(self, graph_pruned : nx.Graph, src: str, dst: str, flow_id: str, old_path : list[str] = None):
        """
        Enumerate the TOP_N lowest-latency simple paths from src to dst, then
        keep the K with the smallest diff_score among them.

        The search weight is the per-edge latency (transmission + propagation +
        qtime), so shortest_simple_paths yields paths in true ascending path
        latency, not hop count — this duplicates the formula in path_latency /
        hopLatency (routing_core.pl); keep the three in sync. The first TOP_N
        are taken, then re-sorted by diff_score: since Python's sort is stable,
        ties on diff_score preserve the ascending-latency order.

        Unlike biased_k_shortest_path, candidate order is driven by latency, not
        old-path reuse, so it trades reconfiguration cost for route quality.

        Args:
            graph_pruned: read-only bandwidth-filtered view of the network.
            src, dst: endpoint node ids.
            flow_id: flow being routed (drives the per-edge weight and logging).
            old_path: node list of the flow's previous path (None/empty if new).

        Returns:
            List of (score, path_nodes) tuples, sorted by score (≤ K entries).
            Empty if no path exists between src and dst.
        """
        TOP_N = 100
        K = 10

        pckt_size = self.config.pckt_size
        speed_of_light = self.config.speed_of_light

        def weight_fn(u, v, edge_data):
            d_trasm = pckt_size / edge_data["bw"]
            d_prop = edge_data["length"] / speed_of_light
            qtime = self.network.graph.nodes[u].get("qtime", 0.0)
            return d_trasm + d_prop + qtime
        
        candidates = []
        try: 
            for c in nx.shortest_simple_paths(graph_pruned, source=src, target=dst, weight=weight_fn):
                score = self.diff_score(old_path, c)
                candidates.append((score, c))
                if len(candidates) >= TOP_N:
                    break
        except nx.NetworkXNoPath: 
            logger.warning(f"No path found for flow {flow_id} from {src} to {dst}")
            return []
        
        logger.info(f"latency_biased_paths: flow={flow_id} candidates_length={len(candidates)} paths")
        
        candidates.sort(key=lambda x: x[0])
        return candidates[:K]            
    
    def all_simple_candidates(self, graph_pruned : nx.Graph, src: str, dst: str, flow_id: str, old_path : list[str] = None):
        """
        Baseline the heuristics are measured against: enumerates ALL simple paths
        src->dst within cutoff = diameter*2 hops (main component if disconnected),
        sorted by (diff_score, path_latency) so repair commits the best one.
        The optimum is therefore exact but only WITHIN that hop budget and per
        flow, never global.
        """
        
        if nx.is_connected(graph_pruned):
            cutoff = nx.diameter(graph_pruned)*2
        else: 
            components = nx.connected_components(graph_pruned)
            main_component = max(components, key=len)
            gcomponent = graph_pruned.subgraph(main_component)
            cutoff = nx.diameter(gcomponent)*2
        
        tmp_candidates = []
        try:
            for c in nx.all_simple_paths(graph_pruned, src, dst, cutoff=cutoff):
                score = self.diff_score(old_path, c)
                latency = self.path_latency(c)
                tmp_candidates.append((score, latency, c))
            logger.info(f"exhaustive_paths: flow={flow_id} candidates_length={len(tmp_candidates)} paths")    
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            logger.warning(f"No path found for flow {flow_id} from {src} to {dst}")
            return []
        
        tmp_candidates.sort(key=lambda x: (x[0], x[1]))
        
        candidates = [(p[0], p[2]) for p in tmp_candidates] #uniform in couples for re_rorouting 
                
        return candidates