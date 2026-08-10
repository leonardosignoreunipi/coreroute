"""
Epoch-based drift benchmark: Continuous Reasoning (CR) vs Full Recompute (FULL).

Protocol
--------
For each (topology, n, flow_factor, seed) batch:
  1. Generate the topology, initialize the Prolog KB, route every flow once
     (INIT via full_recompute) and snapshot that post-init state.
  2. For each pct_mod: restore bandwidth to nominal and routing to post-init,
     then drift the network for EPOCHS epochs. Every epoch degrades a fresh
     random pct_mod share of router-router links by multiplying their CURRENT
     bandwidth (damage is cumulative: bandwidth is never restored between
     epochs, so the network progressively decays).
  3. Every epoch, time continuous_reasoning(); its result PERSISTS into the
     next epoch (that is the "continuous" in continuous reasoning). Then time
     full_recompute() as a discarded what-if: snapshot after CR, run FULL,
     read its outcome, restore the CR snapshot. The two strategies see the
     exact same perturbation sequence and never contaminate each other.

Both strategies are compared against the SAME pre-reconfiguration state of the
epoch, so per-epoch metrics (symmetric difference, flows changed, mean latency)
are directly comparable.

Reproducibility
---------------
Perturbations are drawn from a PRIVATE random.Random seeded with
hash((seed, pct_mod)): the perturbation sequence depends only on (seed,
pct_mod), never on how many random numbers the routing engine consumes.
(Numeric-tuple hashes are stable across processes; PYTHONHASHSEED only
affects str/bytes.)

Output
------
One CSV row per (topology, n, flow_factor, seed, pct_mod, epoch), with a FIXED
column schema: failed rows carry the same columns as successful ones (metric
fields left empty). The CSV is checkpointed after every completed batch.

Uses Ray Core (@ray.remote, max_calls=1) so each batch gets a fresh OS process
and therefore a fresh embedded Prolog runtime.
"""

import os
import sys
import time
import random
import subprocess
import tempfile
import itertools
import logging
from pathlib import Path

import ray
import pandas as pd


logger = logging.getLogger(__name__)

class epoch_benchmark_exception(Exception):
    """Custom exception for experiments"""
    pass

BENCHMARK_DIR = Path(__file__).parent
REPO_ROOT     = BENCHMARK_DIR.parent
KB_FILE       = str(REPO_ROOT / "routing_core.pl")
RESULTS_DIR   = BENCHMARK_DIR / "results"

SEEDS          = [913067, 224737, 611953, 742073, 871871, 350377, 479915, 1003001, 1234567, 15485863]
TOPOLOGIES     = ["er", "ba", "iaag"]
SIZES          = [250, 500, 750, 1000]
FLOW_FACTORS   = [0.25, 0.50, 0.75, 1.00]
PCT_MODS       = [0.10, 0.20, 0.30, 0.50]
EPOCHS         = 20
DEGRADE_FACTOR = (0.5, 1.5)
STRATEGY       = "biased_k_shortest_path_latency"

_ROW_DEFAULTS = {
    "num_nodes": None, "num_edges": None, "num_flows": None,
    "T_CR": None, "T_FULL": None,
    "T_generate_candidates_CR": None, "T_prolog_strategy_CR": None,
    "T_generate_candidates_FULL": None, "T_prolog_strategy_FULL": None,
    "N_KO_CR": None, "N_R_CR": None, "N_KO_FULL": None, "N_R_FULL": None,
    "P_KO": None, "P_R": None, "Speedup": None,
    "n_links_epoch": None, "frac_rr_degraded": None,
    "diff_simm_tot_CR": None, "flows_changed_CR": None, "avg_latency_CR": None,
    "diff_simm_tot_FULL": None, "flows_changed_FULL": None, "avg_latency_FULL": None,
    "no_path_count_CR": None, "no_path_count_FULL": None,
    "ok": False, "error": "",
}


def _make_row(base: dict, pct_mod: float, epoch: int, **values) -> dict:
    """Build one CSV row with the fixed schema; `values` override the defaults."""
    row = {**base, "pct_mod": pct_mod, "epoch": epoch, **_ROW_DEFAULTS}
    row.update(values)
    return row


def _timed(fn):
    """Run fn() and return (elapsed_seconds, result)."""
    t0 = time.perf_counter()
    result = fn()
    return time.perf_counter() - t0, result


def _active_routes(kb) -> dict:
    """Photo of the KB routing state: FlowId -> (PathId, Nodes)."""
    return {r["FlowId"]: (r["PathId"], r["Nodes"]) for r in kb.get_routings()}


