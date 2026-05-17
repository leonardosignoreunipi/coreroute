from dataclasses import dataclass
from typing import List

@dataclass
class Flow:
    id: str
    src_service: str
    dst_service: str
    max_latency: float
    rate: float
    
    def required_bw(self, pckt_size: float) -> float:
        return self.rate * pckt_size

@dataclass
class Router:
    id: str
    qtime: float

@dataclass
class Host:
    id: str
    services: List[str]

@dataclass
class Link:
    src: str
    dst: str
    bw: float
    length: float

@dataclass
class Path:
    id: str
    src: str
    dst: str
    nodes: List[str]

@dataclass
class Routing:
    flow_id: str
    path_id: str