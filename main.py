import networkx as nx
import janus_swi as janus
import heapq
import json
from models import Flow, Router, Host, Link, Path, Routing

class SDNController:
    def __init__(self, config_path: str):
        self._load_config(config_path)
        self.graph = self._build_graph()

    def _load_config(self, config_path: str):
        with open(config_path, 'r') as f:
            config = json.load(f)
            
        self.speed_of_light = config['constants']['SPEED_OF_LIGHT']
        self.pckt_size = config['constants']['PCKT_SIZE']
        
        self.flows = {f['id']: Flow(**f) for f in config['flows']}
        self.paths = {p['id']: Path(**p) for p in config['paths']}
        self.routers = [Router(**r) for r in config['routers']] #in runtime dopo la costruzione del grafo ho una duplicazione di informazioni per host, router e link.
        self.hosts = [Host(**h) for h in config['hosts']]
        self.links = [Link(**l) for l in config['links']]
        self.routings = [Routing(**r) for r in config['routings']]

    def _build_graph(self):
        graph = nx.Graph()
        for h in self.hosts:
            graph.add_node(h.id, type="Host", services=h.services)
        for r in self.routers:
            graph.add_node(r.id, type="Router", qtime=r.qtime)
        for l in self.links:
            graph.add_edge(l.src, l.dst, bw=l.bw, length=l.length)

        lengths = [d['length'] for _, _, d in graph.edges(data=True)]
        bws = [d['bw']     for _, _, d in graph.edges(data=True)]

        self._max_link_lat = max(lengths) / self.speed_of_light  # secondi
        self._max_inv_bw   = 1.0 / min(bws)                      # 1/Mbps

        return graph

    def inizialize_janus_kb(self):
        janus.consult('routing_core.pl')
        
        janus.query_once("assertz(pcktSize(_,PcktSize))", {"PcktSize": self.pckt_size})#sto ignorando la possibilità di avere un packsize per flusso
        janus.query_once("assertz(speedOfLight(SpeedOfLight))", {"SpeedOfLight": self.speed_of_light})
        
        for h in self.hosts:
            janus.query_once("assertz(host(HostId, Services))", {"HostId": h.id, "Services": h.services})
        for r in self.routers:
            janus.query_once("assertz(router(RouterId, QTime))", {"RouterId": r.id, "QTime": r.qtime})
        for l in self.links:
            janus.query_once("assertz(link(Src, Dst, BW, Length))", {"Src": l.src, "Dst": l.dst, "BW": l.bw, "Length": l.length})
        for f in self.flows.values():
            janus.query_once("assertz(flow(FlowId, SrcSvc, DstSvc, MaxLat, Rate))", {"FlowId": f.id, "SrcSvc": f.src_service, "DstSvc": f.dst_service, "MaxLat": f.max_latency, "Rate": f.rate})
        for p in self.paths.values():
            janus.query_once("assertz(path(PathId, Src, Dst, Path))", {"PathId": p.id, "Src": p.src, "Dst": p.dst, "Path": p.nodes})
        for r in self.routings:
            janus.query_once("assertz(routing(FlowId, PathId))", {"FlowId": r.flow_id, "PathId": r.path_id})

    def partition(self):
        query = """
            partition(_OkFlowsTemp, _KoFlowsTemp),
            findall(_{flow: _F, path: _P}, member(routing(_F, _P), _OkFlowsTemp), OkFlows), 
            findall(_{flow: _F, path: _P}, member(routing(_F, _P), _KoFlowsTemp), KoFlows).
        """ #TODO: eliminare il doppio findall, o almeno rinominare le chiavi del dizionario
        result = janus.query_once(query)
        return result["OkFlows"], result["KoFlows"]

    def cr_routing(self, okflows, koflows):
        koflows.sort(key=lambda routing: self.flows[routing["flow"]].required_bw(self.pckt_size), reverse=True)
        
        flowsNodes = {r.flow_id: self.paths[r.path_id].nodes for r in self.routings}
        
        temp_koflows = list(koflows)
        while len(temp_koflows) > 0:
            routing = temp_koflows.pop() #take the flow with the lowest packet rate among the KoFlows
            flowId = routing["flow"]
            nodes = flowsNodes[flowId] 
            requiredBandwidth = self.flows[flowId].required_bw(self.pckt_size)
        
            Gpruned = self.pruning_per_bandwith(requiredBandwidth)
            candidates = self.search_candidates(Gpruned, nodes, flowId)
            if len(candidates) == 0:
                print(f"Not valid paths for flow: {flowId}")
            print(f"\nCandidates for flow {flowId}: {candidates}")
            pathsIds = []
            index = 0
            while len(candidates) > 0:
                diffScore, pathLength, nodes = heapq.heappop(candidates)
                pathId = f"{flowId}_{index + 1}"
                pathsIds.append(pathId)
                janus.query_once("assertz(path(PathId, Src, Dst, Path))", {"PathId": pathId, "Src": nodes[0], "Dst": nodes[-1], "Path": nodes})
                index += 1
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
            print(f"Errore critico nel ricalcolo: {e}")
            return []
        
    def print_prolog_facts(self):
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

    def print_flow_paths(self):
        print("\n=== CONFIGURAZIONE ROUTING ATTUALE (Flow -> Nodes) ===")
        query = "routing(FlowId, PathId), path(PathId, _, _, Nodes)"
        results = list(janus.query(query))
    
        if not results:
            print("Nessun routing attivo trovato nella Knowledge Base.")
        else:
            for d in results:
                flow_id = d['FlowId']
                nodes = d['Nodes']
                print(f"{flow_id} -> {nodes}")
            
        print("=====================================================\n")

    def diff_score(self, path1, path2): 
        set_path1 = set((u, v) for u, v in zip(path1[:-1], path1[1:]))
        set_path2 = set((u, v) for u, v in zip(path2[:-1], path2[1:]))
        return len(set_path1.symmetric_difference(set_path2))

    def _edge_weight(self, u: str, v: str, d: dict, old_edges: set, flowId,alpha: float = 0.45, beta: float = 0.45) -> float:
        flow = self.flows[flowId]
        costo_config = 0.0 if (u, v) in old_edges else 1.0
        dprop  = d['length'] / self.speed_of_light
        dtrasm = (self.pckt_size * flow.rate) / d['bw']
        node_data = self.graph.nodes.get(u, {})
        dqueue = node_data.get('qtime', 0.0) if node_data.get('type') == 'Router' else 0.0

        lat_norm = (dprop + dtrasm + dqueue) / self._max_link_lat

        bw_norm = (1.0 / d['bw']) / self._max_inv_bw

        print(f"COSTO: {costo_config + alpha * lat_norm + beta * bw_norm}")

        return costo_config + alpha * lat_norm + beta * bw_norm

    def search_candidates(self, graph_pruned, old_path, flowId, max_candidates=30):
        candidates = []
        src = old_path[0]
        dst = old_path[-1]
        set_old_path = set((u, v) for u, v in zip(old_path[:-1], old_path[1:]))

        def weight(u, v, d):
            return self._edge_weight(u, v, d, set_old_path, flowId)
                
        try:
            generator = nx.shortest_simple_paths(graph_pruned, src, dst, weight='weight')
            for _ in range(max_candidates):
                newPath = next(generator)
                print(newPath)
                diffScore = self.diff_score(old_path, newPath) #TODO devo finire l'intervallo con la stessa lunghezza
                heapq.heappush(candidates, (diffScore, len(newPath), newPath))
            
        except (nx.NetworkXNoPath, StopIteration):
            pass    
            
        return candidates

    def update_janus_kb(self, newValidRoutings):
        janus.query_once("retractall(routing(_, _))")
        for r in newValidRoutings:
            janus.query_once("assertz(routing(FlowId, PathId))", {"FlowId":r['flowId'], "PathId":r['pathId']})

    def pruning_per_bandwith(self, requireBandwidth):
        def filter_edge(u, v):
            return self.graph[u][v]['bw'] >= requireBandwidth
    
        Gpruned = nx.subgraph_view(self.graph, filter_edge=filter_edge)
        return Gpruned

def __main__():
    controller = SDNController('topology.json')
    controller.inizialize_janus_kb()
    print("\n\nCaricamento dati nella knowledge base...")
    controller.print_prolog_facts()
    okflows, koflows = controller.partition()
    print(f"Partition dei routing:\nOkflows: {okflows}\nKoflows: {koflows}\n\nRicerca nuovi percorsi...")
    newValidRoutings = controller.cr_routing(okflows, koflows)
    if newValidRoutings: controller.update_janus_kb(newValidRoutings)
    print(f"\n\nNewValidRouting: {newValidRoutings}")
    controller.print_flow_paths()

if __name__ == "__main__":
    __main__()