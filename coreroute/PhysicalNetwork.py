import networkx as nx
import logging
from ConfigLoader import TopologyConfig

logger = logging.getLogger(__name__)
class PhysicalNetworkError(Exception):
    """Custom exception for PhysicalNetwork errors."""
    pass

class PhysicalNetwork:
    """
    In-memory physical topology backed by an undirected networkx graph.

    Nodes carry a `type` ("Host"/"Router") plus role attributes (host
    services, router qtime); edges carry `bw`, `bw_nominal` and `length`.
    """
    
    def __init__(self, config: TopologyConfig):
        """
        Build the graph from config. Raises PhysicalNetworkError if config is None.
        """
        if config is None:
            raise PhysicalNetworkError("Configuration cannot be None")
        self.graph = nx.Graph()
        self.build_graph(config)

    def build_graph(self, config: TopologyConfig) -> nx.Graph:
        """
        Populate self.graph from the config: add host and router nodes, then
        the links as edges. Detects duplicate node ids and links referencing
        unknown nodes.

        Returns the built graph. Any failure is wrapped as PhysicalNetworkError.
        """
        try:
            for h in config.hosts:
                
                if h.id in self.graph.nodes:
                    raise PhysicalNetworkError(f"Error host duplicated {h.id}")
                self.graph.add_node(h.id, type="Host", services = h.services)
                
            for r in config.routers: 
                
                if r.id in self.graph.nodes:
                    raise PhysicalNetworkError(f"Error router duplicated {r.id}")
                self.graph.add_node(r.id, type="Router", qtime = r.qtime)
                
            for l in config.links:
                
                if not self.graph.has_node(l.src) or not self.graph.has_node(l.dst):
                    raise PhysicalNetworkError(f"Link {l.src} -> {l.dst} references unknown node(s)")
                self.graph.add_edge(l.src, l.dst, bw=l.bw, length=l.length, bw_nominal = l.bw_nominal)
            
            return self.graph
        
        except PhysicalNetworkError:
            raise
        except Exception as e: 
            raise PhysicalNetworkError(f"Error occured in build_graph: {e}")

    def pruning_per_bandwidth(self, required_bw: float):
        """
        Return a read-only view of the graph keeping only the edges whose
        bandwidth is >= required_bw. The underlying graph is not modified.
        """
        
        def filter_link(u, v): return self.graph[u][v]["bw"] >= required_bw
        
        return nx.subgraph_view(self.graph, filter_edge = filter_link)