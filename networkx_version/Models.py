from dataclasses import dataclass
from typing import List

@dataclass
class Flow:
    """Traffic flow: endpoints expressed as services, plus latency/rate SLOs."""
    id: str
    src_service: str
    dst_service: str
    max_latency: float
    rate: float
    
    def required_bw(self, pckt_size: float) -> float:
        return self.rate * pckt_size

@dataclass
class Router:
    """Bandwidth required by the flow = packet rate * packet size."""
    id: str
    qtime: float

@dataclass
class Host:
    """Host node exposing a list of services."""
    id: str
    services: List[str]

@dataclass
class Link:
    """Undirected link with current/nominal bandwidth and physical length."""
    src: str
    dst: str
    bw: float
    bw_nominal: float
    length: float

@dataclass
class Path:
    """Named path: an ordered node list from src to dst."""
    id: str
    src: str
    dst: str
    nodes: List[str]

@dataclass
class Routing:
    """Binding of a flow to the path currently assigned to it."""
    flow_id: str
    path_id: str