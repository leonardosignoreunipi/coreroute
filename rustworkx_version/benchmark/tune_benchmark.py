"""
Parallel benchmark runner: Continuous Reasoning vs Full Recompute.
Uses Ray Core (@ray.remote) for parallelism — avoids Ray Tune's
BasicVariantGenerator pickling bug on Python 3.14.

Total trials: 3 topologies × 4 sizes × 4 flow_factors × 4 pct_mod × 10 seeds = 1920
"""

import os
import sys
import time
import random
import tempfile
import itertools
import logging
from pathlib import Path

import ray
import pandas as pd

BENCHMARK_DIR = Path(__file__).parent
REPO_ROOT     = BENCHMARK_DIR.parent
KB_FILE       = str(REPO_ROOT / "routing_core.pl")
RESULTS_DIR   = BENCHMARK_DIR / "results"

SEEDS        = [104729]
TOPOLOGIES   = ["er", "ba", "iaag"]
SIZES        = [250, 500, 750, 1000]
FLOW_FACTORS = [0.25, 0.50, 0.75, 1.00]
PCT_MODS     = [0.01, 0.05, 0.10, 0.20]


@ray.remote(num_cpus=1, max_calls=1)
def run_trial(config: dict) -> dict:
    """Runs one experiment trial in an isolated Ray worker process."""
    logging.basicConfig(level=logging.WARNING)

    # lazy imports: each worker gets its own module state (and Prolog runtime)
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(BENCHMARK_DIR))
    from build_topology import generate_sdn_topology
    from SDNcontroller  import SDNcontroller
    from ConfigLoader   import ConfigLoader
    from PhysicalNetwork import PhysicalNetwork as Net
    from RoutingEngine  import RoutingEngine as Engine
    from JanusKB        import JanusKB as PrologKB

    topology    = config["topology"]
    n           = config["n"]
    flow_factor = config["flow_factor"]
    pct_mod     = config["pct_mod"]
    seed        = config["seed"]
    num_flows   = int(flow_factor * n)
    num_hosts   = max(2, n // 10)

    random.seed(seed)
    topo_file = None

    try:
        fd, topo_file = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        generate_sdn_topology(
            graph_type=topology, num_routers=n, num_hosts=num_hosts,
            num_flows=num_flows, filename=topo_file, seed=seed,
        )

        cfg     = ConfigLoader(topo_file).load()
        network = Net(cfg)
        kb      = PrologKB(cfg, KB_FILE)
        engine  = Engine(network, kb, cfg)
        ctrl    = SDNcontroller(network, kb, cfg, engine)

        kb.clear_kb()
        kb.initialize_kb()

        num_nodes = network.graph.num_nodes()
        num_edges = network.graph.num_edges()

        # [INIT] route all flows from scratch
        ctrl.continuos_reasoning()

        # [PERTURB] select pct_mod fraction of router-router links
        rr_indices = [
            idx for idx in network.graph.edge_indices()
            if not (network.inv_node_map[network.graph.get_edge_endpoints_by_index(idx)[0]].startswith("h") or
                    network.inv_node_map[network.graph.get_edge_endpoints_by_index(idx)[1]].startswith("h"))
        ]
        n_mod    = max(1, int(pct_mod * len(rr_indices)))
        selected = random.sample(rr_indices, min(n_mod, len(rr_indices)))
        degraded = []
        for idx in selected:
            ed     = network.graph.get_edge_data_by_index(idx)
            new_bw = ed["bw_nominal"] * random.uniform(0.5, 1.5)
            ed["bw"] = new_bw
            network.graph.update_edge_by_index(idx, ed)
            degraded.append((ed["u"], ed["v"], new_bw))
        kb.update_links_bandwidth(degraded)

        # [CR] continuous reasoning — only re-routes KO flows
        t0 = time.perf_counter()
        _, n_ko = ctrl.continuos_reasoning()
        t_cr = time.perf_counter() - t0

        # [FULL] full recompute — routes all flows from scratch on perturbed network
        t0 = time.perf_counter()
        _, n_full_ko = ctrl.full_recompute()
        t_full = time.perf_counter() - t0

        speedup = t_full / t_cr if t_cr > 0 else float("inf")

        return {
            **config,
            "num_nodes":   num_nodes,
            "num_edges":   num_edges,
            "num_flows":   num_flows,
            "T_CR":        t_cr,
            "T_FULL":      t_full,
            "N_KO":        n_ko,
            "N_R":         n_ko,
            "P_KO":        n_ko / num_flows if num_flows > 0 else 0.0,
            "P_R":         n_ko / num_flows if num_flows > 0 else 0.0,
            "Speedup":     speedup,
            "n_links_mod": len(selected),
            "ok":          True,
            "error":       "",
        }

    except Exception as e:
        return {**config, "ok": False, "error": str(e)}

    finally:
        if topo_file and os.path.exists(topo_file):
            os.unlink(topo_file)


if __name__ == "__main__":
    os.environ["RAY_local_fs_capacity_threshold"] = "0.99" #toglie il warning sullo spazio in /tmp/ray/seession
    RESULTS_DIR.mkdir(exist_ok=True)
    NUM_WORKERS = 4
    ray.init(num_cpus=NUM_WORKERS)

    all_configs = [
        {
            "topology": t, 
            "n": n, 
            "flow_factor": ff,  
            "pct_mod": pm, 
            "seed": s
        }
        for t, n, ff, pm, s in itertools.product(TOPOLOGIES, SIZES, FLOW_FACTORS, PCT_MODS, SEEDS)
    ]
    total = len(all_configs)
    print(f"Launching {total} trials with {NUM_WORKERS} parallel workers...")

    # sliding window: keep exactly NUM_WORKERS trials running at all times
    config_iter = iter(all_configs)
    active = []
    for cfg in itertools.islice(config_iter, NUM_WORKERS):
        active.append(run_trial.remote(cfg))

    results = []
    done = 0
    while active:
        ready, active = ray.wait(active, num_returns=1)
        result = ray.get(ready[0])
        results.append(result)
        done += 1
        status = "✓" if result.get("ok") else "✗"
        print(f"  [{done}/{total}] {status}  topology={result['topology']}  n={result['n']}"
              f"  ff={result['flow_factor']}  pct={result['pct_mod']}  seed={result['seed']}"
              + (f"  T_CR={result['T_CR']:.3f}s  Speedup={result['Speedup']:.1f}x" if result.get("ok") else f"  ERROR: {result.get('error')}"))
        # as soon as a slot frees up, submit the next config
        next_cfg = next(config_iter, None)
        if next_cfg is not None:
            active.append(run_trial.remote(next_cfg))

    df = pd.DataFrame(results)
    csv_out = RESULTS_DIR / "benchmark_cr.csv"
    df.to_csv(csv_out, index=False)

    ok_count = df["ok"].sum()
    print(f"\n✅  Done!  {ok_count}/{total} trials succeeded.")
    print(f"   CSV → {csv_out}")
    ray.shutdown()
