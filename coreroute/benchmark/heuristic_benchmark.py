import json
import os
import sys
import time
import random
import subprocess
import tempfile
import itertools
import logging
from pathlib import Path
from epoch_benchmark import (BENCHMARK_DIR, REPO_ROOT, KB_FILE, RESULTS_DIR, TOPOLOGIES, _timed, _reset_to_nominal, _apply_bandwidth, _active_routes, _compute_metrics)
import ray
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
logger = logging.getLogger(__name__)

SEEDS = [104730, 224741, 350377, 479915, 611953, 742073, 871871, 1003001, 1234567, 15485863]
SIZES          = [20, 25, 30, 35, 40]
NUM_FLOWS_LIST = [3, 4, 5, 6]
PCT_MODS       = [0.25, 0.35, 0.45] #se vado oltre questo pctmod si alzano troppo i no_path_count se non garantisco un alternativa l'esperimento perde di senso
DEGRADE_FACTOR = (0.05, 0.3)
EPOCHS         = 10
STRATEGIES     = ["latency_biased_paths", "biased_k_shortest_path_latency", "biased_k_shortest_path", "exhaustive_optimal"]
INIT_STRATEGY  = "biased_k_shortest_path_latency"
PERTURBATION   = "classic"  # solo per il log auto-descrittivo -- tenere allineato a _run_epoch
#scaling factors for bandwidths demand
RR_LINK_BW_RANGE = (15.0, 35.0)
IAAG_BW_SCALE = 0.2


class heuristic_benchmark_exception(Exception):
    """Custom Exception for heuristic_benchmark.py"""
    pass


def _rescale_router_bandwidth(topo_file: str, topology: str) -> None:
    """
    Set router-router link capacity for this experiment's contention regime.

    ER/BA get a fixed range (RR_LINK_BW_RANGE), same for every link. IAAG
    gets IAAG_BW_SCALE applied to each link's own original capacity, so its
    tier hierarchy survives instead of flattening to one range.
    """
    with open(topo_file) as f:
        topo = json.load(f)
    for link in topo["links"]:
        if link["src"].startswith("h") or link["dst"].startswith("h"):
            continue
        if topology == "iaag":
            link["bw"] *= IAAG_BW_SCALE
            link["bw_nominal"] *= IAAG_BW_SCALE
        else:
            bw = random.uniform(*RR_LINK_BW_RANGE)
            link["bw"] = bw
            link["bw_nominal"] = bw
    with open(topo_file, "w") as f:
        json.dump(topo, f)


def _build_system(topology: str, n: int, num_flows: int, seed: int, topo_file: str, strategy: str):
    """
    Build a fresh network/KB/engine/controller for one (topology, n, seed)
    cell and route every flow once via INIT_STRATEGY, then switch the
    engine to `strategy` for the CR calls that follow.

    Raises heuristic_benchmark_exception if `strategy` is unknown or if
    INIT does not route every flow.

    Returns:
        (network, kb, engine, ctrl): the built collaborators
        and the number of flows routed at INIT.
    """
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(BENCHMARK_DIR))
    from build_topology  import generate_sdn_topology
    from SDNcontroller   import SDNcontroller
    from ConfigLoader    import ConfigLoader
    from PhysicalNetwork import PhysicalNetwork as Net
    from RoutingEngine   import RoutingEngine as Engine
    from JanusKB         import JanusKB as PrologKB

    if strategy not in STRATEGIES:
        raise heuristic_benchmark_exception(f"Unknown strategy {strategy}")

    random.seed(seed)  # topology generation uses the global RNG
    generate_sdn_topology(graph_type=topology, num_nodes=n, num_flows=num_flows, filename=topo_file, seed=seed)
    _rescale_router_bandwidth(topo_file, topology)

    cfg     = ConfigLoader(topo_file).load()
    network = Net(cfg)
    kb      = PrologKB(cfg, KB_FILE)
    engine  = Engine(network, kb, cfg)
    ctrl    = SDNcontroller(network, kb, cfg, engine)

    kb.clear_kb()
    kb.initialize_kb()

    # INIT with the fixed strategy/repair
    engine.STRATEGY = getattr(engine, INIT_STRATEGY)
    engine.prolog_strategy = engine.resolve_repair
    t_init, (nvr, f_ko, f_rr, f_no_path) = _timed(ctrl.full_recompute)
    
    if f_rr < num_flows:
        logger.error(f"[{strategy} {topology} n={n} seed={seed}] INIT failed: only {f_rr}/{num_flows} flows routed")
        raise heuristic_benchmark_exception(f"The experiment starts with {f_rr} routing\nabort experiment")
    
    logger.info(f"[{strategy} {topology} n={n} seed={seed}] INIT ({INIT_STRATEGY}) "f"in {t_init:.2f}s | routed {len(nvr)}/{num_flows}")

    # from here on the strategy under test drives every CR and FULL
    if strategy == "exhaustive_optimal":
        engine.STRATEGY = engine.all_simple_candidates
        engine.prolog_strategy = engine.resolve_exhaustive_routing
    else:
        engine.STRATEGY = getattr(engine, strategy)
        engine.prolog_strategy = engine.resolve_repair

    
    return network, kb, engine, ctrl


