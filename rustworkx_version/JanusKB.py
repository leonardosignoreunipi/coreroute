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

    def clear_kb(self):
        """Remove all dynamic facts from the Prolog runtime.
        Must be called between trials that share the same OS process (e.g. Ray workers)."""
        try:
            for pred in ["host/2", "router/2", "link/4", "path/4", "flow/5",
                         "routing/2", "pathsCandidates/2", "speedOfLight/1", "pcktSize/2"]:
                j.query_once(f"retractall({pred})")
        except Exception as e:
            logger.warning(f"clear_kb warning: {e}")

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
    
    def update_janus_kb(self, newValidRoutings, failedRoutings=[]):
        """
        This function updates the Janus KB with new valid routings and failed routings.
        It first retracts all existing routing facts, then asserts the new valid routings.
        For failed routings, it retracts the existing path and asserts a new path with an empty node list, and then asserts the routing.
        """

        try:
            j.query_once("retractall(routing(_, _))")
            for r in newValidRoutings:
                j.query_once("assertz(routing(FlowId, PathId))", {"FlowId": str(r.flow_id), "PathId": str(r.path_id)})
            for r in failedRoutings:
                j.query_once("retractall(path(PathId, _, _, _))", {"PathId": str(r.path_id)})
                j.query_once("assertz(path(PathId, Src, Dst, []))", {"PathId": str(r.path_id), "Src": str(self.config.flows[r.flow_id].src_service), "Dst": str(self.config.flows[r.flow_id].dst_service)})
                j.query_once("assertz(routing(FlowId, PathId))", {"FlowId": str(r.flow_id), "PathId": str(r.path_id)})
        except Exception as e:
            logger.error(f"Error updating Janus KB: {e}")
            raise JanusKBError(f"Error updating Janus KB: {e}")

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
    
    def query_cr_routings(self, koflows: List[Routing], okflows: List[Routing]) -> tuple[List[Routing], List[Routing]]:
        ko_terms = [f"routing('{r.flow_id}', '{r.path_id}')" for r in koflows]
        ok_terms = [f"routing('{r.flow_id}', '{r.path_id}')" for r in okflows]

        ko_list = f"[{', '.join(ko_terms)}]"
        ok_list = f"[{', '.join(ok_terms)}]"

        query = f"""
            crRouting({ko_list}, {ok_list}, _NewValidRoutingsTemp, _FailedTemp),
            findall(_{{flowId: _F, pathId: _P}}, member(routing(_F, _P), _NewValidRoutingsTemp), NewValidRoutings),
            findall(_{{flowId: _F, pathId: _P}}, member(routing(_F, _P), _FailedTemp), FailedRoutings).
        """

        try:
            result = j.query_once(query)
            new_routings = [Routing(flow_id=d["flowId"], path_id=d["pathId"]) for d in result["NewValidRoutings"]]
            failed_routings = [Routing(flow_id=d["flowId"], path_id=d["pathId"]) for d in result["FailedRoutings"]]
            return new_routings, failed_routings
        except Exception as e:
            logger.error(f"Error in recalculation: {e}")
            raise JanusKBError(f"Error in recalculation: {e}")
        
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

    def reset_all_routings(self):
        """Reset all flows to KO by clearing every routing and path, then restoring
        initial empty-path entries.  After this call, get_partition() returns all
        flows as ko_flows (as if the network had never been routed)."""
        try:
            j.query_once("retractall(routing(_, _))")
            j.query_once("retractall(path(_, _, _, _))")
            j.query_once("retractall(pathsCandidates(_, _))")
            for f in self.config.flows.values():
                init_path_id = f"p_{f.id}_init"
                j.query_once(
                    "assertz(path(PathId, Src, Dst, []))",
                    {"PathId": init_path_id, "Src": str(f.src_service), "Dst": str(f.dst_service)}
                )
                j.query_once(
                    "assertz(routing(FlowId, PathId))",
                    {"FlowId": str(f.id), "PathId": init_path_id}
                )
        except Exception as e:
            logger.error(f"Error resetting routings: {e}")
            raise JanusKBError(f"Error resetting routings: {e}")

    def snapshot_kb_state(self) -> dict:
        """Salva lo stato corrente di routing e path dalla KB Prolog.
        Usato per preservare lo stato post-init e ripristinarlo tra perturbazioni diverse."""
        try:
            routings = list(j.query("routing(FlowId, PathId)"))
            paths    = list(j.query("path(PathId, Src, Dst, Nodes)"))
            return {"routings": routings, "paths": paths}
        except Exception as e:
            logger.error(f"Snapshot KB failed: {e}")
            raise JanusKBError(f"Snapshot KB failed: {e}")

    def restore_kb_state(self, snapshot: dict):
        """Ripristina routing e path dalla snapshot (es. stato post-init).
        Cancella lo stato corrente e riasserisce quello salvato."""
        try:
            j.query_once("retractall(routing(_, _))")
            j.query_once("retractall(path(_, _, _, _))")
            j.query_once("retractall(pathsCandidates(_, _))")
            for r in snapshot["routings"]:
                j.query_once("assertz(routing(FlowId, PathId))",
                             {"FlowId": r["FlowId"], "PathId": r["PathId"]})
            for p in snapshot["paths"]:
                j.query_once("assertz(path(PathId, Src, Dst, Nodes))",
                             {"PathId": p["PathId"], "Src": p["Src"],
                              "Dst": p["Dst"], "Nodes": p["Nodes"]})
        except Exception as e:
            logger.error(f"Restore KB failed: {e}")
            raise JanusKBError(f"Restore KB failed: {e}")

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
    
    