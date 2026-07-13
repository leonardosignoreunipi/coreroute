"""
Epoch-based drift benchmark: Continuous Reasoning vs Full Recompute.

For each (topology, n, flow_factor, seed) an INIT is done once. Then, for each
pct_mod, the network is perturbed over EPOCHS epochs with CUMULATIVE drift: every
epoch degrades a fresh random pct_mod% of router-router links by multiplying their
CURRENT bandwidth, and the bandwidth is NOT restored between epochs, so damage
accumulates and the network progressively deteriorates.

The CR routing state persists epoch-to-epoch (true continuous reasoning over time):
continuous_reasoning() at epoch k builds on its own routing from epoch k-1. Full
Recompute is measured as a discarded "what-if" each epoch (snapshot after CR ->
time FULL -> restore to the post-CR snapshot), so the two strategies never
contaminate each other.

Between pct_mods the network is fully reset (bw -> nominal + routing -> post-init).
One CSV row per (topology, n, flow_factor, seed, pct_mod, epoch).

Uses Ray Core (@ray.remote) for parallelism.
"""

#GENERATO DA CLAUDE

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

SEEDS = [104729]# , 224737, 350377, 479909, 611953, 742073, 871871, 1003001, 1234567, 15485863
TOPOLOGIES     = ["er", "ba", "iaag"]
SIZES          = [250] # , 500, 750, 1000
FLOW_FACTORS   = [1.00] # 0.25, 0.50, 0.75, 
PCT_MODS       = [0.10, 0.20, 0.30, 0.50]
EPOCHS         = 10
DEGRADE_FACTOR = (0.7, 1.2)   # severe: bw *= U(0.1, 0.5) each time a link is hit


def _run_batch(config_base: dict) -> list:
    """Run all pct_mods (each for EPOCHS cumulative-drift epochs) of one
    (topology, n, flow_factor, seed) combination. INIT is done once; each pct_mod
    starts from the post-init state, then drifts over its epochs.

    `pct_mods` and `epochs` can be overridden via config_base (used for testing);
    they default to the module-level PCT_MODS / EPOCHS.
    """
    logging.basicConfig(level=logging.WARNING)

    # lazy imports: each Ray worker has its own Python state and Prolog runtime
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(BENCHMARK_DIR))
    from build_topology  import generate_sdn_topology
    from SDNcontroller   import SDNcontroller
    from ConfigLoader    import ConfigLoader
    from PhysicalNetwork import PhysicalNetwork as Net
    from RoutingEngine   import RoutingEngine as Engine
    from JanusKB         import JanusKB as PrologKB

    topology    = config_base["topology"]
    n           = config_base["n"]
    flow_factor = config_base["flow_factor"]
    seed        = config_base["seed"]
    num_flows   = int(flow_factor * n)
    pct_mods    = config_base.get("pct_mods", PCT_MODS)
    epochs      = config_base.get("epochs", EPOCHS)

    topo_file = None
    results   = []

    try:
        # ── generate topology ─────────────────────────────────────────────
        random.seed(seed)
        fd, topo_file = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        generate_sdn_topology(
            graph_type=topology, num_nodes=n,
            num_flows=num_flows, filename=topo_file, seed=seed,
        )

        cfg     = ConfigLoader(topo_file).load()
        network = Net(cfg)
        kb      = PrologKB(cfg, KB_FILE)
        engine  = Engine(network, kb, cfg)
        ctrl    = SDNcontroller(network, kb, cfg, engine)

        kb.clear_kb()
        kb.initialize_kb()

        num_nodes = len(network.graph.nodes)
        num_edges = len(network.graph.edges)

        # ── [INIT] once for the whole batch ───────────────────────────────
        ctrl.full_recompute()

        # router-router edges (label pairs), invariant for the whole batch
        rr_edges = [
            (u, v) for u, v in network.graph.edges()
            if not (u.startswith("h") or v.startswith("h"))
        ]

        # snapshot of the post-init state (routing + paths), restored before each pct_mod
        post_init_snapshot = kb.snapshot_kb_state()

        for pct_mod in pct_mods:
            # ── reset to a clean network before each pct_mod ──────────────
            # bw -> nominal (undo the previous pct_mod's accumulated drift) ...
            reset = []
            for (u, v) in rr_edges:
                data = network.graph[u][v]
                if data["bw"] != data["bw_nominal"]:
                    data["bw"] = data["bw_nominal"]
                    reset.append((u, v, data["bw_nominal"]))
            if reset:
                kb.update_links_bandwidth(reset)
            # ... and routing/paths -> post-init
            kb.restore_kb_state(post_init_snapshot)

            # reproducible epoch sequence for each (seed, pct_mod)
            random.seed(hash((seed, pct_mod)) % (2**32))

            for epoch in range(epochs):
                config = {**config_base, "pct_mod": pct_mod, "epoch": epoch}
                config.pop("pct_mods", None)
                config.pop("epochs", None)
                try:
                    # ── [PERTURB — cumulative drift] ──────────────────────
                    # degrade a fresh random pct_mod% subset of rr links by
                    # multiplying their CURRENT bw (damage stacks, coverage grows)
                    n_mod    = max(1, int(pct_mod * len(rr_edges)))
                    selected = random.sample(rr_edges, min(n_mod, len(rr_edges)))
                    degraded = []
                    for (u, v) in selected:
                        data = network.graph[u][v]
                        new_bw = data["bw"] * random.uniform(*DEGRADE_FACTOR)
                        if new_bw > data["bw_nominal"]: new_bw = data["bw_nominal"]
                        data["bw"] = new_bw
                        degraded.append((u, v, new_bw))
                    kb.update_links_bandwidth(degraded)

                    # fraction of rr links currently below nominal (drift progress)
                    frac_degraded = (
                        sum(1 for (u, v) in rr_edges
                            if network.graph[u][v]["bw"] < network.graph[u][v]["bw_nominal"])
                        / len(rr_edges)
                    ) if rr_edges else 0.0

                    # ── [CR] incremental; its result persists into next epoch ──
                    t0 = time.perf_counter()
                    _, n_ko, n_r = ctrl.continuous_reasoning()
                    t_cr = time.perf_counter() - t0

                    # freeze CR trajectory, time FULL as a throwaway, then restore
                    snapshot_cr = kb.snapshot_kb_state()
                    t0 = time.perf_counter()
                    _, n_full_ko, n_full_r = ctrl.full_recompute()
                    t_full = time.perf_counter() - t0
                    kb.restore_kb_state(snapshot_cr)

                    speedup = t_full / t_cr if t_cr > 0 else float("inf")

                    results.append({
                        **config,
                        "num_nodes":        num_nodes,
                        "num_edges":        num_edges,
                        "num_flows":        num_flows,
                        "T_CR":             t_cr,
                        "T_FULL":           t_full,
                        "N_KO_CR":          n_ko,
                        "N_R_CR":           n_r,
                        "N_KO_FULL":        n_full_ko,
                        "N_R_FULL":         n_full_r,
                        "P_KO":             n_ko / num_flows if num_flows > 0 else 0.0,
                        "P_R":              n_r  / num_flows if num_flows > 0 else 0.0,
                        "Speedup":          speedup,
                        "n_links_epoch":    len(selected),
                        "frac_rr_degraded": frac_degraded,
                        "ok":               True,
                        "error":            "",
                    })

                except Exception as e:
                    # drift state is now inconsistent; record and move to the next
                    # pct_mod, which resets cleanly
                    results.append({**config, "ok": False, "error": str(e)})
                    break

    except Exception as e:
        # error during init/snapshot: every (pct_mod, epoch) of the batch fails
        for pct_mod in pct_mods:
            for epoch in range(epochs):
                results.append({
                    "topology": topology, "n": n, "flow_factor": flow_factor,
                    "seed": seed, "pct_mod": pct_mod, "epoch": epoch,
                    "ok": False, "error": f"Init failed: {e}",
                })

    finally:
        if topo_file and os.path.exists(topo_file):
            os.unlink(topo_file)

    return results


