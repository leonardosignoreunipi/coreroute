import rustworkx as rx 
import logging

logger = logging.getLogger(__name__)
class PhysicalNetworkError(Exception):
    """Custom exception for PhysicalNetwork errors."""
    pass
class PhysicalNetwork:
    def __init__(self, config):
        if config is None:
            raise PhysicalNetworkError("Configuration cannot be None")
        self.graph = rx.PyGraph()
        self.node_map = {}      # mapping: string ID -> int index
        self.inv_node_map = {}  # mapping: int index -> string ID
        self.build_graph(config)

    def build_graph(self, config):
        for h in config.hosts:
            if h.id in self.node_map:
                raise PhysicalNetworkError(f"Duplicate node ID: {h.id}")
            idx = self.graph.add_node({"id": h.id, "type": "Host", "services": h.services})
            self.node_map[h.id] = idx
            self.inv_node_map[idx] = h.id
        for r in config.routers:
            if r.id in self.node_map:
                raise PhysicalNetworkError(f"Duplicate node ID: {r.id}")
            idx = self.graph.add_node({"id": r.id, "type": "Router", "qtime": r.qtime})
            self.node_map[r.id] = idx
            self.inv_node_map[idx] = r.id
        for l in config.links:
            try:
                idx1 = self.node_map[l.src]
                idx2 = self.node_map[l.dst]
                bw = float(l.bw)
                length = float(l.length)
            except KeyError:
                raise PhysicalNetworkError(f"Link {l.src} -> {l.dst} references unknown node(s)")
            except (ValueError, TypeError):
                raise PhysicalNetworkError(f"Link {l.src} -> {l.dst} has non-numeric bandwidth or length")
            if idx1 == idx2:
                raise PhysicalNetworkError(f"Link {l.src} -> {l.dst} cannot connect a node to itself")
            if self.graph.has_edge(idx1, idx2):
                raise PhysicalNetworkError(f"Duplicate link between {l.src} and {l.dst}")
            self.graph.add_edge(idx1, idx2, {"bw": l.bw, "bw_nominal": l.bw_nominal, "length": l.length, "u": l.src, "v": l.dst})

    def pruning_per_bandwith(self, requireBandwidth: float) -> rx.PyGraph:
        """Returns a new graph by eliminating links with insufficient bandwidth. Complexity: O(E) where E is the number of edges."""
        pruned = self.graph.copy()
        edges_to_remove = []
        logger.info(f"Starting pruning with required bandwidth: {requireBandwidth}")
        for (u, v) in pruned.edge_list():
            payload = pruned.get_edge_data(u, v)
            bw = payload.get("bw")
            logger.debug(f"Checking edge {self.inv_node_map[u]} -> {self.inv_node_map[v]} with bandwidth {bw}")
            if bw < requireBandwidth:
                edges_to_remove.append((u, v))

        for (u, v) in edges_to_remove:
            pruned.remove_edge(u, v)
            
        return pruned