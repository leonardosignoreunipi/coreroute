import os
import sys
import time
import random
import tempfile
import itertools
import logging
from pathlib import Path
from epoch_benchmark import (BENCHMARK_DIR, REPO_ROOT, KB_FILE, RESULTS_DIR, TOPOLOGIES, INIT_TOLERANCE, _make_row, _timed, _reset_to_nominal, _run_epoch)
import ray
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
logger = logging.getLogger(__name__)

SEEDS = [104730, 224737, 350377, 479915, 611953, 742073, 871871, 1003001, 1234567, 15485863]
SIZES        = [20, 30, 40, 50, 60, 70, 80, 90, 100]
FLOW_FACTORS = [1.00]
PCT_MODS     = [0.10, 0.30, 0.50]
EPOCHS       = 1
STRATEGIES   = ["exhaustive_paths", "latency_biased_paths","biased_k_shortest_path_latency", "biased_k_shortest_path"]
INIT_STRATEGY = "biased_k_shortest_path_latency" #the strategy for init route flows equal to different strategies
EXHAUSTIVE_MAX_NODES = 50 #
class heuristic_benchmark_exception(Exception):
    """Custom Exception for heuristic_benchmark.py"""
    pass

def _build_system(topology: str, n: int, num_flows: int, seed: int, topo_file: str, strategy: str):
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

    cfg     = ConfigLoader(topo_file).load()
    network = Net(cfg)
    kb      = PrologKB(cfg, KB_FILE)
    engine  = Engine(network, kb, cfg)
    ctrl    = SDNcontroller(network, kb, cfg, engine)

    kb.clear_kb()
    kb.initialize_kb()

    # INIT with the fixed strategy: the post-init state is then a property of
    # (topology, n, seed) alone, identical for every strategy under test.
    engine.STRATEGY = getattr(engine, INIT_STRATEGY)
    t_init, (nvr, f_ko, f_rr, f_no_path) = _timed(ctrl.full_recompute)  # INIT: route every flow once
    
    logger.info(f"[{strategy} {topology} n={n} seed={seed}] INIT ({INIT_STRATEGY}) "f"in {t_init:.2f}s | routed {len(nvr)}/{num_flows}")

    # from here on the strategy under test drives every CR and FULL
    engine.STRATEGY = getattr(engine, strategy)

    # The INIT invariant (all flows routed) is checked by _run_batch, not here,
    # so the count reaches the CSV even when it fails.
    init_routed = len(nvr)
    return network, kb, engine, ctrl, init_routed