def _perturb_epoch(network, kb, engine, pct_mod: float, rng: random.Random) -> int:
    """
    Break one router-router edge on a pct_mod share of routed flows' own
    paths, forcing each below its required bandwidth.

    Targeted rather than random: only the chosen flows' own edges are cut,
    so other flows' alternatives stay intact. `routed` is sorted by flow_id
    because KB order tracks Prolog retract/reassert history, not flow
    identity, which would otherwise make rng.sample non-reproducible.

    Returns:
        Number of flows actually hit (a target is skipped if its path has
        no router-router edge).
    """
    
    routed = sorted(((fid, nodes) for fid, (_, nodes) in _active_routes(kb).items() if nodes), key=lambda x: x[0])
    targets = rng.sample(routed, min(max(1, int(pct_mod * len(routed))), len(routed)))

    changes = []
    for flow_id, nodes in targets:
        rr = [(u, v) for u, v in zip(nodes[:-1], nodes[1:]) if not (u.startswith("h") or v.startswith("h"))]
        if not rr:
            logger.warning(f"[{engine.STRATEGY.__name__}] flow {flow_id} has no router-router edges to break, skipping")
            continue
        u, v = rng.choice(rr)
        changes.append((u, v, 0.0))

    _apply_bandwidth(network, kb, changes)
    return len(changes)

def _classic_perturbation (network, kb, engine, pct_mod: float, rng: random.Random) -> int:
    """
    Break one router-router edge on a pct_mod share of all edges, forcing each below its required bandwidth.

    Returns:
        Number of edges actually hit (a target is skipped if its path has
        no router-router edge).
    """
    rr_edges = [(u, v) for u, v in network.graph.edges() if not (u.startswith("h") or v.startswith("h"))]
    
    targets = rng.sample(rr_edges, min(max(1, int(pct_mod * len(rr_edges))), len(rr_edges)))

    changes = []
    for u, v in targets:
        old_bw = network.graph[u][v]["bw"]
        new_bw = old_bw * rng.uniform(*DEGRADE_FACTOR)
        if new_bw > network.graph[u][v]["bw_nominal"]:
            new_bw = network.graph[u][v]["bw_nominal"]
        changes.append((u, v, new_bw))

    _apply_bandwidth(network, kb, changes)
    return len(changes)