run_trial_batch = ray.remote(num_cpus=1, max_calls=1)(_run_batch)


if __name__ == "__main__":
    os.environ["RAY_local_fs_capacity_threshold"] = "0.99"
    RESULTS_DIR.mkdir(exist_ok=True)
    NUM_WORKERS = 4

    OUTPUT_CSV = sys.argv[1] if len(sys.argv) > 1 else "benchmark_epoch_drift.csv"

    ray.init(num_cpus=NUM_WORKERS)

    # 480 batches: pct_mod and epoch are expanded inside each batch
    all_configs = [
        {"topology": t, "n": n, "flow_factor": ff, "seed": s}
        for t, n, ff, s in itertools.product(TOPOLOGIES, SIZES, FLOW_FACTORS, SEEDS)
    ]
    total_batches = len(all_configs)
    total_rows    = total_batches * len(PCT_MODS) * EPOCHS
    print(f"Launching {total_batches} batches → {total_rows} rows "
          f"({len(PCT_MODS)} pct × {EPOCHS} epochs each) | {NUM_WORKERS} parallel workers")

    # sliding window: keeps exactly NUM_WORKERS batches active
    config_iter = iter(all_configs)
    active      = []
    for cfg in itertools.islice(config_iter, NUM_WORKERS):
        active.append(run_trial_batch.remote(cfg))

    results      = []
    done_batches = 0
    csv_out      = RESULTS_DIR / OUTPUT_CSV

    while active:
        ready, active = ray.wait(active, num_returns=1)
        batch_results = ray.get(ready[0])
        done_batches += 1
        results.extend(batch_results)

        b0 = batch_results[0]
        n_ok = sum(1 for r in batch_results if r.get("ok"))
        print(f"  [batch {done_batches}/{total_batches}] "
              f"topo={b0['topology']} n={b0['n']} ff={b0['flow_factor']} seed={b0['seed']} "
              f"→ {n_ok}/{len(batch_results)} rows ok")

        # checkpoint: save the partial CSV after every batch
        pd.DataFrame(results).to_csv(csv_out, index=False)

        # submit the next batch as soon as a slot frees up
        next_cfg = next(config_iter, None)
        if next_cfg is not None:
            active.append(run_trial_batch.remote(next_cfg))

    print(f"   CSV → {csv_out}")
    ray.shutdown()