import networkx as nx
import janus_swi as janus
import heapq

### --- Constants ---
SPEED_OF_LIGHT = 300000 
PCKT_SIZE = 256

### --- Network Topology --- ###

flows = [
    ("f1", "s1", "s2", 20, 3),   
    ("f2", "s1", "s2", 20, 3),
]
 
routers = [
    ("r1", 1), ("r2", 1), ("r3", 1),
    ("r4", 1), ("r5", 1), ("r6", 1)
]
 
hosts = [
    ("h1", ["s1",]),
    ("h2", ["s2",]),
]
 
links = [
    ("h1", "r1", 2048, 1),
    ("r1", "r2", 2048, 1),
    ("r2", "r3", 2048, 1),
    ("r3", "h2", 1024, 1),
    ("h1", "r4", 1024, 1),
    ("r4", "r5", 2048, 1),
    ("r5", "r6", 2048, 1),
    ("r3", "r6", 2048, 1),
    ("r6", "h2", 1024, 1)
]

paths = [
    ("old_path", "h1", "h2", ["h1", "r1", "r2", "r3", "h2"]),
]

routings = [
    ("f1", "old_path"),
    ("f2", "old_path")
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
           paths[flowId] = (f"old_p{index + 1}", nx.shortest_path(graph, source=src, target=dst, weight='length'))
        else: print(f"Error: Source or destination service not found for flow {flowId}")
    return paths

def inizialize_janus_kb(graph):
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
    for pathId, src, dst, Nodes in paths:
        janus.query_once("assertz(path(PathId, Src, Dst, Path))", {"PathId": pathId, "Src": src, "Dst": dst, "Path": Nodes})
    for flowId, pathId in routings:
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

def print_flow_paths():
    """
    Stampa l'instradamento attuale mostrando il FlowId e la lista dei nodi fisici.
    Formato: flowId -> ['n1', 'n2', ...]
    """
    print("\n=== CONFIGURAZIONE ROUTING ATTUALE (Flow -> Nodes) ===")
    
    # Eseguiamo un join in Prolog tra routing/2 e path/4 tramite PathId
    query = "routing(FlowId, PathId), path(PathId, _, _, Nodes)"
    
    # Iteriamo sui risultati restituiti da Janus
    results = list(janus.query(query))
    
    if not results:
        print("Nessun routing attivo trovato nella Knowledge Base.")
    else:
        for d in results:
            flow_id = d['FlowId']
            nodes = d['Nodes']
            print(f"{flow_id} -> {nodes}")
            
    print("=====================================================\n")

def get_path_edges(path):
    return set(frozenset([u, v]) for u, v in zip(path[:-1], path[1:]))

def diff_score(oldPath, newPath):
    old_edges = get_path_edges(oldPath)
    new_edges = get_path_edges(newPath)
    return len(new_edges - old_edges)

def build_heap(G, old_path):
    flowHeap = []
        
    src = old_path[0]
    dst = old_path[-1]
        
    all_paths = list(nx.all_simple_paths(G, source=src, target=dst))# :(
    for newPath in all_paths:
        diffScore = diff_score(old_path, newPath)
        heapq.heappush(flowHeap, (diffScore, newPath))
    
    return flowHeap

def searchCandidates(G, old_path, max_candidates=5):
    candidates = []
        
    src = old_path[0]
    dst = old_path[-1]
    
    old_edges = set(frozenset([u, v]) for u, v in zip(old_path[:-1], old_path[1:]))
    
    def weight_function(u, v, edge_attr):
        return 0 if frozenset([u, v]) in old_edges else 1  
    
    try:
        generator = nx.shortest_simple_paths(G, src, dst, weight=weight_function)
        
        for _ in range(max_candidates):
            path = next(generator)
            candidates.append(path)
            
    except (nx.NetworkXNoPath, StopIteration):
        pass    
   
    return candidates

def partition():
    query = """
        partition(_OkFlowsTemp, _KoFlowsTemp),
        findall(_{flow: _F, path: _P}, member(routing(_F, _P), _OkFlowsTemp), OkFlows),
        findall(_{flow: _F, path: _P}, member(routing(_F, _P), _KoFlowsTemp), KoFlows).
    """
    result = janus.query_once(query)
    return result["OkFlows"], result["KoFlows"]

def crRouting(G, flowNodes, okflows, koflows):
    
    flow_rates = {f[0]: f[4] for f in flows} #sort flows by decreasing packet rate
    koflows.sort(key=lambda routing: flow_rates[routing["flow"]], reverse=True)
    
    temp_koflows = list(koflows)
    
    while len(temp_koflows) > 0:
        routing = temp_koflows.pop() #take the flow with the lowest packet rate among the KoFlows
        flowId = routing["flow"]
        nodes = flowNodes[flowId]
        requiredBandwidth = flow_rates[flowId] * PCKT_SIZE
        
        Gpruned = pruningPerBandwith(G,requiredBandwidth)
        
        candidates = searchCandidates(Gpruned, nodes, max_candidates=5)
        if len(candidates) == 0:
            print(f"Not valid paths for flow: {flowId}")
        
        pathsIds = []
        for index, nodes in enumerate(candidates):
            pathId = f"{flowId}_{index + 1}"
            pathsIds.append(pathId)
            janus.query_once("assertz(path(PathId, Src, Dst, Path))", {"PathId": pathId, "Src": nodes[0], "Dst": nodes[-1], "Path": nodes})
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

def update_janus_kb(newValidRoutings):
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
    
    inizialize_janus_kb(G)
    
    pathsDict = {p[0]: p[3] for p in paths}
    flowsNodes = {f_id: pathsDict[p_id] for f_id, p_id in routings}
    
    okRoutings, koRoutings = partition()
    
    newValidRoutings = crRouting(G, flowsNodes, okRoutings, koRoutings)
    
    update_janus_kb(newValidRoutings)
    
    print_flow_paths()
    
if __name__ == "__main__":
    __main__()