def _run_epoch(network, kb, engine, ctrl, rr_edges, pct_mod, rng) -> dict:
    """
    Run one perturbation-and-measure cycle: reset bandwidth to nominal,
    apply this epoch's classic perturbation (a random pct_mod share of all
    router-router links degraded, independent of who is routed where), then
    measure continuous reasoning.

    Bandwidth resets every epoch so damage never accumulates; routing
    itself persists, which is the point of "continuous" reasoning. Only CR
    is measured -- this experiment compares candidate-search strategies
    against exhaustive_optimal, not CR against FULL.

    Returns:
        Dict of this epoch's CR metrics (timing, KO/rerouted counts,
        reconfiguration cost, latency).
    """
    _reset_to_nominal(network, kb, rr_edges)
    n_links = _classic_perturbation(network, kb, engine, pct_mod, rng)
    pre     = _active_routes(kb)

    t_cr, (_, n_ko, n_r, no_path_count_cr) = _timed(ctrl.continuous_reasoning)
    metrics_cr = _compute_metrics(pre, _active_routes(kb), engine)

    return {
        "T_CR": t_cr,
        "T_generate_candidates": engine.last_time_strategy,   # Stage 1 (NetworkX)
        "T_prolog_strategy": engine.last_time_prolog_strategy,
        "N_KO": n_ko, 
        "N_RR": n_r,
        "n_links_fired": n_links,
        "no_path_count": no_path_count_cr,
        "diff_simm_tot": metrics_cr["diff_simm_tot"],
        "flows_changed": metrics_cr["flows_changed"],
        "avg_latency":   metrics_cr["avg_latency"],
    }


_ROW_FIELDS = [
    "strategy", "topology", "n", "seed", "init_routed",
    "pct_mod", "epoch", "num_edges", "num_flows",
    "T_CR", "T_generate_candidates", "T_prolog_strategy", "N_KO", "N_RR", "n_links_fired", "no_path_count",
    "diff_simm_tot", "flows_changed", "avg_latency", "P_KO", "P_R",
    "ok", "error",
]


def _make_row(base: dict, pct_mod: float, epoch: int, **values) -> dict:
    """Build one CSV row for this experiment's own schema; `values` fills in
    whatever this call computed on top of `base`."""
    row = dict.fromkeys(_ROW_FIELDS)
    row.update(base)
    row["pct_mod"], row["epoch"], row["ok"], row["error"] = pct_mod, epoch, False, ""
    row.update(values)
    return row


def _run_batch(config_base: dict) -> list:
    """
    Run one full (topology, n, num_flows, seed, strategy) cell: build the
    system, then for each pct_mod replay `epochs` perturb-and-measure
    cycles from the same post-INIT snapshot.

    Args:
        config_base: strategy/topology/n/num_flows/seed, plus optional
            pct_mods/epochs overrides.

    Returns:
        List of per-epoch row dicts (see _make_row), `ok=False` rows on
        failure.
    """
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "WARNING").upper(), format="%(asctime)s %(levelname)s %(message)s", force=True)

    # lazy import (runs in the Ray worker, not in the driver): the search budget
    # is read from where it is enforced, so the CSV cannot disagree with the code
    sys.path.insert(0, str(REPO_ROOT))

    topology    = config_base["topology"]
    n           = config_base["n"]
    num_flows   = config_base["num_flows"]
    seed        = config_base["seed"]
    strategy    = config_base.get("strategy", STRATEGIES[0])
    epochs      = config_base.get("epochs", EPOCHS)

    base = {"strategy": strategy, "topology": topology, "n": n, "seed": seed, "init_routed": None}
    results   = []
    topo_file = None

    try:
        fd, topo_file = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        network, kb, engine, ctrl = _build_system(topology, n, num_flows, seed, topo_file, strategy)

        num_edges = len(network.graph.edges)
        sizes = {"num_edges": num_edges, "num_flows": num_flows}

        # router-router edges; string-prefix coupling to the h*/r* naming
        rr_edges = [(u, v) for u, v in network.graph.edges() if not (u.startswith("h") or v.startswith("h"))]

        post_init_snapshot = kb.snapshot_kb_state()

        for pct_mod in PCT_MODS:
            # clean restart: bandwidth -> nominal, routing -> post-init
            _reset_to_nominal(network, kb, rr_edges)
            kb.restore_kb_state(post_init_snapshot)

            # private RNG: the perturbation sequence is a function of
            # (seed, pct_mod) only, independent of the engine's RNG usage
            rng = random.Random(hash((seed, pct_mod)) % (2**32))

            for epoch in range(epochs):
                try:
                    measures = _run_epoch(network, kb, engine, ctrl, rr_edges, pct_mod, rng)
                    p_ko = measures["N_KO"] / num_flows if num_flows > 0 else 0.0
                    p_r  = measures["N_RR"]  / num_flows if num_flows > 0 else 0.0
                    results.append(_make_row(base, pct_mod, epoch, **sizes, **measures, P_KO=p_ko, P_R=p_r, ok=True))
                except Exception as e:
                    results.append(_make_row(base, pct_mod, epoch, **sizes, ok=False, error=str(e)))
                    logger.warning(f"[{strategy} {topology} n={n} seed={seed}] "f"pct={pct_mod} epoch {epoch + 1} failed: {e}")
                    break
                
    except Exception as e:
        logger.warning(f"[{strategy} {topology} n={n} seed={seed}] batch failed: {e}")
        for pct_mod in PCT_MODS:
            for epoch in range(epochs):
                results.append(_make_row(base, pct_mod, epoch, num_flows=num_flows, ok=False, error=f"Init failed: {e}"))

    finally:
        if topo_file and os.path.exists(topo_file):
            os.unlink(topo_file)

    return results