def _routes_from_snapshot(snapshot: dict) -> dict:
    """Same photo as _active_routes, but derived from a snapshot_kb_state()
    dict — guarantees the metrics are computed on exactly the state that the
    snapshot will restore, with no extra KB query."""
    nodes_by_path = {p["PathId"]: p["Nodes"] for p in snapshot["paths"]}
    return {r["FlowId"]: (r["PathId"], nodes_by_path.get(r["PathId"], [])) for r in snapshot["routings"]}


def _compute_metrics(pre: dict, post: dict, engine) -> dict:
    """Compare routing state before/after one rerouting pass.

    pre/post: FlowId -> (PathId, Nodes).
    - diff_simm_tot: sum of diff_score (symmetric edge difference) over all flows
    - flows_changed: flows whose PathId changed (path interning makes this
      equivalent to comparing node lists)
    - avg_latency: mean path_latency over flows with a non-empty path after
    """
    diff_simm_tot = 0
    flows_changed = 0
    latencies = []
    for flow_id, (post_path_id, post_nodes) in post.items():
        pre_path_id, pre_nodes = pre.get(flow_id, (None, []))
        diff_simm_tot += engine.diff_score(pre_nodes, post_nodes)
        if pre_path_id != post_path_id:
            flows_changed += 1
        if post_nodes:
            latencies.append(engine.path_latency(post_nodes))
    return {
        "diff_simm_tot": diff_simm_tot,
        "flows_changed": flows_changed,
        "avg_latency": sum(latencies) / len(latencies) if latencies else 0.0,
    }


def _apply_bandwidth(network, kb, changes: list[tuple]) -> None:
    """Mutates link bandwidth: applies (u, v, new_bw)
    to the NetworkX graph and mirrors it into the Prolog KB, keeping the two
    routing stages (Python prefilter / Prolog authoritative check) in sync."""
    for (u, v, new_bw) in changes:
        network.graph[u][v]["bw"] = new_bw
    if changes:
        kb.update_links_bandwidth(changes)


def _reset_to_nominal(network, kb, rr_edges: list[tuple]) -> None:
    """Undo all accumulated drift: bandwidth of every rr link -> bw_nominal."""
    changes = [
        (u, v, network.graph[u][v]["bw_nominal"])
        for (u, v) in rr_edges
        if network.graph[u][v]["bw"] != network.graph[u][v]["bw_nominal"]
    ]
    _apply_bandwidth(network, kb, changes)


def _perturb_epoch(network, kb, rr_edges: list[tuple], pct_mod: float, rng: random.Random) -> int:
    """One epoch of cumulative drift: degrade a fresh random pct_mod share of
    rr links by multiplying their CURRENT bandwidth (clamped at nominal).
    Returns the number of links hit."""
    n_mod    = max(1, int(pct_mod * len(rr_edges)))
    selected = rng.sample(rr_edges, min(n_mod, len(rr_edges)))
    changes  = []
    for (u, v) in selected:
        data   = network.graph[u][v]
        new_bw = min(data["bw"] * rng.uniform(*DEGRADE_FACTOR), data["bw_nominal"])
        changes.append((u, v, new_bw))
    _apply_bandwidth(network, kb, changes)
    return len(selected)


def _frac_degraded(network, rr_edges: list[tuple]) -> float:
    """Fraction of rr links currently below nominal bandwidth (drift progress)."""
    if not rr_edges:
        return 0.0
    below = sum(1 for (u, v) in rr_edges
                if network.graph[u][v]["bw"] < network.graph[u][v]["bw_nominal"])
    return below / len(rr_edges)


