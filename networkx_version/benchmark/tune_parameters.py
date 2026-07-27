import sys, os, re, random, tempfile, itertools
from pathlib import Path

BENCHMARK_DIR = Path(__file__).parent
REPO_ROOT     = BENCHMARK_DIR.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(BENCHMARK_DIR))

import ray
import epoch_benchmark as eb
from epoch_benchmark import (_build_system, _perturb_epoch, _reset_to_nominal,
                             _frac_degraded, epoch_benchmark_exception, _routes_from_snapshot)

RESULTS_CSV     = "tune_parameters.csv"
TOPOLOGIES      = ["iaag", "er", "ba"]
SIZES           = [500, 1000]
FLOW_FACTORS    = [1.00]
SEEDS           = [104729, 224737, 350377]
PCT_MODS        = [0.10, 0.20, 0.30, 0.50]
DEGRADE_FACTORS = [(0.5, 2.0), (0.5, 1.5), (0.6, 1.2)]
SCALES          = [1.0, 0.95, 0.90, 0.85, 0.80, 0.75, 0.70]
FLOOR_SIZES     = [250, 500, 750, 1000]
FLOOR_FF        = 1.00
EPOCHS          = 20
NUM_WORKERS     = 7


def _apply_scale(topo, scale):
    import build_topology as bt
    if topo == "iaag":
        bt.IAAG_BW_TIERS = {k: (lo * scale, hi * scale) for k, (lo, hi) in dict(bt.IAAG_BW_TIERS).items()}
    else:
        lo, hi = bt.ROUTER_BW
        bt.ROUTER_BW = (lo * scale, hi * scale)
        
def _mean_rr_bw(network, rr_edges):
    return sum(network.graph[u][v]["bw"] for u, v in rr_edges) / len(rr_edges)


def run_seq(network, kb, engine, rr_edges, post_init, degrade, pct, seed, num_flows, topo, n, ff):
    _reset_to_nominal(network, kb, rr_edges)
    kb.restore_kb_state(post_init)
    rng = random.Random(hash((seed, pct)) % (2 ** 32))
    rows = []
    for epoch in range(EPOCHS):
        _perturb_epoch(network, kb, rr_edges, pct, rng)
        frac   = _frac_degraded(network, rr_edges)
        avg_bw = _mean_rr_bw(network, rr_edges)

        ok_flows, ko_flows = engine.get_partition()
        new_valid, failed, no_path = engine.re_routing(ok_flows, ko_flows)
        kb.update_janus_kb(new_valid, failed)
        
        snapshot_cr = kb.snapshot_kb_state()
        latencies = []
        for flow_id, (_, post_nodes) in _routes_from_snapshot(snapshot_cr).items():
            if post_nodes:
                        latencies.append(engine.path_latency(flow_id, post_nodes))
        avg_letencies = sum(latencies) / len(latencies) if latencies else 0.0        

        n_ko = len(ko_flows)
        rows.append({
            "phase": "degrade", "scale": 1.0,
            "degrade_min": degrade[0], "degrade_max": degrade[1],
            "topology": topo, "n": n, "flow_factor": ff, "seed": seed,
            "pct_mod": pct, "epoch": epoch, "num_flows": num_flows,
            "init_routed": num_flows, "init_ok": True,
            "frac_degraded": frac, "avg_bw": avg_bw,
            "N_KO": n_ko, "N_rerouted": len(new_valid) - len(ok_flows),
            "N_failed": len(failed), "N_no_path": no_path,
            "avg_letencies": avg_letencies,
            "P_KO": n_ko / num_flows if num_flows else 0.0, "error": "",
        })
    return rows


def _run_build(cfg):
    topo, n, ff, seed = cfg["topo"], cfg["n"], cfg["ff"], cfg["seed"]
    scale, phase = cfg["scale"], cfg["phase"]
    num_flows = int(ff * n)
    _apply_scale(topo, scale)

    fd, tf = tempfile.mkstemp(suffix=".json"); os.close(fd)
    rows = []
    network = None
    try:
        try:
            network, kb, engine, ctrl = _build_system(topo, n, num_flows, seed, tf)
            init_routed, init_ok = num_flows, True
        except epoch_benchmark_exception as e:
            m = re.search(r"\d+", str(e))
            init_routed, init_ok = (int(m.group()) if m else -1), False

        if phase == "floor":
            rr = ([(u, v) for u, v in network.graph.edges() if not (u.startswith("h") or v.startswith("h"))] if network is not None else [])
            rows.append({
                "phase": "floor", "scale": scale,
                "topology": topo, "n": n, "flow_factor": ff, "seed": seed,
                "num_flows": num_flows, "init_routed": init_routed, "init_ok": init_ok,
                "avg_bw": _mean_rr_bw(network, rr) if rr else None, "error": "",
            })
            return rows

        if not init_ok:
            rows.append({"phase": "degrade", "scale": scale, "topology": topo, "n": n,
                         "flow_factor": ff, "seed": seed, "num_flows": num_flows,
                         "init_ok": False, "error": "INIT_FAIL"})
            return rows
        rr_edges = [(u, v) for u, v in network.graph.edges() if not (u.startswith("h") or v.startswith("h"))]
        post_init = kb.snapshot_kb_state()
        for degrade in DEGRADE_FACTORS:
            eb.DEGRADE_FACTOR = degrade
            for pct in PCT_MODS:
                rows += run_seq(network, kb, engine, rr_edges, post_init,degrade, pct, seed, num_flows, topo, n, ff)
    finally:
        os.path.exists(tf) and os.unlink(tf)
    return rows


run_build = ray.remote(num_cpus=1, max_calls=1)(_run_build)


def main():
    import pandas as pd
    os.environ["RAY_local_fs_capacity_threshold"] = "0.99"
    ray.init(num_cpus=NUM_WORKERS, runtime_env={"env_vars": {"PYTHONPATH": f"{BENCHMARK_DIR}{os.pathsep}{REPO_ROOT}"}})

    floor_cfgs = [{"phase": "floor", "topo": t, "n": n, "ff": FLOOR_FF, "seed": s, "scale": sc} for t in TOPOLOGIES for n in FLOOR_SIZES for s in SEEDS for sc in SCALES]
    degrade_cfgs = [{"phase": "degrade", "topo": t, "n": n, "ff": ff, "seed": s, "scale": 1.0} for t in TOPOLOGIES for n in SIZES for ff in FLOW_FACTORS for s in SEEDS]
    configs = floor_cfgs + degrade_cfgs
    csv_path = BENCHMARK_DIR / RESULTS_CSV
    print(f"tune_parameters | floor={len(floor_cfgs)} + degrade={len(degrade_cfgs)} build | "
          f"{NUM_WORKERS} worker | degrade={DEGRADE_FACTORS} scale={SCALES} -> {csv_path}")

    it       = iter(configs)
    active   = [run_build.remote(c) for c in itertools.islice(it, NUM_WORKERS)]
    all_rows = []
    done     = 0
    while active:
        ready, active = ray.wait(active, num_returns=1)
        all_rows.extend(ray.get(ready[0]))
        done += 1
        print(f"  [{done}/{len(configs)}] build completata ({len(all_rows)} righe)")
        pd.DataFrame(all_rows).to_csv(csv_path, index=False)
        nxt = next(it, None)
        if nxt is not None:
            active.append(run_build.remote(nxt))

    pd.DataFrame(all_rows).to_csv(csv_path, index=False)
    print(f"CSV -> {csv_path}")
    ray.shutdown()


if __name__ == "__main__":
    main()
