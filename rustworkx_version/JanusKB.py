import janus_swi as j
from typing import List
from ConfigLoader import TopologyConfig
from models import Routing

class JanusKB: 
    def __init__(self, config: TopologyConfig, prolog_kb_path: str):
        self.config = config
        self.prolog_kb_path = prolog_kb_path

    def initialize_kb(self):
        j.consult(self.prolog_kb_path)
        
        j.query_once("assertz(pcktSize(_,PcktSize))", {"PcktSize": self.config.pckt_size})#TODO sto ignorando la possibilità di avere un packsize per flusso
        j.query_once("assertz(speedOfLight(SpeedOfLight))", {"SpeedOfLight": self.config.speed_of_light})
        
        for h in self.config.hosts:
            j.query_once("assertz(host(HostId, Services))", {"HostId": h.id, "Services": h.services})
        for r in self.config.routers:
            j.query_once("assertz(router(RouterId, QTime))", {"RouterId": r.id, "QTime": r.qtime})
        for l in self.config.links:
            j.query_once("assertz(link(Src, Dst, BW, Length))", {"Src": l.src, "Dst": l.dst, "BW": l.bw, "Length": l.length})
        for f in self.config.flows.values():
            j.query_once("assertz(flow(FlowId, SrcSvc, DstSvc, MaxLat, Rate))", {"FlowId": f.id, "SrcSvc": f.src_service, "DstSvc": f.dst_service, "MaxLat": f.max_latency, "Rate": f.rate})
        for p in self.config.paths.values():
            j.query_once("assertz(path(PathId, Src, Dst, Path))", {"PathId": p.id, "Src": p.src, "Dst": p.dst, "Path": p.nodes})
        for r in self.config.routings:
            j.query_once("assertz(routing(FlowId, PathId))", {"FlowId": r.flow_id, "PathId": r.path_id})

    def update_links_bandwidth(self, degraded_links: list[tuple]): 
        updated_count = 0
        for src, dst, new_bw in degraded_links:
            # Recuperiamo la lunghezza attuale del link per non perderla
            query = "link(Src, Dst, _, Length) ; link(Dst, Src, _, Length)"
            res = j.query_once(query, {"Src": src, "Dst": dst})
            
            if res:
                length = res["Length"]
                
                # Rimuoviamo il vecchio fatto in entrambe le direzioni (come visto in precedenza)
                j.query_once("retractall(link(Src, Dst, _, _))", {"Src": src, "Dst": dst})
                j.query_once("retractall(link(Dst, Src, _, _))", {"Src": src, "Dst": dst})
                
                # Asseriamo il nuovo fatto con la banda aggiornata
                j.query_once("assertz(link(Src, Dst, BW, Length))", {"Src": src, "Dst": dst, "BW": new_bw, "Length": length})
                updated_count += 1
                
        return updated_count
    
    def update_janus_kb(self, newValidRoutings):
        j.query_once("retractall(routing(_, _))")
        for r in newValidRoutings:
            j.query_once("assertz(routing(FlowId, PathId))", {"FlowId":r.flow_id, "PathId":r.path_id})

    def query_partition(self):
        query = """
            partition(_OkFlowsTemp, _KoFlowsTemp),
            findall(_{flowId: _F, pathId: _P}, member(routing(_F, _P), _OkFlowsTemp), OkFlows), 
            findall(_{flowId: _F, pathId: _P}, member(routing(_F, _P), _KoFlowsTemp), KoFlows).
        """ #TODO: eliminare il doppio findall, o almeno rinominare le chiavi del dizionario
        result = j.query_once(query)
        ok_routings = [Routing(flow_id=d["flowId"], path_id=d["pathId"]) for d in result["OkFlows"]]
        ko_routings = [Routing(flow_id=d["flowId"], path_id=d["pathId"]) for d in result["KoFlows"]]
        return ok_routings, ko_routings
    
    def query_cr_routings(self, koflows: List[Routing],okflows: List[Routing] ) -> List[Routing]:
        ko_terms = [f"routing({r.flow_id}, {r.path_id})" for r in koflows]
        ok_terms = [f"routing({r.flow_id}, {r.path_id})" for r in okflows]

        ko_list = f"[{', '.join(ko_terms)}]"
        ok_list = f"[{', '.join(ok_terms)}]"

        query = f"""
            crRouting({ko_list}, {ok_list}, _NewValidRoutingsTemp),
            findall(_{{flowId: _F, pathId: _P}}, member(routing(_F, _P), _NewValidRoutingsTemp), NewValidRoutings).
        """ #TODO: eliminare il doppio findall, o almeno rinominare le chiavi del dizionario


        try:
            result = j.query_once(query)
            if result['NewValidRoutings']:
                return [Routing(flow_id=d["flowId"], path_id=d["pathId"]) for d in result["NewValidRoutings"]]
            else: return []
        except Exception as e:
            print(f"Errore nel ricalcolo: {e}")
            return []
    
    def get_routings(self):
        query = "routing(FlowId, PathId), path(PathId, _, _, Nodes)"
        results = list(j.query(query))
        return results

    def get_path(self, pathId: str):
        query = f"path({pathId}, _, _, Nodes)"
        result = j.query_once(query)
        return result["Nodes"]

    def put_candidates_paths(self, flowId: str, pathIds: List[str]):
        j.query_once("assertz(pathsCandidates(FlowId, PathIds))", {"FlowId": flowId, "PathIds": pathIds})

    def put_path(self, pathId: str, src: str, dst: str, path: List[str]):
        j.query_once("assertz(path(PathId, Src, Dst, Path))", {"PathId": pathId, "Src": src, "Dst": dst, "Path": path})
    
    def put_routing(self, flowId: str, pathId: str):
        j.query_once("assertz(routing(FlowId, PathId))", {"FlowId": flowId, "PathId": pathId})
    
    def print_prolog_facts(self):
        print("\n=== KNOWLEDGE BASE ===")
        
        for d in  j.query("speedOfLight(SpeedOfLight)"):
            print(f"speedOfLight({d['SpeedOfLight']}).")
        
        for d in j.query("pcktSize(_, PacktSize)"):
            print(f"pcktSize(_, {d['PacktSize']}).")
        
        for h in j.query("host(HostId, Services)"):
            print(f"host({h['HostId']}, {h['Services']}).")

        for r in j.query("router(RouterId, QTime)"):
            print(f"router({r['RouterId']}, {r['QTime']}).")
        
        for l in j.query("link(Src, Dst, BW, Length)"):
            print(f"link({l['Src']}, {l['Dst']}, {l['BW']}, {l['Length']}).")
        
        for f in j.query("flow(FlowId, SrcSvc, DstSvc, MaxLat, Rate)"):
            print(f"flow({f['FlowId']}, {f['SrcSvc']}, {f['DstSvc']}, {f['MaxLat']}, {f['Rate']}).")
        
        for p in j.query("path(PathId, Src, Dst, Path)"):
            print(f"path({p['PathId']}, {p['Src']}, {p['Dst']}, {p['Path']}).")
        
        for r in j.query("routing(FlowId, PathId)"):
            print(f"routing({r['FlowId']}, {r['PathId']}).")
        
        for c in j.query("pathsCandidates(FlowId, PathIds)"):
            print(f"pathsCandidates({c['FlowId']}, {c['PathIds']}).")
        
        print("=" * 60)
        print("\n")
    
    