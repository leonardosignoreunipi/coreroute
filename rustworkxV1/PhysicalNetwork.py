import rustworkx as rx 

class PhysicalNetwork:
    def __init__(self, config):
        self.graph = rx.PyGraph()
        self.node_map = {}      # mapping: string ID -> int index
        self.inv_node_map = {}  # mapping: int index -> string ID
        self.build_graph(config)

    def build_graph(self, config):
        for h in config.hosts:
            idx = self.graph.add_node({"id": h.id, "type": "Host", "services": h.services})
            self.node_map[h.id] = idx
            self.inv_node_map[idx] = h.id
        for r in config.routers:
            idx = self.graph.add_node({"id": r.id, "type": "Router", "qtime": r.qtime})
            self.node_map[r.id] = idx
            self.inv_node_map[idx] = r.id
        for l in config.links:
            idx1 = self.node_map[l.src]
            idx2 = self.node_map[l.dst]
            self.graph.add_edge(idx1, idx2, {"bw": l.bw, "length": l.length})

    def pruning_per_bandwith(self, requireBandwidth: float) -> rx.PyGraph:
        """Restituisce un nuovo grafo eliminando i link con banda insufficiente."""
        pruned = rx.PyGraph()

        for node_idx in self.graph.node_indices():
            pruned.add_node(self.graph.get_node_data(node_idx))
        edges_to_add = []
        
        for u, v in self.graph.edge_list():
            payload = self.graph.get_edge_data(u, v)
            bw = float(payload["bw"])
            if bw >= requireBandwidth:
                edges_to_add.append((u, v, payload))
                
        pruned.add_edges_from(edges_to_add)
        return pruned