def _run_epoch(network, kb, engine, ctrl, rr_edges, pct_mod, rng) -> dict:
    """One drift epoch: perturb, measure CR (persists into the next epoch).

    The FULL what-if is measured only when `measure_full` is True (last epoch
    of each pct sequence): its cost is state-independent (T_FULL constant
    within 1-2% across epochs, see probes), so one sample per sequence
    suffices. When skipped, no snapshot/restore is needed — there is nothing
    to undo — and the CR trajectory is bit-identical either way. All KB reads
    happen OUTSIDE the timed sections."""
    n_links = _perturb_epoch(network, kb, rr_edges, pct_mod, rng)
    frac    = _frac_degraded(network, rr_edges)
    pre     = _active_routes(kb)

    t_cr, (_, n_ko, n_r, no_path_count_cr) = _timed(ctrl.continuous_reasoning)
    # letti SUBITO: full_recompute piu' sotto chiama re_routing e sovrascrive gli stessi due attributi
    t_gen_cr, t_prolog_cr = engine.last_time_strategy, engine.last_time_prolog_strategy

    measures = {
        "T_CR": t_cr,
        "T_generate_candidates_CR": t_gen_cr, "T_prolog_strategy_CR": t_prolog_cr,
        "N_KO_CR": n_ko, "N_R_CR": n_r,
        "n_links_epoch": n_links,
        "frac_rr_degraded": frac,
        "no_path_count_CR": no_path_count_cr
    }

    
    snapshot_cr = kb.snapshot_kb_state()          # freezes the CR trajectory
    metrics_cr  = _compute_metrics(pre, _routes_from_snapshot(snapshot_cr), engine)

    # FULL: throwaway what-if, measured then discarded
    t_full, (_, n_full_ko, n_full_r, no_path_count_full) = _timed(ctrl.full_recompute)
    t_gen_full, t_prolog_full = engine.last_time_strategy, engine.last_time_prolog_strategy
    metrics_full = _compute_metrics(pre, _active_routes(kb), engine)
    kb.restore_kb_state(snapshot_cr)

    measures.update({
            "T_FULL": t_full,
            "T_generate_candidates_FULL": t_gen_full, "T_prolog_strategy_FULL": t_prolog_full,
            "N_KO_FULL": n_full_ko, "N_R_FULL": n_full_r,
            "Speedup": t_full / t_cr if t_cr > 0 else float("inf"),
            "diff_simm_tot_FULL": metrics_full["diff_simm_tot"],
            "flows_changed_FULL": metrics_full["flows_changed"],
            "avg_latency_FULL":   metrics_full["avg_latency"],
            "no_path_count_FULL": no_path_count_full
    })

    measures.update({
        "diff_simm_tot_CR": metrics_cr["diff_simm_tot"],
        "flows_changed_CR": metrics_cr["flows_changed"],
        "avg_latency_CR":   metrics_cr["avg_latency"],
    })
    return measures


def _build_system(topology: str, n: int, num_flows: int, seed: int, topo_file: str):
    """Generate the topology and build the full stack (network, kb, engine,
    ctrl), initialize the KB and run the INIT full_recompute."""
    # lazy imports: each Ray worker has its own Python state and Prolog runtime
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(BENCHMARK_DIR))
    from build_topology  import generate_sdn_topology
    from SDNcontroller   import SDNcontroller
    from ConfigLoader    import ConfigLoader
    from PhysicalNetwork import PhysicalNetwork as Net
    from RoutingEngine   import RoutingEngine as Engine
    from JanusKB         import JanusKB as PrologKB

    random.seed(seed)  # topology generation uses the global RNG
    generate_sdn_topology(graph_type=topology, num_nodes=n,
                          num_flows=num_flows, filename=topo_file, seed=seed)

    cfg     = ConfigLoader(topo_file).load()
    network = Net(cfg)
    kb      = PrologKB(cfg, KB_FILE)
    engine  = Engine(network, kb, cfg)
    ctrl    = SDNcontroller(network, kb, cfg, engine)

    kb.clear_kb()
    kb.initialize_kb()
    nvr, f_ko, f_rr, f_no_path = ctrl.full_recompute()  # INIT: route every flow once, strategia di default fissa

    if len(nvr) != num_flows:
        logger.error(f"[{topology} n={n} seed={seed}] INIT incompleta: " f"{len(nvr)}/{num_flows} instradati ({num_flows - len(nvr)} falliti, " f"{f_no_path} senza cammino con banda sufficiente)")
        raise epoch_benchmark_exception(f"INIT failed: not all flows routed topology {topology} n={n} seed={seed} routed={len(nvr)}/{num_flows} no_path={f_no_path}")

    engine.STRATEGY = getattr(engine, STRATEGY)  # da qui in poi la strategia sotto test guida CR e FULL
    return network, kb, engine, ctrl, len(nvr)


