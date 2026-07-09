"""
Parallel benchmark runner: Continuous Reasoning vs Full Recompute.
Uses Ray Core (@ray.remote) for parallelism — avoids Ray Tune's
BasicVariantGenerator pickling bug on Python 3.14.

Batch structure: per ogni (topology, n, flow_factor, seed) viene eseguito
un solo init, poi tutti i PCT_MODS in sequenza con restore dello stato
post-init tra una perturbazione e l'altra.

Total batches: 3 × 4 × 4 × 10 = 480
Total trials:  3 × 4 × 4 × 4 × 10 = 1920
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

SEEDS = [104729, 224737, 350377, 479909, 611953, 742073, 871871, 1003001, 1234567, 15485863]
TOPOLOGIES   = ["er", "ba", "iaag"]
SIZES        = [250, 500, 750, 1000]
FLOW_FACTORS = [0.25, 0.50, 0.75, 1.00]
PCT_MODS     = [0.10, 0.20, 0.30, 0.50]


@ray.remote(num_cpus=1, max_calls=1)
def run_trial_batch(config_base: dict) -> list:
    """Esegue tutti i PCT_MODS per una combinazione (topology, n, flow_factor, seed).
    L'init viene fatto una sola volta; ogni pct_mod riusa lo stato post-init."""
    logging.basicConfig(level=logging.WARNING)

    # lazy imports: ogni worker Ray ha il proprio stato Python e runtime Prolog
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
    num_hosts   = max(2, n // 10)

    topo_file = None
    results   = []

    try:
        # ── genera topologia ──────────────────────────────────────────────
        random.seed(seed)
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

        # ── [INIT] una sola volta per tutti i pct_mod ────────────────────
        ctrl.full_recompute()

        # pre-calcola gli indici dei link router-router (invarianti per tutto il batch)
        rr_indices = [
            idx for idx in network.graph.edge_indices()
            if not (
                network.inv_node_map[network.graph.get_edge_endpoints_by_index(idx)[0]].startswith("h") or
                network.inv_node_map[network.graph.get_edge_endpoints_by_index(idx)[1]].startswith("h")
            )
        ]

        # snapshot dello stato post-init: sarà ripristinato dopo ogni perturbazione
        post_init_snapshot = kb.snapshot_kb_state()

        # ── loop su ogni livello di perturbazione ────────────────────────
        for pct_mod in PCT_MODS:
            config   = {**config_base, "pct_mod": pct_mod}
            selected = []  # inizializzato prima del try per il finally

            try:
                # sub-seed indipendente e riproducibile per ogni (seed, pct_mod)
                random.seed(hash((seed, pct_mod)) % (2**32))

                # [PERTURB] seleziona pct_mod% dei link rr e degrada la banda
                n_mod    = max(1, int(pct_mod * len(rr_indices)))
                selected = random.sample(rr_indices, min(n_mod, len(rr_indices)))
                degraded = []
                for idx in selected:
                    ed      = network.graph.get_edge_data_by_index(idx)
                    new_bw  = ed["bw_nominal"] * random.uniform(0.1, 0.5)
                    ed["bw"] = new_bw
                    network.graph.update_edge_by_index(idx, ed)
                    degraded.append((ed["u"], ed["v"], new_bw))
                kb.update_links_bandwidth(degraded)

                # [CR] solo i flussi KO vengono re-instradati
                t0 = time.perf_counter()
                _, n_ko, n_r = ctrl.continuos_reasoning()
                t_cr = time.perf_counter() - t0

                # [FULL] tutti i flussi vengono re-instradati da zero
                t0 = time.perf_counter()
                _, n_full_ko, n_full_r = ctrl.full_recompute()
                t_full = time.perf_counter() - t0

                speedup = t_full / t_cr if t_cr > 0 else float("inf")

                results.append({
                    **config,
                    "num_nodes":   num_nodes,
                    "num_edges":   num_edges,
                    "num_flows":   num_flows,
                    "T_CR":        t_cr,
                    "T_FULL":      t_full,
                    "N_KO_CR":        n_ko,
                    "N_R_CR":         n_r,
                    "N_KO_FULL":      n_full_ko,
                    "N_R_FULL":       n_full_r,
                    "P_KO":        n_ko / num_flows if num_flows > 0 else 0.0,
                    "P_R":         n_r / num_flows if num_flows > 0 else 0.0,
                    "Speedup":     speedup,
                    "n_links_mod": len(selected),
                    "ok":          True,
                    "error":       "",
                })

            except Exception as e:
                results.append({**config, "ok": False, "error": str(e)})

            finally:
                # ── RESTORE ──────────────────────────────────────────────
                # 1) ripristina bw a bw_nominal nel grafo Python e in Prolog
                if selected:
                    restored = []
                    for idx in selected:
                        ed = network.graph.get_edge_data_by_index(idx)
                        ed["bw"] = ed["bw_nominal"]
                        network.graph.update_edge_by_index(idx, ed)
                        restored.append((ed["u"], ed["v"], ed["bw_nominal"]))
                    kb.update_links_bandwidth(restored)
                # 2) ripristina routing e path allo stato post-init
                kb.restore_kb_state(post_init_snapshot)

    except Exception as e:
        # errore durante init o snapshot: tutti i pct_mod del batch falliscono
        for pct_mod in PCT_MODS:
            results.append({
                **config_base, "pct_mod": pct_mod,
                "ok": False, "error": f"Init failed: {e}",
            })

    finally:
        if topo_file and os.path.exists(topo_file):
            os.unlink(topo_file)

    return results


if __name__ == "__main__":
    os.environ["RAY_local_fs_capacity_threshold"] = "0.99"
    RESULTS_DIR.mkdir(exist_ok=True)
    NUM_WORKERS = 4
    ray.init(num_cpus=NUM_WORKERS)

    # 480 batch: niente pct_mod nel prodotto cartesiano
    all_configs = [
        {"topology": t, "n": n, "flow_factor": ff, "seed": s}
        for t, n, ff, s in itertools.product(TOPOLOGIES, SIZES, FLOW_FACTORS, SEEDS)
    ]
    total_batches = len(all_configs)
    total_trials  = total_batches * len(PCT_MODS)
    print(f"Launching {total_batches} batches → {total_trials} trials | {NUM_WORKERS} parallel workers")

    # sliding window: mantiene esattamente NUM_WORKERS batch attivi
    config_iter  = iter(all_configs)
    active       = []
    for cfg in itertools.islice(config_iter, NUM_WORKERS):
        active.append(run_trial_batch.remote(cfg))

    results      = []
    done_trials  = 0
    done_batches = 0
    csv_out = RESULTS_DIR / "benchmark_cr_severe_shortest_simple_paths.csv"

    while active:
        ready, active = ray.wait(active, num_returns=1)
        batch_results = ray.get(ready[0])
        done_batches += 1

        for result in batch_results:
            results.append(result)
            done_trials += 1
            status = "✓" if result.get("ok") else "✗"
            print(
                f"  [{done_trials}/{total_trials}] {status}"
                f"  topo={result['topology']}  n={result['n']}"
                f"  ff={result['flow_factor']}  pct={result['pct_mod']}  seed={result['seed']}"
                + (f"  T_CR={result['T_CR']:.3f}s  Speedup={result['Speedup']:.1f}x"
                   if result.get("ok") else f"  ERROR: {result.get('error')}")
            )

        # checkpoint: salva il CSV parziale dopo ogni batch
        pd.DataFrame(results).to_csv(csv_out, index=False)

        # appena si libera uno slot, sottometti il batch successivo
        next_cfg = next(config_iter, None)
        if next_cfg is not None:
            active.append(run_trial_batch.remote(next_cfg))

    print(f"   CSV → {csv_out}")
    ray.shutdown()
