import os
import sys
import random
import tempfile
import itertools
import logging
from pathlib import Path

import ray
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
# Everything identical is imported, not copied, so the two experiments cannot
# drift apart. _run_epoch pulls in the rest of the protocol (_perturb_epoch,
# _frac_degraded, _compute_metrics, ...) and _make_row the CSV schema: both keep
# reading epoch_benchmark's own globals (DEGRADE_FACTOR, _ROW_DEFAULTS), so
# redefining those here would be silently ignored — change them there.
from epoch_benchmark import (
    epoch_benchmark_exception,
    BENCHMARK_DIR, REPO_ROOT, KB_FILE, RESULTS_DIR,
    SEEDS, TOPOLOGIES,
    _make_row, _timed, _reset_to_nominal, _run_epoch,
)

logger = logging.getLogger(__name__)

STRATEGIES   = ["exhaustive_paths", "latency_biased_paths","biased_k_shortest_path_latency", "biased_k_shortest_path"]
SIZES        = [20, 30, 40, 50, 60, 70, 80, 90, 100]
FLOW_FACTORS = [1.00]
PCT_MODS     = [0.10, 0.30, 0.50]
EPOCHS       = 15

INIT_STRATEGY = "biased_k_shortest_path_latency"

EXHAUSTIVE_MAX_N = 50


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
        raise epoch_benchmark_exception(f"Unknown strategy {strategy}")

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
    logger.info(f"[{strategy} {topology} n={n} seed={seed}] INIT ({INIT_STRATEGY}) "
                f"in {t_init:.2f}s | routed {len(nvr)}/{num_flows}")

    # from here on the strategy under test drives every CR and FULL
    engine.STRATEGY = getattr(engine, strategy)

    # The INIT invariant (all flows routed) is checked by _run_batch, not here,
    # so the count reaches the CSV even when it fails.
    return network, kb, engine, ctrl, len(nvr)


def _run_batch(config_base: dict) -> list:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "WARNING").upper(), format="%(asctime)s %(levelname)s %(message)s", force=True)

    # lazy import (runs in the Ray worker, not in the driver): the search budget
    # is read from where it is enforced, so the CSV cannot disagree with the code
    sys.path.insert(0, str(REPO_ROOT))
    from RoutingEngine import EXHAUSTIVE_TIMEOUT

    topology    = config_base["topology"]
    n           = config_base["n"]
    flow_factor = config_base["flow_factor"]
    seed        = config_base["seed"]
    num_flows   = int(flow_factor * n)
    strategy    = config_base.get("strategy", STRATEGIES[0])
    pct_mods    = config_base.get("pct_mods", PCT_MODS)
    epochs      = config_base.get("epochs", EPOCHS)

    # Batch-level facts repeated on every row:
    #   init_routed      how many flows the (fixed-strategy) INIT managed to route
    #   search_timeout   the strategy under test ran out of time on some search
    #   timeout_s        the budget in force, so the run is self-identifying
    # Since the INIT no longer uses the strategy under test, a timeout now shows
    # up during the epochs, not at build time — hence the neutral name.
    base = {"strategy": strategy, "topology": topology, "n": n, "flow_factor": flow_factor,
            "seed": seed, "init_routed": None,
            "search_timeout": False, "timeout_s": EXHAUSTIVE_TIMEOUT}
    results   = []
    topo_file = None

    try:
        fd, topo_file = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        network, kb, engine, ctrl, init_routed = _build_system(topology, n, num_flows, seed, topo_file, strategy)
        base["init_routed"] = init_routed

        if init_routed != num_flows:
            raise epoch_benchmark_exception(f"The experiment starts with {init_routed} routing")

        num_nodes = len(network.graph.nodes)
        num_edges = len(network.graph.edges)
        sizes = {"num_nodes": num_nodes, "num_edges": num_edges, "num_flows": num_flows}

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
                    # lazy import: keeps the Prolog runtime out of the driver process
                    from RoutingEngine import ExhaustiveTimeoutError
                    if isinstance(e, ExhaustiveTimeoutError):
                        base["search_timeout"] = True
                    results.append(_make_row(base, pct_mod, epoch, **sizes, ok=False, error=str(e)))
                    logger.warning(f"[{strategy} {topology} n={n} seed={seed}] "
                                   f"pct={pct_mod} epoch {epoch + 1} failed: {e}")
                    break

    except Exception as e:
        from RoutingEngine import ExhaustiveTimeoutError
        base["search_timeout"] = isinstance(e, ExhaustiveTimeoutError)
        logger.warning(f"[{strategy} {topology} n={n} seed={seed}] batch failed: {e}")
        for pct_mod in pct_mods:
            for epoch in range(epochs):
                results.append(_make_row(base, pct_mod, epoch, num_flows=num_flows, ok=False, error=f"Init failed: {e}"))

    finally:
        if topo_file and os.path.exists(topo_file):
            os.unlink(topo_file)

    # search_timeout is a batch-level verdict but may be discovered halfway
    # through, so it is stamped on every row of the batch, not only the later ones
    for row in results:
        row["search_timeout"] = base["search_timeout"]

    return results


run_trial_batch = ray.remote(num_cpus=1, max_calls=1)(_run_batch)


if __name__ == "__main__":
    os.environ["RAY_local_fs_capacity_threshold"] = "0.99"
    RESULTS_DIR.mkdir(exist_ok=True)
    NUM_WORKERS = 7

    OUTPUT_CSV = sys.argv[1] if len(sys.argv) > 1 else "heuristic_benchmark.csv"

    ray.init(num_cpus=NUM_WORKERS)

    all_configs = [
        {"strategy": strat, "topology": t, "n": n, "flow_factor": ff, "seed": s}
        for strat, t, n, ff, s in itertools.product(STRATEGIES, TOPOLOGIES, SIZES, FLOW_FACTORS, SEEDS)
        # the exhaustive search does not complete above EXHAUSTIVE_MAX_N: those
        # configurations are skipped instead of being paid for as timeouts
        if not (strat == "exhaustive_paths" and n > EXHAUSTIVE_MAX_N)
    ]
    total_batches = len(all_configs)
    total_rows    = total_batches * len(PCT_MODS) * EPOCHS
    print(f"Launching {total_batches} batches → {total_rows} rows " f"({len(PCT_MODS)} pct × {EPOCHS} epochs each) | {NUM_WORKERS} parallel workers")

    # sliding window: keeps exactly NUM_WORKERS batches active
    config_iter = iter(all_configs)
    active      = [run_trial_batch.remote(cfg) for cfg in itertools.islice(config_iter, NUM_WORKERS)]

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
              f"strat={b0['strategy']} topo={b0['topology']} n={b0['n']} "
              f"ff={b0['flow_factor']} seed={b0['seed']} "
              f"→ {n_ok}/{len(batch_results)} rows ok")

        # checkpoint: rewrite the partial CSV after every completed batch
        pd.DataFrame(results).to_csv(csv_out, index=False)

        next_cfg = next(config_iter, None)
        if next_cfg is not None:
            active.append(run_trial_batch.remote(next_cfg))

    print(f"   CSV → {csv_out}")
    ray.shutdown()
