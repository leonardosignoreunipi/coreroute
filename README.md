# CoReRoute

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/logo/dark-tagline.png">
  <source media="(prefers-color-scheme: light)" srcset="assets/logo/light-tagline.png">
  <img src="assets/logo/light-tagline.png" alt="CoReRoute — Continuous Routing Repair in SDN" width="720">
</picture>

# CoReRoute

*Continuous Reasoning for SDN Route Repair*

CoReRoute is a research prototype of a hybrid SDN controller for self-healing routing repair. It splits routing decisions across two engines with different responsibilities: **Python / NetworkX** proposes candidate paths cheaply, and **SWI-Prolog** (embedded via [`janus_swi`](https://pypi.org/project/janus-swi/)) is the authoritative layer — the only component that reasons about bandwidth contention between flows and latency budgets, and the one that commits the final routing.

It was built to answer two questions about routing repair under progressive network degradation:

1. **How close do fast path-search heuristics get to a true combinatorial optimum**, when repairing a single broken flow?
2. **At scale, is it cheaper to reroute only what broke** (*Continuous Reasoning*) **or to recompute the whole network from scratch** every time the network degrades (*Full Recompute*)?

The repository contains the controller itself, three synthetic topology generators, and a [Ray](https://www.ray.io/)-parallel benchmark harness used to answer both questions experimentally.

> Developed as part of a Master's thesis at the University of Pisa — see [Citing this work](#citing-this-work).

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quickstart](#quickstart)
- [Repository layout](#repository-layout)
- [Running the benchmarks](#running-the-benchmarks)
- [Benchmark methodology](#benchmark-methodology)
- [Known limitations](#known-limitations)
- [Contributing](#contributing)
- [Citing this work](#citing-this-work)
- [License](#license)
- [Acknowledgments](#acknowledgments)

## Features

- **Two-stage routing** — cheap NetworkX candidate generation feeding an authoritative Prolog validator, so bandwidth/latency accounting is never duplicated or re-approximated on the Python side.
- **Two reconfiguration strategies** — Continuous Reasoning (reroute only broken flows, biased to reuse each flow's previous path) vs. Full Recompute (discard all state, reroute everything).
- **Four interchangeable candidate-search strategies**, plus a true combinatorial optimum (`exhaustiveRouting/3`, which explores every flow-processing order) usable as ground truth on small topologies.
- **Three synthetic topology generators** — Erdős–Rényi, Barabási–Albert, and a hierarchical Internet-AS model (`networkx.random_internet_as_graph`) — with bandwidth/latency parameters aligned to a reference SDN benchmarking paper.
- **A Ray-parallelized benchmark harness** that replays cumulative, epoch-by-epoch degradation sequences and records reconfiguration cost, latency and timing to CSV, with checkpointing and per-batch timeouts.
- **A declared, paired experimental methodology** (statistical unit = sequence, not epoch; a pre-declared confirmatory cell; seed counts sized for Wilcoxon significance) — see [Benchmark methodology](#benchmark-methodology).

## Architecture

```
 ┌────────────────────────────┐          ┌──────────────────────────────┐
 │ Stage 1 — Python            │          │ Stage 2 — Prolog              │
 │ (RoutingEngine)              │          │ (routing_core.pl, via janus)  │
 │                               │  writes  │                                │
 │ 1. prune graph by bandwidth  │ ───────▶ │ crRouting/4 walks the KO      │
 │ 2. generate K candidates      │ pathsCandidates │ list, committing the    │
 │    per KO flow (pluggable     │          │ first candidate that passes   │
 │    STRATEGY)                  │          │ validPath/3:                  │
 │ 3. write candidates to KB     │          │  · bandwidth contention        │
 │                                │          │    (availableBandwidthLink)   │
 │                                │  reads   │  · latency budget              │
 │                                │ ◀─────── │ new routings feed forward     │
 │                                │ routing/2│ into the next flow's check    │
 └────────────────────────────┘          └──────────────────────────────┘
```

NetworkX picks *plausible* paths cheaply; Prolog performs the *authoritative* feasibility and mutual-exclusion reasoning — it is the only component that knows how much bandwidth every other already-committed flow is consuming on a given link. A flow is **OK** if its current path still validates, **KO** otherwise; Stage 1 only ever generates candidates for KO flows.

### Reconfiguration strategies (`SDNcontroller`)

| Strategy | Method | Behaviour |
|---|---|---|
| Continuous Reasoning | `continuous_reasoning()` | Read the current OK/KO partition from the KB, reroute only the KO flows. |
| Full Recompute | `full_recompute()` | Point every flow at the empty sentinel path (`p_init`) and reroute all of them. |

Both funnel into the same `RoutingEngine.re_routing()` — Full Recompute is Continuous Reasoning starting from an empty state, not a separate code path.

### Candidate-search strategies (`RoutingEngine.STRATEGY`)

Four interchangeable candidate generators, all sharing the signature `(graph_pruned, src, dst, flow_id, old_path) -> list[(score, path_nodes)]`. The short names below are also how the corresponding output lives under `benchmark/results/` (see [Repository layout](#repository-layout)):

| Strategy | Method | Candidate set | Ordered by |
|---|---|---|---|
| **reuse** | `biased_k_shortest_path` | K=10 shortest paths, weighted to reuse the old path | reconfiguration cost |
| **reuseDelay** | `biased_k_shortest_path_latency` | same K=10 generation as above | (reconfiguration cost, latency) |
| **delay** | `latency_biased_paths` | top 100 by per-edge latency, keep top 10 | reconfiguration cost (ties preserve latency order) |
| **exhaustive** | `all_simple_candidates` | **all** simple paths up to `2 × diameter` hops | (reconfiguration cost, latency) |

"Reconfiguration cost" (`diff_score`) is the directed symmetric edge-set difference between old and new path — each differing directed edge approximates one forwarding-table update a real controller would push.

### Resolution strategies (`RoutingEngine.prolog_strategy`)

- **`resolve_cr_routing`** (default) — `crRouting/4`: walks the KO list once, committing the first feasible candidate per flow.
- **`resolve_exhaustive_routing`** — `exhaustiveRouting/3`: re-runs `crRouting/4` over **every permutation** of the KO-flow processing order; `select_best_exhaustive_solution` then picks the permutation with the fewest failures, then the lowest total reconfiguration cost, then the lowest latency. Paired with `all_simple_candidates`, this is the **true combinatorial optimum** used as ground truth — factorial in the number of KO flows, so it is only run on small topologies (see [Known limitations](#known-limitations)).

## Requirements

- **Python ≥ 3.10** (developed and verified on 3.12 and 3.14; no version-specific syntax is used).
- **SWI-Prolog ≥ 9.x**, which provides the embedded Janus bridge `janus_swi` talks to. Install it as a system package *before* the Python dependencies:
  - macOS: `brew install swi-prolog`
  - Debian/Ubuntu: `sudo apt install swi-prolog`
  - Other platforms: <https://www.swi-prolog.org/Download.html>
- Python packages: `networkx`, `ray`, `pandas`, `numpy`, `matplotlib`, `seaborn`, `janus-swi`.

## Installation

```bash
git clone https://github.com/leonardosignoreunipi/tesi.git
cd tesi/coreroute
python3 -m venv .venv
source .venv/bin/activate
pip install networkx ray pandas numpy matplotlib seaborn janus-swi
```

> No dependency manifest is committed yet — see [Repository layout](#repository-layout) for a `requirements.txt` you can add.

## Quickstart

The five collaborators are always wired the same way — `ConfigLoader` loads a topology JSON, `PhysicalNetwork` builds the NetworkX graph, `JanusKB` boots the embedded Prolog runtime, `RoutingEngine` generates candidates, `SDNcontroller` orchestrates a reasoning step:

```python
from ConfigLoader import ConfigLoader
from PhysicalNetwork import PhysicalNetwork
from JanusKB import JanusKB
from RoutingEngine import RoutingEngine
from SDNcontroller import SDNcontroller

config  = ConfigLoader("topology.json").load()
network = PhysicalNetwork(config)
kb      = JanusKB(config, "routing_core.pl")
engine  = RoutingEngine(network, kb, config)
ctrl    = SDNcontroller(network, kb, config, engine)

kb.clear_kb()
kb.initialize_kb()

# ...degrade a link's bandwidth (network.graph[u][v]["bw"] = ...,
# kb.update_links_bandwidth([(u, v, new_bw)])), then reroute what broke:
new_valid, n_ko, n_rerouted, no_path_count = ctrl.continuous_reasoning()
```

`topology.json` is plain JSON (hosts, routers, links, flows, paths, routings) — generate one with `benchmark/build_topology.py` (see [Running the benchmarks](#running-the-benchmarks) below), which produces exactly the shape `ConfigLoader` expects.

## Repository layout

```
coreroute/
├── Models.py                    # Dataclasses: Flow, Router, Host, Link, Path, Routing
├── ConfigLoader.py               # Parses/validates topology JSON into TopologyConfig
├── PhysicalNetwork.py            # NetworkX graph wrapper; bandwidth-pruning prefilter
├── PathRegistry.py               # In-memory node-tuple -> path id cache (dedup)
├── JanusKB.py                    # Facade over the embedded SWI-Prolog runtime
├── RoutingEngine.py               # Stage 1: candidate generation, the 4 STRATEGY methods
├── SDNcontroller.py               # continuous_reasoning() / full_recompute()
├── routing_core.pl                # Stage 2: crRouting/4, exhaustiveRouting/3, validPath/3
└── benchmark/
    ├── build_topology.py          # er / ba / iaag synthetic topology generator (CLI)
    ├── epoch_benchmark.py         # Experiment 2: Continuous Reasoning vs Full Recompute
    ├── heuristic_benchmark.py     # Experiment 1: heuristics vs. the true optimum
    ├── calibrate_parameters/       # One-off pilots for perturbation parameters (not thesis-citable)
    └── results/                    # Benchmark output, one folder per experiment run
        ├── exhaustive/             # Experiment 1: data.csv + grafici.py (its plotting script) + graphs/
        ├── hreuse/                 # Experiment 2, reuse strategy: CSV + build_graphs.py + graphs/
        └── hreuseDelay/            # Experiment 2, reuseDelay strategy: CSV + build_graphs.py + graphs/
```

This is the intended layout of the *code*; see the note on generated experiment output in [Running the benchmarks](#running-the-benchmarks). There is no single top-level plotting entry point — each run under `benchmark/results/` carries its own plotting script next to its data.

## Running the benchmarks

### 1. Generate a topology

```bash
python benchmark/build_topology.py <er|ba|iaag> <num_nodes> <num_flows> <output.json> <seed>
```

### 2. Experiment 1 — heuristics vs. the true optimum (small scale)

```bash
python benchmark/heuristic_benchmark.py heuristic_results.csv
```

Sweeps all four strategies (`delay`, `reuseDelay`, `reuse`, `exhaustive`) over `SIZES = [20, 25, 30, 35, 40]` × `NUM_FLOWS_LIST = [3, 4, 5, 6]` × 10 seeds × 3 topologies × 3 `pct_mod` perturbation levels × 10 epochs, and writes one row per `(strategy, topology, n, seed, pct_mod, epoch)` to `benchmark/results/`.

### 3. Experiment 2 — Continuous Reasoning vs. Full Recompute (large scale)

```bash
python benchmark/epoch_benchmark.py epoch_results.csv
```

Sweeps 3 topologies × `SIZES = [250, 500, 750, 1000]` × `FLOW_FACTORS = [0.25, 0.50, 0.75, 1.00]` × 10 seeds × 4 `pct_mod` levels × 20 cumulative-degradation epochs. Every epoch measures **both** strategies against the identical pre-degradation state.

### 4. Plot the results

Each experiment folder under `benchmark/results/` carries its own plotting script next to its data — run from inside that folder:

```bash
cd benchmark/results/exhaustive && python grafici.py       # Experiment 1: figures + gap tables
```

```bash
cd benchmark/results/hreuse && python build_graphs.py      # Experiment 2, reuse strategy
```

```bash
cd benchmark/results/hreuseDelay && python build_graphs.py # Experiment 2, reuseDelay strategy
```

### Notes before launching a sweep

- The candidate-search strategy is selected by editing the `STRATEGY` constant at the top of the script (or, for `heuristic_benchmark.py`, the `STRATEGIES` list) — there is no CLI flag. Always check `git diff` beforehand; a forgotten change silently mislabels an entire run.
- Both drivers use `Ray` (`@ray.remote(max_calls=1)`, one fresh process per batch, since the embedded Prolog runtime is one-per-process). Tune the worker count to your machine's core count (`NUM_WORKERS` in `epoch_benchmark.py`, or the `NUM_WORKERS` env var for `heuristic_benchmark.py`).
- **Never point an exhaustive strategy at a large topology.** `all_simple_candidates` enumerates all simple paths (exponential in graph size); `exhaustiveRouting/3` explores every permutation of the KO-flow list (factorial in flow count). Both are only tractable at the small scale `heuristic_benchmark.py` already uses (≤ 40 nodes, ≤ 6 flows) — never at the `epoch_benchmark.py` scale (hundreds to thousands of nodes).
- Large sweeps are CPU-bound and can run for hours; launch them in a persistent session (`tmux`/`screen`) and pipe output to a log file, e.g. `tmux new -s bench 'python benchmark/epoch_benchmark.py out.csv 2>&1 | tee out.log'`.
- Output is checkpointed after every completed batch, so an interrupted run (`Ctrl-C`) keeps every batch finished so far.

## Benchmark methodology

The harness is built around a few explicit, non-negotiable conventions:

- **Paired design.** Every strategy under comparison sees the exact same topology, seed, and perturbation sequence, so within-seed differences isolate the strategy's effect.
- **The statistical unit is the sequence, not the epoch.** Degradation is cumulative and Continuous Reasoning's state persists across epochs, so the epochs of one run are not independent samples — aggregate per sequence first (e.g. last epoch, or a mean), then treat sequences as the sample.
- **One pre-declared confirmatory cell.** `n=1000, flow_factor=1.0` is treated as confirmatory; every other cell in the grid is exploratory and reported descriptively, not tested — testing the full grid would manufacture false positives.
- **≥ 10 seeds per cell**, sized so a paired Wilcoxon signed-rank test can reach significance at α = 0.05 (5 seeds cannot, by construction).
- **The latency budget is deliberately not the binding constraint in this regime** — link bandwidth is set below a reference paper's values on purpose, to study reconfiguration under *capacity scarcity*; every failure in these experiments is a bandwidth failure, not a latency one.
- **Timing measures the prototype, not the reasoning algorithm.** `T_CR` / `T_FULL` include the Python↔Prolog marshalling cost of the `janus_swi` bridge, which dominates the actual reasoning time.

## Known limitations

- `exhaustiveRouting/3` is combinatorial (`N!` flow-processing orders) — tractable only up to roughly 7 KO flows / 50 nodes; treat it as a correctness reference, never as a benchmarkable strategy at scale.
- `all_simple_candidates` enumerates every simple path within a hop cutoff — exponential in graph size; small graphs only.
- `crRouting/4` alone (even fed an exhaustive candidate set) is **not** a true optimum: it commits to the first feasible candidate per flow in a fixed order and never backtracks across flows. Only `exhaustiveRouting/3` (permuting that order) recovers the true optimum.
- `no_path_count` means "no path exists in the bandwidth-pruned graph" — it is not evidence of physical network disconnection.
- No automated test suite yet; the scripts under `benchmark/calibrate_parameters/` are the closest thing to manual smoke tests.

## Contributing

Issues and pull requests are welcome. This started as single-author thesis code, so please open an issue to discuss a change before investing time in a larger PR. There is no CI or test suite yet (see [Known limitations](#known-limitations)) — until there is, please describe how you validated a change (which script you ran, and against what topology size) in the PR description.

## Citing this work

If you use CoReRoute in academic work, please cite the thesis it was developed for:

```
Leonardo Signore. "[Thesis title]." Master's Thesis, University of Pisa, 2026.
Advisor: [Advisor name].
```

## License

No license is currently declared. A public repository without a `LICENSE` file is **not** open source by default — under default copyright, nobody else may legally reuse the code no matter how it's hosted. Common choices for research/thesis code are MIT (short, permissive) or Apache-2.0 (adds an explicit patent grant); add a `LICENSE` file at the repository root with your choice before advertising this as open source.

## Acknowledgments

Experimental parameters (flow rate, latency budget, per-hop and per-link latency) are aligned with the reference paper [arXiv:2503.21289](https://arxiv.org/abs/2503.21289) wherever the experimental regime allows; link bandwidth is deliberately set lower than the reference to study routing repair under capacity scarcity (see [Benchmark methodology](#benchmark-methodology)).
