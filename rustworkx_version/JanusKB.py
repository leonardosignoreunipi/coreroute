import janus_swi as j
from typing import List
from ConfigLoader import TopologyConfig
from models import Routing
import logging

logger = logging.getLogger(__name__)

class JanusKBError(Exception):
    """Custom exception for JanusKB-related errors."""
    pass
class JanusKB: 
    def __init__(self, config: TopologyConfig, prolog_kb_path: str):
        if not config:
            raise JanusKBError("Config cannot be None.")
        if not prolog_kb_path:
            raise JanusKBError("Prolog KB path cannot be empty.")
        self.config = config
        self.prolog_kb_path = prolog_kb_path

    def initialize_kb(self):
        try:
            j.consult(self.prolog_kb_path)
        
            j.query_once("assertz(pcktSize(_,PcktSize))", {"PcktSize": self.config.pckt_size})#TODO sto ignorando la possibilità di avere un packsize per flusso
            j.query_once("assertz(speedOfLight(SpeedOfLight))", {"SpeedOfLight": self.config.speed_of_light})
        
            for h in self.config.hosts:
                j.query_once("assertz(host(HostId, Services))", {"HostId": str(h.id), "Services": h.services})
            for r in self.config.routers:
                j.query_once("assertz(router(RouterId, QTime))", {"RouterId": str(r.id), "QTime": float(r.qtime)})
            for l in self.config.links:
                j.query_once("assertz(link(Src, Dst, BW, Length))", {"Src": str(l.src), "Dst": str(l.dst), "BW": float(l.bw), "Length": float(l.length)})
            for f in self.config.flows.values():
                j.query_once("assertz(flow(FlowId, SrcSvc, DstSvc, MaxLat, Rate))", {"FlowId": str(f.id), "SrcSvc": str(f.src_service), "DstSvc": str(f.dst_service), "MaxLat": float(f.max_latency), "Rate": float(f.rate)})
            for p in self.config.paths.values():
                j.query_once("assertz(path(PathId, Src, Dst, Path))", {"PathId": str(p.id), "Src": str(p.src), "Dst": str(p.dst), "Path": p.nodes})
            for r in self.config.routings:
                j.query_once("assertz(routing(FlowId, PathId))", {"FlowId": str(r.flow_id), "PathId": str(r.path_id)})
        except Exception as e:
            msg = f"Errore critico durante l'inizializzazione della KB Prolog: {e}"
            logger.critical(msg)
            raise JanusKBError(msg)
        
    def update_links_bandwidth(self, degraded_links: list[tuple]): 
        updated_count = 0
        for src, dst, new_bw in degraded_links:
            query = "link(Src, Dst, _, Length) ; link(Dst, Src, _, Length)"
            res = j.query_once(query, {"Src": str(src), "Dst": str(dst)})
            
            if res:
                length = res["Length"]
                
                j.query_once("retractall(link(Src, Dst, _, _))", {"Src": str(src), "Dst": str(dst)})
                j.query_once("retractall(link(Dst, Src, _, _))", {"Src": str(src), "Dst": str(dst)})
                
                j.query_once("assertz(link(Src, Dst, BW, Length))", {"Src": str(src), "Dst": str(dst), "BW": float(new_bw), "Length": float(length)})
                updated_count += 1
            else:
                logger.warning(f"Link {src} <-> {dst} not found in KB. Cannot update bandwidth.")
                
        return updated_count
    
    def update_janus_kb(self, newValidRoutings):
        j.query_once("retractall(routing(_, _))")
        for r in newValidRoutings:
            j.query_once("assertz(routing(FlowId, PathId))", {"FlowId": str(r.flow_id), "PathId": str(r.path_id)})

    def query_partition(self):
        query = """
            partition(_OkFlowsTemp, _KoFlowsTemp),
            findall(_{flowId: _F, pathId: _P}, member(routing(_F, _P), _OkFlowsTemp), OkFlows), 
            findall(_{flowId: _F, pathId: _P}, member(routing(_F, _P), _KoFlowsTemp), KoFlows).
        """
        try:
            result = j.query_once(query)
            ok_routings = [Routing(flow_id=d["flowId"], path_id=d["pathId"]) for d in result["OkFlows"]]
            ko_routings = [Routing(flow_id=d["flowId"], path_id=d["pathId"]) for d in result["KoFlows"]]
            return ok_routings, ko_routings
        except Exception as e:
            logger.error(f"Error during partitioning: {e}")
            raise JanusKBError(f"Error during partitioning: {e}")
    
    def query_cr_routings(self, koflows: List[Routing],okflows: List[Routing] ) -> List[Routing]:
        ko_terms = [f"routing({r.flow_id}, {r.path_id})" for r in koflows]
        ok_terms = [f"routing({r.flow_id}, {r.path_id})" for r in okflows]

        ko_list = f"[{', '.join(ko_terms)}]"
        ok_list = f"[{', '.join(ok_terms)}]"

        query = f"""
            crRouting({ko_list}, {ok_list}, _NewValidRoutingsTemp),
            findall(_{{flowId: _F, pathId: _P}}, member(routing(_F, _P), _NewValidRoutingsTemp), NewValidRoutings).
        """

        try:
            result = j.query_once(query)
            if result['NewValidRoutings']:
                return [Routing(flow_id=d["flowId"], path_id=d["pathId"]) for d in result["NewValidRoutings"]]
            else: return []
        except Exception as e:
            logger.error(f"Error in recalculation: {e}")
            return []
    
    def get_routings(self):
        query = "routing(FlowId, PathId), path(PathId, _, _, Nodes)"
        try:
            results = list(j.query(query))
            return results
        except Exception as e:
            logger.error(f"Error retrieving routings: {e}")
            raise JanusKBError(f"Error retrieving routings: {e}")

    def get_path(self, pathId: str):
        if not pathId:
            raise JanusKBError("Path ID cannot be empty.")
        query = f"path({pathId}, _, _, Nodes)"
        try:
            result = j.query_once(query)
            return result["Nodes"]
        except Exception as e:
            logger.error(f"Error retrieving path: {e}")
            raise JanusKBError(f"Error retrieving path: {e}")

    def put_candidates_paths(self, flowId: str, pathIds: List[str]):
        if not flowId:
            raise JanusKBError("Flow ID cannot be empty.")
        try:
            j.query_once("retractall(pathsCandidates(FlowId, _))", {"FlowId": flowId})
            j.query_once("assertz(pathsCandidates(FlowId, PathIds))", {"FlowId": flowId, "PathIds": pathIds})

        except Exception as e:
            logger.error(f"Error putting candidate paths: {e}")
            raise JanusKBError(f"Error putting candidate paths: {e}")

    def put_path(self, pathId: str, src: str, dst: str, path: List[str]):
        if not pathId or not src or not dst or not path:
            raise JanusKBError("Path ID, source, destination, and path cannot be empty.")
        try:
            j.query_once("retractall(path(PathId, _, _, _))", {"PathId": pathId})
            j.query_once("assertz(path(PathId, Src, Dst, Path))", {"PathId": pathId, "Src": src, "Dst": dst, "Path": path})
        except Exception as e:
            logger.error(f"Error putting path: {e}")
            raise JanusKBError(f"Error putting path: {e}")

    def put_routing(self, flowId: str, pathId: str):
        if not flowId or not pathId:
            raise JanusKBError("Flow ID and Path ID cannot be empty.")
        try:
            j.query_once("assertz(routing(FlowId, PathId))", {"FlowId": flowId, "PathId": pathId})
        except Exception as e:
            logger.error(f"Error putting routing: {e}")
            raise JanusKBError(f"Error putting routing: {e}")

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
    
    