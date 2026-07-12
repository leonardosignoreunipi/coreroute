from JanusKB import JanusKB
import logging

logger = logging.getLogger(__name__)

class PathRegistry:
    """
    PathRegistry hold a dictionary Nodes -> pathId to avoid path duplicates in kb
    """ 
    def __init__(self, kb: JanusKB):
        """
        Bind the KB and init an empty nodes->pathId cache and the id counter.
        """
        self.kb = kb
        self._id_by_nodes = {}
        self._next_id = 0
    
    def load_paths(self) -> dict[tuple, str]:
        """
        Loads all paths not empty from the kb into a dictionary.
        returns a dict: tuple(nodes) -> pathId
        the nodes are ordered, (a, b, c) is different from (c, b, a)
        """
        self._id_by_nodes = {}
        for p in self.kb.get_all_paths():
            if p["Nodes"]:
                self._id_by_nodes[tuple(p["Nodes"])] = p["PathId"]
                logger.debug(f"Loaded path: {p['Nodes']} with PathId: {p['PathId']}") 
        logger.debug(f"Total paths not empty loaded: {len(self._id_by_nodes)} in PathRegistry {self._id_by_nodes}")  
        return self._id_by_nodes        
    
    def intern_path(self, nodes: list[str]) -> str:
        """
        Given a path (list of nodes)
        if path already exists in kb return that id 
        else return a new fresh id and insert the new path in kb
        """
        nodes_tuple = tuple(nodes)
        if nodes_tuple in self._id_by_nodes: return self._id_by_nodes[nodes_tuple]
        else:
            self._next_id += 1
            pathId = f"p_{self._next_id}"
            self._id_by_nodes[nodes_tuple] = pathId
            self.kb.put_path(pathId, nodes[0], nodes[-1], nodes)
            return pathId