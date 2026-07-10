from JanusKB import JanusKB
import logging

logger = logging.getLogger(__name__)

class Path_dict:
    """
    Path_dict hold a dictionary Nodes -> pathId to avoid path duplicates in kb
    """ 
    def __init__(self, kb: JanusKB):
        self.kb = kb
        self._H = {}
        self._count_path = 0
    
    def load_paths(self) -> dict[tuple, str]:
        """
        Loads all paths not empty from the kb into a dictionary.
        returns a dict: tuple(nodes) -> pathId
        the nodes are ordered, (a, b, c) is different from (c, b, a)
        """
        self._H = {}
        for p in self.kb.get_all_paths():
            if p["Nodes"]:
                self._H[tuple(p["Nodes"])] = p["PathId"]
                logger.debug(f"Loaded path: {p['Nodes']} with PathId: {p['PathId']}") 
        logger.debug(f"Total paths not empty loaded: {len(self._H)} in Path_dict {self._H}")  
        return self._H        
    
    def add_path(self, nodes: list[str]) -> str:
        """
        Given a path (list of nodes)
        if path already exists in kb return that id 
        else return a new fresh id and insert the new path in kb
        """
        nodes_tuple = tuple(nodes)
        if nodes_tuple in self._H: return self._H[nodes_tuple]
        else:
            self._count_path += 1
            pathId = f"p_{self._count_path}"
            self._H[nodes_tuple] = pathId
            self.kb.put_path(pathId, nodes[0], nodes[-1], nodes)
            return pathId