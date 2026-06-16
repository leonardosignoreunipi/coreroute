import json
import logging
from typing import Dict, Any
from models import Flow, Router, Host, Link, Path, Routing

logger = logging.getLogger(__name__)

class TopologyConfigError(Exception):
    """Custom exception for topology configuration errors"""
    pass
class TopologyConfig:
    
    MIN_ROUTERS = 1
    MIN_HOSTS = 2
    MIN_LINKS = 1
    MIN_FLOWS = 1
    
    def __init__(self, raw: Dict[str, Any]):
        try:
            self.speed_of_light: float = float(raw["constants"]["SPEED_OF_LIGHT"])
            self.pckt_size: float = float(raw["constants"]["PCKT_SIZE"])
        except KeyError as e:
            raise TopologyConfigError(f"Missing constant: {e}")
        except (ValueError, TypeError) as e:
            raise TopologyConfigError(f"Invalid format for constant value: {e}")
        
        try:
            self.hosts    = [Host(**h)          for h in raw["hosts"]]
            self.routers  = [Router(**r)        for r in raw["routers"]]
            self.links    = [Link(**l)          for l in raw["links"]]
            self.routings = [Routing(**r)       for r in raw["routings"]]
            self.flows    = {f["id"]: Flow(**f) for f in raw["flows"]}
            self.paths    = {p["id"]: Path(**p) for p in raw["paths"]}         
        except KeyError as e:
            raise TopologyConfigError(f"Missing key in topology configuration: {e}")
        except TypeError as e:
            raise TopologyConfigError(f"Invalid format in topology configuration: {e}")
        
        self._validate_minimums()
        
    def _validate_minimums(self):
        if len(self.routers) < self.MIN_ROUTERS:
            raise TopologyConfigError(f"At least {self.MIN_ROUTERS} router(s) required.")
        if len(self.hosts) < self.MIN_HOSTS:
            raise TopologyConfigError(f"At least {self.MIN_HOSTS} host(s) required.")
        if len(self.links) < self.MIN_LINKS:
            raise TopologyConfigError(f"At least {self.MIN_LINKS} link(s) required.")
        if len(self.flows) < self.MIN_FLOWS:
            raise TopologyConfigError(f"At least {self.MIN_FLOWS} flow(s) required.")
        if len(self.paths) < 1:
            raise TopologyConfigError(f"At least one path required.")
        if len(self.routings) < len(self.flows):
            raise TopologyConfigError(f"At least one routing required for each flow. If you don't have valid routings, put with an empty path with Nodes = [].")

class ConfigLoader:
    def __init__(self, config_path: str):
        self.config_path = config_path

    def load(self) -> TopologyConfig:
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return TopologyConfig(raw)
        except FileNotFoundError:
            msg = f"Configuration file not found: {self.config_path}"
            logger.error(msg)
            raise TopologyConfigError(msg)
        except json.JSONDecodeError as e:
            msg = f"Error decoding JSON configuration: {e}"
            logger.error(msg)
            raise TopologyConfigError(msg)
        
def __main__():
    logging.basicConfig(
        level=logging.INFO, 
        format='[%(asctime)s] %(levelname)s - %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    try:
        config = ConfigLoader("topologie_test/topo_test.json").load()
        logger.info(
            f"\nTopology:\n"
            f"{len(config.routers)} routers\n"
            f"{len(config.hosts)} hosts\n"
            f"{len(config.links)} links\n"
            f"{len(config.flows)} flows.\n"
            f"{len(config.routings)} routings\n"
            f"{len(config.paths)} paths\n"
            f"SPEED_OF_LIGHT={config.speed_of_light}\n"
            f"PCKT_SIZE={config.pckt_size}\n"
            
        )
    except TopologyConfigError as e:
        logger.critical(f"Test interrupted due to topology error: {e}")

if __name__ == "__main__":
    __main__()