def _run_batch(config_base: dict) -> list:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "WARNING").upper(), format="%(asctime)s %(levelname)s %(message)s", force=True)

    # lazy import (runs in the Ray worker, not in the driver): the search budget
    # is read from where it is enforced, so the CSV cannot disagree with the code
    sys.path.insert(0, str(REPO_ROOT))

    topology    = config_base["topology"]
    n           = config_base["n"]
    flow_factor = config_base["flow_factor"]
    seed        = config_base["seed"]
    num_flows   = int(flow_factor * n)
    strategy    = config_base.get("strategy", STRATEGIES[0])
    pct_mods    = config_base.get("pct_mods", PCT_MODS)
    epochs      = config_base.get("epochs", EPOCHS)

    base = {"strategy": strategy, "topology": topology, "n": n, "flow_factor": flow_factor, "seed": seed, "init_routed": None}
    results   = []
    topo_file = None

    try:
        fd, topo_file = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        network, kb, engine, ctrl, init_routed = _build_system(topology, n, num_flows, seed, topo_file, strategy)
        base["init_routed"] = init_routed

        max_flows_failed = max(1, int(INIT_TOLERANCE * num_flows))
        if num_flows - init_routed > max_flows_failed:
            raise heuristic_benchmark_exception(f"The experiment starts with {init_routed} routing\nabort experiment")

        num_edges = len(network.graph.edges)
        sizes = {"num_edges": num_edges, "num_flows": num_flows}

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
                    results.append(_make_row(base, pct_mod, epoch, **sizes, ok=False, error=str(e)))
                    logger.warning(f"[{strategy} {topology} n={n} seed={seed}] "f"pct={pct_mod} epoch {epoch + 1} failed: {e}")
                    break
                
    except Exception as e:
        logger.warning(f"[{strategy} {topology} n={n} seed={seed}] batch failed: {e}")
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
    NUM_WORKERS = int(os.environ.get("NUM_WORKERS", 7))

    BATCH_TIMEOUT = float(os.environ.get("BATCH_TIMEOUT", 2 * 3600))   # 2 h
    WAIT_POLL     = 30.0   # how often the loop wakes up to check the budget

    OUTPUT_CSV = sys.argv[1] if len(sys.argv) > 1 else "heuristic_benchmark.csv"

    ray.init(num_cpus=NUM_WORKERS)

    all_configs = [
        {"strategy": strat, "topology": t, "n": n, "flow_factor": ff, "seed": s}
        for n, t, ff, s, strat in itertools.product(SIZES, TOPOLOGIES, FLOW_FACTORS, SEEDS, STRATEGIES)
        if not (strat == "exhaustive_paths" and n > EXHAUSTIVE_MAX_NODES)
    ]
    csv_out = RESULTS_DIR / OUTPUT_CSV
    results = []

    # ---- resume: skip the batches already present in the target CSV ----
    # The run is meant to be stopped by hand and picked up later, so an existing
    # CSV is treated as partial output, never overwritten. The batch key omits
    # pct_mod/epoch on purpose: a batch writes all of its rows or none.
    if csv_out.exists():
        prev    = pd.read_csv(csv_out)
        results = prev.to_dict("records")
        key     = ["strategy", "topology", "n", "flow_factor", "seed"]
        done    = set(map(tuple, prev[key].drop_duplicates().itertuples(index=False, name=None)))
        before  = len(all_configs)
        all_configs = [c for c in all_configs
                       if tuple(c[k] for k in key) not in done]
        print(f"Resume from {csv_out.name}: {len(done)} batches already done, "
              f"{len(all_configs)}/{before} left ({len(results)} rows kept)")

    total_batches = len(all_configs)
    total_rows    = total_batches * len(PCT_MODS) * EPOCHS
    print(f"Launching {total_batches} batches → {total_rows} rows " f"({len(PCT_MODS)} pct × {EPOCHS} epochs each) | {NUM_WORKERS} parallel workers")

    def _checkpoint() -> None:
        """Write the CSV atomically: a kill during the write leaves either the
        previous file or the new one, never a truncated one. Plain to_csv on the
        target would corrupt hours of results if interrupted mid-write."""
        tmp = csv_out.with_suffix(".csv.tmp")
        pd.DataFrame(results).to_csv(tmp, index=False)
        os.replace(tmp, csv_out)

    def _dead_batch_rows(cfg: dict, error: str) -> list:
        """Full-schema rows for a batch that returned nothing (cancelled on the
        wall-clock budget, or worker killed). Without them the batch would just
        be missing from the CSV, and a missing batch is indistinguishable from
        one never launched — the exclusion rate has to stay measurable.
        """
        base = {"strategy": cfg["strategy"], "topology": cfg["topology"], "n": cfg["n"],
                "flow_factor": cfg["flow_factor"], "seed": cfg["seed"],
                "init_routed": None}
        num_flows = int(cfg["flow_factor"] * cfg["n"])
        return [_make_row(base, pct_mod, epoch, num_flows=num_flows, ok=False, error=error)
                for pct_mod in PCT_MODS for epoch in range(EPOCHS)]

    # sliding window: keeps exactly NUM_WORKERS batches active.
    # ObjectRef -> (config, launch time), so a batch can be aged out.
    config_iter = iter(all_configs)
    active: dict = {}

    def _launch_next() -> None:
        cfg = next(config_iter, None)
        if cfg is not None:
            active[run_trial_batch.remote(cfg)] = (cfg, time.monotonic())

    for _ in range(NUM_WORKERS):
        _launch_next()

    done_batches = 0
    killed       = 0

    try:
        while active:
            # A bare ray.wait() blocks until something finishes: with the
            # exhaustive search unbounded, a batch that never returns would hold
            # its worker forever and, once every worker is stuck, freeze the run
            # with no further checkpoint. Polling instead lets the loop age out
            # batches that blew the budget.
            ready, _ = ray.wait(list(active), num_returns=1, timeout=WAIT_POLL)
            now = time.monotonic()

            for ref in ready:
                cfg, _t0 = active.pop(ref)
                try:
                    batch_results = ray.get(ref)
                except Exception as e:
                    # a worker killed by the OS/Ray memory monitor lands here:
                    # record it instead of taking the whole run down
                    batch_results = _dead_batch_rows(cfg, f"worker died: {e}")
                    print(f"  [WORKER DIED] strat={cfg['strategy']} topo={cfg['topology']} " f"n={cfg['n']} seed={cfg['seed']}: {e}", flush=True)

                done_batches += 1
                results.extend(batch_results)

                b0   = batch_results[0]
                n_ok = sum(1 for r in batch_results if r.get("ok"))
                print(f"  [batch {done_batches}/{total_batches}] "
                      f"strat={b0['strategy']} topo={b0['topology']} n={b0['n']} "
                      f"ff={b0['flow_factor']} seed={b0['seed']} "
                      f"→ {n_ok}/{len(batch_results)} rows ok "
                      f"[{now - _t0:.0f}s]", flush=True)
                _launch_next()

            # age out whatever blew the wall-clock budget
            for ref, (cfg, t0) in list(active.items()):
                if now - t0 <= BATCH_TIMEOUT:
                    continue
                ray.cancel(ref, force=True)   # max_calls=1: the worker is disposable
                active.pop(ref)
                killed += 1
                results.extend(_dead_batch_rows(
                    cfg, f"batch cancelled after {BATCH_TIMEOUT:.0f}s wall clock"))
                print(f"  [CANCELLED {killed}] strat={cfg['strategy']} topo={cfg['topology']} "
                      f"n={cfg['n']} seed={cfg['seed']} — over {BATCH_TIMEOUT / 3600:.1f}h",
                      flush=True)
                _launch_next()

            if ready or killed:
                # checkpoint after every batch that left the window, however it left
                _checkpoint()

    except KeyboardInterrupt:
        # stopping by hand is the expected way to end an overnight run: the
        # in-flight batches are discarded, everything already collected is kept
        print(f"\nInterrupted by hand after {done_batches} batches "
              f"({len(active)} in flight discarded) — CSV holds every completed batch",
              flush=True)
        _checkpoint()

    finally:
        print(f"   CSV → {csv_out} ({len(results)} rows, "
              f"{done_batches} batches done, {killed} cancelled on the {BATCH_TIMEOUT / 3600:.1f}h budget)")
        ray.shutdown()
