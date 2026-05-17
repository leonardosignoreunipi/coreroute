import json
from models import Flow, Router, Host, Link, Path, Routing


class TopologyConfig:
    def __init__(self, raw: dict):
        self.speed_of_light: float = raw["constants"]["SPEED_OF_LIGHT"]
        self.pckt_size: float = raw["constants"]["PCKT_SIZE"]

        self.hosts    = [Host(**h)          for h in raw["hosts"]]
        self.routers  = [Router(**r)        for r in raw["routers"]]
        self.links    = [Link(**l)          for l in raw["links"]]
        self.flows    = {f["id"]: Flow(**f) for f in raw["flows"]}
        self.paths    = {p["id"]: Path(**p) for p in raw["paths"]}
        self.routings = [Routing(**r)       for r in raw["routings"]]


class ConfigLoader:
    def __init__(self, config_path: str):
        self.config_path = config_path

    def load(self) -> TopologyConfig:
        with open(self.config_path, "r") as f:
            raw = json.load(f)
        return TopologyConfig(raw)