def _run_batch(config_base: dict) -> list:
    """Run all pct_mods (each for EPOCHS cumulative-drift epochs) of one
    (topology, n, flow_factor, seed) combination. INIT is done once; each
    pct_mod restarts from the post-init state, then drifts over its epochs.

    `pct_mods` and `epochs` can be overridden via config_base (used for
    manual testing); they default to the module-level PCT_MODS / EPOCHS.
    """
    logging.basicConfig(level=logging.WARNING)

    topology    = config_base["topology"]
    n           = config_base["n"]
    flow_factor = config_base["flow_factor"]
    seed        = config_base["seed"]
    num_flows   = int(flow_factor * n)
    pct_mods    = config_base.get("pct_mods", PCT_MODS)
    epochs      = config_base.get("epochs", EPOCHS)
    
    base = {"strategy": STRATEGY, "topology": topology, "n": n, "flow_factor": flow_factor, "seed": seed, "init_routed": None}
    results   = []
    topo_file = None

    try:
        fd, topo_file = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        network, kb, engine, ctrl, init_routed = _build_system(topology, n, num_flows, seed, topo_file)
        base["init_routed"]  = init_routed
        sizes = {"num_nodes": len(network.graph.nodes), "num_edges": len(network.graph.edges), "num_flows": num_flows}

        # router-router edges; string-prefix coupling to the h*/r* naming
        rr_edges = [(u, v) for u, v in network.graph.edges() if not (u.startswith("h") or v.startswith("h"))]

        post_init_snapshot = kb.snapshot_kb_state()

        for pct_mod in pct_mods:
            # clean restart: bandwidth -> nominal, routing -> post-init
            _reset_to_nominal(network, kb, rr_edges)
            kb.restore_kb_state(post_init_snapshot)

            # private RNG: the perturbation sequence is a function of
            # (seed, pct_mod) only, independent of the engine's RNG usage
            rng = random.Random(hash((seed, pct_mod)) % (2**32))

            for epoch in range(epochs):
                try:
                    measures = _run_epoch(network, kb, engine, ctrl, rr_edges, pct_mod, rng)
                    p_ko = measures["N_KO_CR"] / num_flows if num_flows > 0 else 0.0
                    p_r  = measures["N_R_CR"]  / num_flows if num_flows > 0 else 0.0
                    results.append(_make_row(base, pct_mod, epoch, **sizes, **measures, P_KO=p_ko, P_R=p_r, ok=True))
                except Exception as e:
                    results.append(_make_row(base, pct_mod, epoch, ok=False, error=str(e)))
                    break

    except Exception as e:
        for pct_mod in pct_mods:
            for epoch in range(epochs):
                            results.append(_make_row(base, pct_mod, epoch, num_flows=num_flows, ok=False, error=f"Init failed: {e}"))

    finally:
        if topo_file and os.path.exists(topo_file):
            os.unlink(topo_file)

    return results


run_trial_batch = ray.remote(num_cpus=1, max_calls=1)(_run_batch)


if __name__ == "__main__":
    os.environ["RAY_local_fs_capacity_threshold"] = "0.99"
    RESULTS_DIR.mkdir(exist_ok=True)
    NUM_WORKERS = 7

    OUTPUT_CSV = sys.argv[1] if len(sys.argv) > 1 else f"benchmark.csv"

    ray.init(num_cpus=NUM_WORKERS)

    all_configs = [
        {"topology": t, "n": n, "flow_factor": ff, "seed": s}
        for t, n, ff, s in itertools.product(TOPOLOGIES, SIZES, FLOW_FACTORS, SEEDS)
    ]
    total_batches = len(all_configs)
    total_rows    = total_batches * len(PCT_MODS) * EPOCHS
    print(f"Launching {total_batches} batches → {total_rows} rows "
          f"({len(PCT_MODS)} pct × {EPOCHS} epochs each) | {NUM_WORKERS} parallel workers")

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()
    print(f"commit={commit} | STRATEGY={STRATEGY} | SEEDS={SEEDS} | SIZES={SIZES} " f"| FLOW_FACTORS={FLOW_FACTORS} | PCT_MODS={PCT_MODS} | DEGRADE_FACTOR={DEGRADE_FACTOR}")
    # sliding window: keeps exactly NUM_WORKERS batches active
    config_iter = iter(all_configs)
    active      = [run_trial_batch.remote(cfg)
                   for cfg in itertools.islice(config_iter, NUM_WORKERS)]

    results      = []
    done_batches = 0
    csv_out      = RESULTS_DIR / OUTPUT_CSV

    while active:
        ready, active = ray.wait(active, num_returns=1)
        batch_results = ray.get(ready[0])
        done_batches += 1
        results.extend(batch_results)

        b0   = batch_results[0]
        n_ok = sum(1 for r in batch_results if r.get("ok"))
        print(f"  [batch {done_batches}/{total_batches}] "
              f"topo={b0['topology']} n={b0['n']} ff={b0['flow_factor']} seed={b0['seed']} "
              f"→ {n_ok}/{len(batch_results)} rows ok")

        # checkpoint: rewrite the partial CSV after every completed batch
        pd.DataFrame(results).to_csv(csv_out, index=False)

        next_cfg = next(config_iter, None)
        if next_cfg is not None:
            active.append(run_trial_batch.remote(next_cfg))

    print(f"   CSV → {csv_out}")
    ray.shutdown()