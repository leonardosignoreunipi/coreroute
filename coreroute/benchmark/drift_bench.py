import os
import sys
import tempfile
import random
import logging
from pathlib import Path

import ray
from ray import tune
import pandas as pd

from epoch_benchmark import _ROW_DEFAULTS, _make_row, _reset_to_nominal, _build_system, _run_epoch

BENCHMARK_DIR = Path(__file__).parent
RESULTS_DIR   = BENCHMARK_DIR / "results"
PCT_MODS       = [0.10, 0.20, 0.30, 0.50]
EPOCHS         = 20
STRATEGY       = "biased_k_shortest_path_latency"
MODES          = ["CR", "FULL"] #Continuous Reasoning, From-scratch

_ROW_COLUMNS = ["mode", "strategy", "topology", "n", "flow_factor", "seed", "init_routed", "pct_mod", "epoch", *_ROW_DEFAULTS]


def _report_dead_epochs(base: dict, pct_mod: float, epochs: int, from_epoch: int, error: str, **extra) -> None:
    for epoch in range(from_epoch, epochs):
        tune.report(_make_row(base, pct_mod, epoch, ok=False, error=error, **extra))

def get_param_space ():
    return {
            "topology":    tune.grid_search(["er", "ba", "iaag"]),
            "n":           tune.grid_search([250, 500, 750, 1000]),
            "flow_factor": tune.grid_search([0.25, 0.50, 0.75, 1.00]),
            "seed":        tune.grid_search([224737, 742073, 871871, 350377, 1003001, 1234567, 15485863, 990635, 782715, 510655]),
            "mode":        tune.grid_search(MODES),
        }

def _run_batch(config: dict) -> None:
    logging.basicConfig(level=logging.WARNING)

    topology    = config["topology"]
    n           = config["n"]
    flow_factor = config["flow_factor"]
    seed        = config["seed"]
    mode        = config.get("mode", MODES[0])
    num_flows   = int(flow_factor * n)
    pct_mods    = config.get("pct_mods", PCT_MODS)
    epochs      = config.get("epochs", EPOCHS)

    base = {"mode": mode, "strategy": STRATEGY, "topology": topology, "n": n, "flow_factor": flow_factor, "seed": seed, "init_routed": None}
    topo_file = None

    try:
        try:
            fd, topo_file = tempfile.mkstemp(suffix=".json")
            os.close(fd)
            network, kb, engine, ctrl, init_routed = _build_system(topology, n, num_flows, seed, topo_file)
            base["init_routed"] = init_routed
            sizes = {"num_nodes": len(network.graph.nodes), "num_edges": len(network.graph.edges), "num_flows": num_flows}
            reasoning_fn = ctrl.continuous_reasoning if mode == "CR" else ctrl.full_recompute
            rr_edges = [(u, v) for u, v in network.graph.edges() if not (u.startswith("h") or v.startswith("h"))]
            init_config = kb.snapshot_kb_state()
        except Exception as e:
            for pct_mod in pct_mods:
                _report_dead_epochs(base, pct_mod, epochs, 0, f"Init failed: {e}", num_flows=num_flows)
            return

        for pct_mod in pct_mods:
            try:
                _reset_to_nominal(network, kb, rr_edges)
                kb.restore_kb_state(init_config)
            except Exception as e:
                _report_dead_epochs(base, pct_mod, epochs, 0, f"pct_mod setup failed: {e}", **sizes)
                continue
            
            rng = random.Random(hash((seed, pct_mod)) % (2**32))

            for epoch in range(epochs):
                try:
                    measures = _run_epoch(network, kb, engine, ctrl, rr_edges, pct_mod, rng, reasoning_fn)
                    p_ko = measures["N_KO"] / num_flows if num_flows > 0 else 0.0
                    p_r  = measures["N_R"]  / num_flows if num_flows > 0 else 0.0
                    tune.report(_make_row(base, pct_mod, epoch, **sizes, **measures, P_KO=p_ko, P_R=p_r, ok=True))
                except Exception as e:
                    _report_dead_epochs(base, pct_mod, epochs, epoch, str(e), **sizes)
                    break
    finally:
        if topo_file and os.path.exists(topo_file):
            os.unlink(topo_file)


if __name__ == "__main__":
    os.environ["RAY_local_fs_capacity_threshold"] = "0.99"
    RESULTS_DIR.mkdir(exist_ok=True)

    OUTPUT_CSV = sys.argv[1] if len(sys.argv) > 1 else "exp2.csv"
    csv_out = RESULTS_DIR / OUTPUT_CSV

    ray.init()  # run from coreroute/benchmark/, like epoch_benchmark.py and heuristic_benchmark.py
    print(f"CPUs available: {int(ray.available_resources().get('CPU', 1))}")

    run_config = tune.RunConfig(name=csv_out.stem, storage_path=str(RESULTS_DIR / "ray_results"))

    tuner = tune.Tuner(
        tune.with_resources(_run_batch, {"cpu": 1}),
        param_space= get_param_space(),
        run_config= run_config,
    )
    
    results = tuner.fit()

    dfs = [r.metrics_dataframe[_ROW_COLUMNS] for r in results if r.metrics_dataframe is not None]
    df  = pd.concat(dfs, ignore_index=True)
    df.to_csv(csv_out, index=False)

    print(f"   CSV → {csv_out} ({len(df)} rows, {len(results)} batches, {results.num_errors} errored)")
    ray.shutdown()
