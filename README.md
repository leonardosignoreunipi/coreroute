# CoReRoute

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/logo/dark-tagline.png">
  <source media="(prefers-color-scheme: light)" srcset="assets/logo/light-tagline.png">
  <img src="assets/logo/light-tagline.png" alt="CoReRoute — Continuous Routing Repair in SDN" width="720">
</picture>

*Continuous Reasoning for SDN Route Repair* — a research prototype of a hybrid SDN controller for self-healing routing repair, developed for a Master's thesis at the University of Pisa.

Routing decisions are split across two engines: **Python/NetworkX** proposes candidate paths cheaply, and **SWI-Prolog** (via [`janus_swi`](https://pypi.org/project/janus-swi/)) is the authoritative layer that checks bandwidth/latency feasibility and commits the final routing.

## Requirements

- Python ≥ 3.10
- SWI-Prolog ≥ 9.x (`brew install swi-prolog` / `apt install swi-prolog`)
- `pip install networkx ray pandas numpy matplotlib seaborn janus-swi`

## Repository layout

```
coreroute/
├── Models.py                  # Dataclasses: Flow, Router, Host, Link, Path, Routing
├── ConfigLoader.py             # Parses/validates a topology JSON into TopologyConfig
├── PhysicalNetwork.py          # NetworkX graph wrapper; bandwidth-pruning prefilter
├── PathRegistry.py             # In-memory node-tuple -> path id cache (dedup)
├── JanusKB.py                  # Facade over the embedded SWI-Prolog runtime
├── RoutingEngine.py            # Stage 1 engine: see below
├── SDNcontroller.py            # continuous_reasoning() / full_recompute() orchestration
├── routing_core.pl             # Stage 2 (Prolog): crRouting/4, exhaustiveRouting/3, validPath/3
└── benchmark/
    ├── build_topology.py       # er / ba / iaag synthetic topology generator (CLI)
    ├── heuristic_benchmark.py  # Experiment 1: see below
    ├── epoch_benchmark.py      # Experiment 2: see below
    ├── calibrate_parameters/   # One-off pilots for perturbation parameters (not thesis-citable)
    └── results/                # One folder per run, each with its own plotting script
```

### RoutingEngine.py

Stage 1 of the pipeline: given the set of KO (broken) flows, it prunes the graph by residual bandwidth and generates up to K candidate paths per flow, ordering them by reconfiguration cost (and latency, depending on strategy). It exposes four interchangeable candidate-search strategies (`biased_k_shortest_path`, `biased_k_shortest_path_latency`, `latency_biased_paths`, `all_simple_candidates`) selected via the `STRATEGY` constant. `all_simple_candidates` enumerates *every* simple path and is only tractable on small topologies — paired with Prolog's `exhaustiveRouting/3` it gives the true combinatorial optimum used as ground truth. The engine never validates feasibility itself; it only proposes, Prolog decides.

### benchmark/heuristic_benchmark.py — Experiment 1

Compares the three fast heuristic strategies against the true optimum (`exhaustive`) on small topologies (≤ 40 nodes, ≤ 6 flows), to measure how close cheap path search gets to optimal repair cost. Sweeps sizes, flow counts, seeds, topology types and perturbation levels; writes one CSV row per `(strategy, topology, n, seed, pct_mod, epoch)`.

### benchmark/epoch_benchmark.py — Experiment 2

Compares **Continuous Reasoning** (reroute only broken flows) against **Full Recompute** (reroute everything) at scale (hundreds–thousands of nodes), under cumulative epoch-by-epoch degradation. Every epoch measures both strategies from the identical pre-degradation state, to isolate whether local repair is cheaper than full recomputation as the network grows.

## Quickstart — running a test

Generate a small topology, then run the heuristic benchmark against it:

```bash
python benchmark/build_topology.py er 20 3 topo.json 42
python benchmark/heuristic_benchmark.py heuristic_results.csv
```

Both benchmark drivers use Ray with one fresh process per batch; for large `epoch_benchmark.py` sweeps, launch inside `tmux` and pipe to a log file:

```bash
tmux new -s bench 'python benchmark/epoch_benchmark.py out.csv 2>&1 | tee out.log'
```

## Known limitations

- `exhaustiveRouting/3` and `all_simple_candidates` are combinatorial/exponential — correctness references only, never benchmarkable at scale.
- `crRouting/4` alone commits to the first feasible candidate per flow and never backtracks — only `exhaustiveRouting/3` (permuting flow order) recovers the true optimum.
- No automated test suite; `benchmark/calibrate_parameters/` scripts are the closest thing to manual smoke tests.

## License

No license is currently declared — add one (e.g. MIT, Apache-2.0) before treating this as open source.
