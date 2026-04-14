import networkx as nx
import janus_swi as janus
import matplotlib.pyplot as plt
import heapq

### --- Constants --- ### NON VENGONO USATE
SPEED_OF_LIGHT = 300000 
PCKT_SIZE = 256

### --- Network Topology --- ###

flows = [
            ("f1", "s1", "s3", 7, 4), 
            ("f2", "s2", "s4", 7, 3), 
            ("f3", "s1", "s4", 7, 3),
            ("f4", "s1", "s4", 7, 3),
            ("f5", "s1", "s4", 7, 3)
        ]

links = [
            ("h1", "r1", 2048, 10),
            ("r1", "r2", 2048, 10),
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

def find_paths(graph, flows):
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

def print_routings():
    print("\n=== ROUTING ATTUALI ===")
    for d in janus.query("routing(FlowId, PathId)"):
        print(f"routing({d['FlowId']}, {d['PathId']}).")
    print("=======================\n")

def get_path_edges(path):
    return set(frozenset([u, v]) for u, v in zip(path[:-1], path[1:]))

def diff_score(oldPath, newPath):
    old_edges = get_path_edges(oldPath)
    new_edges = get_path_edges(newPath)
    return len(new_edges - old_edges)

def build_heap(G, flowId, old_path):
    flowHeap = []
        
    FlowId = flowId
        
    src = old_path[0]
    dst = old_path[-1]
        
    all_paths = list(nx.all_simple_paths(G, source=src, target=dst))
    for newPath in all_paths:
        diffScore = diff_score(old_path, newPath)
        heapq.heappush(flowHeap, (diffScore, newPath))
    
    return flowHeap
    
def partition():
    query = """
        partition(_OkFlowsTemp, _KoFlowsTemp),
        findall(_{flow: _F, path: _P}, member(routing(_F, _P), _OkFlowsTemp), OkFlows),
        findall(_{flow: _F, path: _P}, member(routing(_F, _P), _KoFlowsTemp), KoFlows).
    """
    result = janus.query_once(query)
    return result["OkFlows"], result["KoFlows"]

def deleteKoFlows(KoFlows):
    for routing in KoFlows:
        janus.query_once("retract(routing(FlowId, _))", {"FlowId": routing["flow"]})

def is_valid_path(flowId, pathNodes):
    new_path_id = f"new_{flowId}"
    src = pathNodes[0]
    dst = pathNodes[-1]
    
    janus.query_once("assertz(path(PathId, Src, Dst, Nodes))", {"PathId": new_path_id, "Src": src, "Dst": dst, "Nodes": pathNodes})
    
    janus.query_once("assertz(routing(FlowId, PathId))", {"FlowId": flowId, "PathId": new_path_id})
    
    query = """
        partition(_OkFlowsTemp, _KoFlowsTemp),
        member(routing(FlowId, PathId), _OkFlowsTemp).
    """
    result = janus.query_once(query, {"FlowId": flowId, "PathId": new_path_id})
    
    if result["truth"] == False:
        janus.query_once("retract(routing(FlowId, _))", {"FlowId": flowId})
        janus.query_once("retract(path(PathId, _, _, _))", {"PathId": new_path_id})
    
    return result["truth"]

def crRouting():
    query = """
        partition(_OkFlowsTemp, _KoFlowsTemp),
        crRouting(_OkFlowsTemp, _KoFlowsTemp, _NewRoutingTemp),
        findall(_{flow: _F, pathId: _P}, member(routing(_F, _P), _NewRoutingTemp), NewValidRouting).
    """
    result = janus.query_once(query)
    return result["NewValidRouting"]

def crRoutingWithHeap(G, paths, koflows):
    deleteKoFlows(koflows)
    
    flow_rates = {f[0]: f[4] for f in flows}
    koflows.sort(key=lambda routing: flow_rates[routing["flow"]])
    
    invalidRoutings = []
    
    while len(koflows) > 0:
        
        routing = koflows.pop(0)
        flowId = routing["flow"]
        old_path_nodes = paths[flowId][1]
        
        heap = build_heap(G, flowId, old_path_nodes)
        if len(heap) == 0:
            print(f"No paths for flow {flowId}.") 
            continue
        
        if len(heap) == 0:
            print(f"Not existing path for flow {flowId}.")
            continue
        
        next_path = heapq.heappop(heap)[1]
        
        while (is_valid_path(flowId, next_path) == False):
            if len(heap) == 0:
                next_path = None
                break
            next_path = heapq.heappop(heap)[1]
        if next_path is None:
            invalidRoutings.append(routing)
            print(f"No valid alternative path found for flow {flowId}.")
            continue
    for routing in invalidRoutings:
        janus.query_once("assertz(routing(FlowId, PathId))", {"FlowId": routing["flow"], "PathId": routing["path"]}) ### insert old path for invalid routings
    

def __main__():
    
    G = nx.Graph()
    
    G = build_graph(G, hosts, routers, links)
    
    paths = find_paths(G, flows) #paths = {flowId: (pathId, path)}
    
    inizialize_janus_kb(G, paths)
    
    okflows, koflows = partition()
    print(f"\n\nOkFlows:{okflows}\n\nKoFlows:{koflows}\n")
    
    crRoutingWithHeap(G, paths, koflows)
    
    print_routings()
   
    
if __name__ == "__main__":
    __main__()