import networkx as nx
import janus_swi as janus
import matplotlib.pyplot as plt

### --- Constants --- ###
SPEED_OF_LIGHT = 300000 
PCKT_SIZE = 256

### --- Network Topology --- ###
flows = [
            ("f1", "s1", "s3", 17, 1), 
            ("f2", "s2", "s4", 17, 3)
        ]

links = [
            ("h1", "r1", 1024, 10),
            ("r1", "r2", 1024, 10),
            ("r2", "h2", 1024, 10),
            ("r1", "r3", 1024, 10),
            ("r3", "h2", 1024, 10)
        ]

routers = [
            ("r1", 1),
            ("r2", 1),
            ("r3", 1)
        ]

hosts = [
            ("h1", ["s1", "s2"]),
            ("h2", ["s3", "s4"])
        ]

def build_graph(graph, hosts, routers, links):
    assert graph is not None
    assert len(hosts) > 0
    assert len(routers) > 0 
    assert len(links) > 0
    
    for hostId, services in hosts:
        graph.add_node(hostId, type="Host", services=services)
    for routerId, qtime in routers:
        graph.add_node(routerId, type="Router", qtime=qtime)
    for src, dst, bw, length in links:
        graph.add_edge(src, dst, bw=bw, length=length)
        
    return graph

def inizialize_path_graph(graph, flows):
    assert graph is not None
    assert len(flows) > 0
    
    paths = {}
    
    for index, (flowId, SrcService, DstService, _, _) in enumerate(flows):
        
        src = next((hostId for hostId, services in hosts if SrcService in services), None)
        dst = next((hostId for hostId, services in hosts if DstService in services), None)
        
        if src and dst: 
           paths[flowId] = (f"p{index + 1}", nx.shortest_path(graph, source=src, target=dst, weight='length'))
        else: print(f"Error: Source or destination service not found for flow {flowId}")
    return paths

def inizialize_janus_kb(graph, paths):
    assert graph is not None
    assert len(paths) > 0
    
    janus.consult('routing_core.pl')
    
    janus.query_once("retractall(host(_, _))")
    janus.query_once("retractall(router(_, _))")
    janus.query_once("retractall(link(_, _, _, _))")
    janus.query_once("retractall(flow(_, _, _, _, _))")
    janus.query_once("retractall(routing(_, _))")
    janus.query_once("retractall(path(_, _, _, _))")
    
    for hostId, services in hosts:
        janus.query_once("assertz(host(HostId, Services))", {"HostId": hostId, "Services": services})
    for routerId, qtime in routers:
        janus.query_once("assertz(router(RouterId, QTime))", {"RouterId": routerId, "QTime": qtime})
    for src, dst, bw, length in links:
        janus.query_once("assertz(link(Src, Dst, BW, Length))", {"Src": src, "Dst": dst, "BW": bw, "Length": length})
    for flow_id, srcService, dstService, max_latency, pckt_rate in flows:
        janus.query_once("assertz(flow(FlowId, SrcService, DstService, MaxLatency, PcktRate))", {"FlowId": flow_id, "SrcService": srcService, "DstService": dstService, "MaxLatency": max_latency, "PcktRate": pckt_rate})
    for flowId, (pathId, path) in paths.items():
        janus.query_once("assertz(path(PathId, Src, Dst, Path))", {"PathId": pathId, "Src": path[0], "Dst": path[-1], "Path": path})
        janus.query_once("assertz(routing(FlowId, PathId))", {"FlowId": flowId, "PathId": pathId})

def print_prolog_facts():
    print("\n=== STATO ATTUALE DEI DATI IN PROLOG ===")
    
    print("\n--- HOSTS ---")
    for d in janus.query("host(Id, Services)"):
        print(f"host({d['Id']}, {d['Services']}).")
        
    print("\n--- ROUTERS ---")
    for d in janus.query("router(Id, QTime)"):
        print(f"router({d['Id']}, {d['QTime']}).")
        
    print("\n--- LINKS ---")
    for d in janus.query("link(Src, Dst, Bw, Length)"):
        print(f"link({d['Src']}, {d['Dst']}, {d['Bw']}, {d['Length']}).")
        
    print("\n--- FLOWS ---")
    for d in janus.query("flow(Id, SrcSvc, DstSvc, MaxLat, Rate)"):
        print(f"flow({d['Id']}, {d['SrcSvc']}, {d['DstSvc']}, {d['MaxLat']}, {d['Rate']}).")
        
    print("\n--- PATHS ---")
    for d in janus.query("path(Id, Src, Dst, Nodes)"):
        print(f"path({d['Id']}, {d['Src']}, {d['Dst']}, {d['Nodes']}).")
        
    print("\n--- ROUTING ATTUALI ---")
    for d in janus.query("routing(FlowId, PathId)"):
        print(f"routing({d['FlowId']}, {d['PathId']}).")
        
    print("=======================================\n")


def partition():
    query = """
        partition(_OkFlowsTemp, _KoFlowsTemp),
        findall(_{flow: _F, path: _P}, member(routing(_F, _P), _OkFlowsTemp), OkFlows),
        findall(_{flow: _F, path: _P}, member(routing(_F, _P), _KoFlowsTemp), KoFlows).
    """
    result = janus.query_once(query)
    return result["OkFlows"], result["KoFlows"]

def isValidRouting(flowId, pathId):
    query = """
        partition(_OkFlowsTemp, _KoFlowsTemp),
        is_routing_valid(FlowId, PathId, _OkFlowsTemp).
    """
    result = janus.query_once(query, {"FlowId": flowId, "PathId": pathId})
    return result["truth"]

def crRouting():
    query = """
        partition(_OkFlowsTemp, _KoFlowsTemp),
        crRouting(_OkFlowsTemp, _KoFlowsTemp, _NewRoutingTemp),
        findall(_{flow: _F, pathId: _P}, member(routing(_F, _P), _NewRoutingTemp), NewValidRouting).
    """
    result = janus.query_once(query)
    return result["NewValidRouting"]

def __main__():
    G = nx.Graph()
    
    print("Building graph...")
    G = build_graph(G, hosts, routers, links)
    
    print("\nKB:", )
    
    print("\nInitialize graph paths...")
    paths = inizialize_path_graph(G, flows)
    print("\nInitial paths:", paths)
    
    print("\nInitialize Janus KB...")
    inizialize_janus_kb(G, paths)
    print("\nKB initialized with hosts, routers, links, and flows.")
    
    okflows, koflows = partition()
    
    print("\nValid routings (OkFlows):", okflows)
    print("\nInvalid routings (KoFlows):", koflows)
    
    print_prolog_facts()
    
    print("\nIsRoutingValid(f1,p1)", isValidRouting("f1", "p1"))
    print("crRouting", crRouting())
   
    
if __name__ == "__main__":
    __main__()