import json
import logging
from typing import Dict, Any
from Models import Flow, Router, Host, Link, Path, Routing

logger = logging.getLogger(__name__)

class TopologyConfigError(Exception):
    """Custom exception for topology configuration errors"""
    pass
class TopologyConfig:
    """
    Parsed and validated topology: constants, hosts, routers, links, flows,
    paths and routings, built from the raw JSON dict. Flows and paths are
    indexed by id; the rest are lists.
    """
    
    def __init__(self, raw: Dict[str, Any]):
        """
        Parse the raw config dict into typed model objects and validate the
        minimum cardinalities. Raises TopologyConfigError on missing keys,
        malformed values or unmet minimums.
        """
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
            self.links    = [Link(bw_nominal=l.get("bw_nominal", l["bw"]), **{k: v for k, v in l.items() if k != "bw_nominal"}) for l in raw["links"]]
            self.routings = [Routing(**r)       for r in raw["routings"]]
            self.flows    = {f["id"]: Flow(**f) for f in raw["flows"]}
            self.paths    = {p["id"]: Path(**p) for p in raw["paths"]}         
        except KeyError as e:
            raise TopologyConfigError(f"Missing key in topology configuration: {e}")
        except TypeError as e:
            raise TopologyConfigError(f"Invalid format in topology configuration: {e}")

class ConfigLoader:
    """
    Loads a topology JSON file from disk into a validated TopologyConfig.
    """
    def __init__(self, config_path: str):
        """
        Store the path of the JSON topology file to load.
        """
        self.config_path = config_path

    def load(self) -> TopologyConfig:
        """
        Read and parse the JSON file into a TopologyConfig.

        Raises TopologyConfigError if the file is missing, is not valid JSON,
        or fails topology validation.
        """
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