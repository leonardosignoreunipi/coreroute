from JanusKB import JanusKB
import janus_swi as j


class DebugKB:
    def __init__(self, kb: JanusKB):
        self.invoke_count = 0
        self.kb = kb
    
    def saves_snapshot_kb(self, msg: str = "snapshot kb\n"):
        """"Saves a snapshot of kb"""
        if self.invoke_count == 0:
            with open("kb_snapshot.txt", "w") as f:
                f.write(msg + "\n")
        self.invoke_count += 1
        
        with open("kb_snapshot.txt", "a") as f:
            f.write(msg + "\n")
            for d in  j.query("speedOfLight(SpeedOfLight)"):
                f.write(f"speedOfLight({d['SpeedOfLight']}).\n")
            
            for d in j.query("pcktSize(_, PacktSize)"):
                f.write(f"pcktSize(_, {d['PacktSize']}).\n")
        
            for h in j.query("host(HostId, Services)"):
                f.write(f"host({h['HostId']}, {h['Services']}).\n")

            for r in j.query("router(RouterId, QTime)"):
                f.write(f"router({r['RouterId']}, {r['QTime']}).\n")
        
            for l in j.query("link(Src, Dst, BW, Length)"):
                f.write(f"link({l['Src']}, {l['Dst']}, {l['BW']}, {l['Length']}).\n")
        
            for d in j.query("flow(FlowId, SrcSvc, DstSvc, MaxLat, Rate)"):
                f.write(f"flow({d['FlowId']}, {d['SrcSvc']}, {d['DstSvc']}, {d['MaxLat']}, {d['Rate']}).\n")
        
            for p in j.query("path(PathId, Src, Dst, Path)"):
                f.write(f"path({p['PathId']}, {p['Src']}, {p['Dst']}, {p['Path']}).\n")
        
            for r in j.query("routing(FlowId, PathId)"):
                f.write(f"routing({r['FlowId']}, {r['PathId']}).\n")
        
            for c in j.query("pathsCandidates(FlowId, PathIds)"):
                f.write(f"pathsCandidates({c['FlowId']}, {c['PathIds']}).\n")