def _dead_batch_rows(cfg: dict, error: str) -> list:
    """
    Full-schema rows for a batch that returned nothing (worker killed, or
    cancelled on the wall-clock budget).

    Returns:
        One `ok=False` row per (pct_mod, epoch) -- without them the batch
        would be indistinguishable from one never launched.
    """
    base = {"strategy": cfg["strategy"], "topology": cfg["topology"], "n": cfg["n"], "seed": cfg["seed"], "init_routed": None}
    return [_make_row(base, pct_mod, epoch, num_flows=cfg["num_flows"], ok=False, error=error) for pct_mod in PCT_MODS for epoch in range(EPOCHS)]


run_trial_batch = ray.remote(num_cpus=1, max_calls=1)(_run_batch)


def main():
    """
    Ray driver: sweep every (strategy, topology, n, num_flows, seed) cell
    through run_trial_batch, with a sliding window of NUM_WORKERS batches
    in flight and a wall-clock timeout per batch, and write the results
    to a CSV.
    """
    os.environ["RAY_local_fs_capacity_threshold"] = "0.99"
    RESULTS_DIR.mkdir(exist_ok=True)
    NUM_WORKERS   = int(os.environ.get("NUM_WORKERS", 7))
    BATCH_TIMEOUT = int(os.environ.get("BATCH_TIMEOUT", 3600))  
    WAIT_POLL = 30  # seconds between checks for timed-out batches

    OUTPUT_CSV = sys.argv[1] if len(sys.argv) > 1 else "heuristic_benchmark.csv"
    csv_out = RESULTS_DIR / OUTPUT_CSV

    ray.init(num_cpus=NUM_WORKERS)

    all_configs = [
        {"strategy": strat, "topology": t, "n": n, "num_flows": nf, "seed": s}
        for n, nf, t, s, strat in itertools.product(SIZES, NUM_FLOWS_LIST, TOPOLOGIES, SEEDS, STRATEGIES)
    ]
    results = []

    total_batches = len(all_configs)
    total_rows    = total_batches * len(PCT_MODS) * EPOCHS
    print(f"Launching {total_batches} batches → {total_rows} rows "
          f"({len(PCT_MODS)} pct × {EPOCHS} epochs each) | {NUM_WORKERS} parallel workers | batch timeout {BATCH_TIMEOUT}s")

    # self-describing log
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                             capture_output=True, text=True).stdout.strip()
    print(f"commit={commit} | STRATEGIES={STRATEGIES} | PERTURBATION={PERTURBATION} "
          f"| PCT_MODS={PCT_MODS} | DEGRADE_FACTOR={DEGRADE_FACTOR} "
          f"| RR_LINK_BW_RANGE={RR_LINK_BW_RANGE} | IAAG_BW_SCALE={IAAG_BW_SCALE} "
          f"| SIZES={SIZES} | NUM_FLOWS_LIST={NUM_FLOWS_LIST}")

    # sliding window: keeps exactly NUM_WORKERS batches active.
    # ObjectRef -> (config, launch time), the latter only for the elapsed-time print.
    config_iter = iter(all_configs)
    active: dict = {}

    def _launch_next() -> None:
        """Pull the next config and launch it, if any remain."""
        cfg = next(config_iter, None)
        if cfg is not None:
            active[run_trial_batch.remote(cfg)] = (cfg, time.monotonic())

    def _checkpoint() -> None:
        """Write the CSV atomically: a kill during the write leaves either the
        previous file or the new one, never a truncated one. Plain to_csv on
        the target would corrupt hours of results if interrupted mid-write."""
        tmp = csv_out.with_suffix(".csv.tmp")
        pd.DataFrame(results).to_csv(tmp, index=False)
        os.replace(tmp, csv_out)

    for _ in range(NUM_WORKERS):
        _launch_next()

    done_batches = 0
    timed_out_batches = 0

    try:
        while active:
            # Poll every WAIT_POLL seconds instead of blocking indefinitely,
            # so a batch stuck in all_simple_candidates' unbounded path
            # enumeration gets aged out instead of stalling the whole sweep.
            ready, _ = ray.wait(list(active), num_returns=1, timeout=WAIT_POLL)
            now = time.monotonic()

            for ref in ready:
                cfg, t0 = active.pop(ref)
                try:
                    batch_results = ray.get(ref)
                except Exception as e:
                    batch_results = _dead_batch_rows(cfg, f"worker died: {e}")
                    print(f"  [WORKER DIED] strat={cfg['strategy']} topo={cfg['topology']} " f"n={cfg['n']} seed={cfg['seed']}: {e}", flush=True)

                done_batches += 1
                results.extend(batch_results)

                b0   = batch_results[0]
                n_ok = sum(1 for r in batch_results if r.get("ok"))
                print(f"  [batch {done_batches}/{total_batches}] "
                      f"strat={b0['strategy']} topo={b0['topology']} n={b0['n']} "
                      f"nf={b0['num_flows']} seed={b0['seed']} "
                      f"→ {n_ok}/{len(batch_results)} rows ok "
                      f"[{now - t0:.0f}s]", flush=True)
                _launch_next()

            # age out whatever blew past the wall-clock budget -- safe to
            # force-cancel: workers are max_calls=1, so a cancelled worker
            # is disposable, no shared state to corrupt
            timed_out = [ref for ref, (_, t0) in active.items() if now - t0 > BATCH_TIMEOUT]
            for ref in timed_out:
                cfg, t0 = active.pop(ref)
                ray.cancel(ref, force=True)
                results.extend(_dead_batch_rows(cfg, f"batch exceeded BATCH_TIMEOUT={BATCH_TIMEOUT}s"))
                timed_out_batches += 1
                done_batches += 1
                print(f"  [TIMEOUT] strat={cfg['strategy']} topo={cfg['topology']} "
                      f"n={cfg['n']} nf={cfg['num_flows']} seed={cfg['seed']} "
                      f"after {now - t0:.0f}s -- cancelled", flush=True)
                _launch_next()

            if ready or timed_out:
                _checkpoint()

    except KeyboardInterrupt:
        # stopping by hand is the expected way to end an overnight run: the
        # in-flight batches are discarded, everything already collected is kept
        print(f"\nInterrupted by hand after {done_batches} batches "
              f"({len(active)} in flight discarded) — CSV holds every completed batch",
              flush=True)

    finally:
        _checkpoint()
        print(f"   CSV → {csv_out} ({len(results)} rows, {done_batches} batches done, "
              f"{timed_out_batches} timed out)")
        ray.shutdown()


if __name__ == "__main__":
    main()
