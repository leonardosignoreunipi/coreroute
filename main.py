import networkx as nx
import janus_swi as janus
import matplotlib.pyplot as plt
import heapq
import time

### --- Constants ---
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
    
    janus.query_once("retractall(pcktSize(_, _))")
    janus.query_once("retractall(speedOfLight(_))")
    janus.query_once("retractall(host(_, _))")
    janus.query_once("retractall(router(_, _))")
    janus.query_once("retractall(link(_, _, _, _))")
    janus.query_once("retractall(flow(_, _, _, _, _))")
    janus.query_once("retractall(routing(_, _))")
    janus.query_once("retractall(path(_, _, _, _))")
    janus.query_once("retractall(pathsCandidates(_, _))")
    
    janus.query_once("assertz(pcktSize(_,PcktSize))", {"PcktSize": PCKT_SIZE})
    janus.query_once("assertz(speedOfLight(SpeedOfLight))", {"SpeedOfLight": SPEED_OF_LIGHT})
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
    
    for d in  janus.query("speedOfLight(SpeedOfLight)"):
        print(f"speedOfLight({d['SpeedOfLight']}).")
    
    for d in janus.query("pcktSize(_, PacktSize)"):
        print(f"pcktSize(_, {d['PacktSize']}).")
        
    for d in janus.query("host(Id, Services)"):
        print(f"host({d['Id']}, {d['Services']}).")
        
    for d in janus.query("router(Id, QTime)"):
        print(f"router({d['Id']}, {d['QTime']}).")
        
    for d in janus.query("link(Src, Dst, Bw, Length)"):
        print(f"link({d['Src']}, {d['Dst']}, {d['Bw']}, {d['Length']}).")
        
    for d in janus.query("flow(Id, SrcSvc, DstSvc, MaxLat, Rate)"):
        print(f"flow({d['Id']}, {d['SrcSvc']}, {d['DstSvc']}, {d['MaxLat']}, {d['Rate']}).")
    
    for d in janus.query("path(Id, Src, Dst, Nodes)"):
        print(f"path({d['Id']}, {d['Src']}, {d['Dst']}, {d['Nodes']}).")
    
    for d in janus.query("pathsCandidates(FlowId, Paths)"):
        print(f"pathsCandidates({d['FlowId']}, {d['Paths']}).")
        
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
        
    all_paths = list(nx.all_simple_paths(G, source=src, target=dst))# :(
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

def crRoutingWithHeap(G, paths, okflows, koflows):
    
    flow_rates = {f[0]: f[4] for f in flows} #sort flows by decreasing packet rate
    koflows.sort(key=lambda routing: flow_rates[routing["flow"]], reverse=True)
    temp_koflows = list(koflows)
    while len(temp_koflows) > 0:
        routing = temp_koflows.pop() #take the flow with the lowest packet rate among the KoFlows
        flowId = routing["flow"]
        old_path_nodes = paths[flowId][1]
        requiredBandwidth = flow_rates[flowId] * PCKT_SIZE
        
        Gpruned = pruningPerBandwith(G,requiredBandwidth)
        
        heap = build_heap(Gpruned, flowId, old_path_nodes)
        pathsIds = []
        for index, (_, pathNodes) in enumerate(heap):
            pathId = f"{flowId}_{index + 1}"
            pathsIds.append(pathId)
            janus.query_once("assertz(path(PathId, Src, Dst, Path))", {"PathId": pathId, "Src": pathNodes[0], "Dst": pathNodes[-1], "Path": pathNodes})
        janus.query_once("assertz(pathsCandidates(FlowId, PathIds))", {"FlowId": flowId, "PathIds": pathsIds})
    
    ko_terms = [f"routing({r['flow']}, {r['path']})" for r in koflows]
    ok_terms = [f"routing({r['flow']}, {r['path']})" for r in okflows]

    ko_list = f"[{', '.join(ko_terms)}]"
    ok_list = f"[{', '.join(ok_terms)}]"
    query = f"""
        crRouting({ko_list}, {ok_list}, _NewValidRoutingsTemp),
        findall(_{{flowId: _F, pathId: _P}}, member(routing(_F,_P), _NewValidRoutingsTemp), NewValidRoutings).
    """
    try:
        result = janus.query_once(query)
        if result['NewValidRoutings']: 
            return result["NewValidRoutings"]
        else: return []
    except Exception as e:
        print(f"❌ Errore critico nel ricalcolo: {e}")
        return []

def updateRoutings(newValidRoutings):
    janus.query_once("retractall(routing(_, _))")
    for r in newValidRoutings:
                janus.query_once("assertz(routing(FlowId, PathId))", {"FlowId":r['flowId'], "PathId":r['pathId']})

def pruningPerBandwith(G, requireBandwidth):
    def filter_edge(u, v):
        return G[u][v]['bw'] >= requireBandwidth
    
    Gpruned = nx.subgraph_view(G, filter_edge=filter_edge)
    return Gpruned

def __main__():
    
    G = nx.Graph()
    
    G = build_graph(G, hosts, routers, links)
    
    oldRouting = find_paths(G, flows) #paths = {flowId: (pathId, path)}
    
    inizialize_janus_kb(G, oldRouting)
    
    startTime = time.time()
    okflows, koflows = partition()
    
    newValidRoutings = crRoutingWithHeap(G, oldRouting, okflows, koflows)
    endTime = time.time()
    
    updateRoutings(newValidRoutings)
    print(f"\ntime: {endTime - startTime}")
    print(f"\nNewValidRoutings:{newValidRoutings}")
   
    
if __name__ == "__main__":
    __main__()