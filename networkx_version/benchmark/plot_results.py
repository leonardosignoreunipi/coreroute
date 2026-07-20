"""
Reusable execution-time plot for any benchmark CSV produced by
epoch_benchmark.py / heuristic_benchmark.py (same fixed row schema).

One panel per topology (er, ba, iaag), x = number of nodes, y = execution
time (log scale). Two lines per panel: Continuous Reasoning (T_CR) and
Full Recompute (T_FULL), median with IQR band across every other dimension
present in the CSV (seed, flow_factor, pct_mod, epoch).

Usage:
    python benchmark/plot_results.py <input.csv> [output.png]

<input.csv> is resolved relative to benchmark/results/ if not found as-is.
<output.png> defaults to <input>.png next to the input CSV.
"""

import sys
from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BENCHMARK_DIR = Path(__file__).parent
RESULTS_DIR = BENCHMARK_DIR / "results"

TOPOLOGIES = ["er", "ba", "iaag"]
TOPO_LABEL = {"er": "ER", "ba": "BA", "iaag": "IAAG"}

# validated categorical pair (light mode): CVD dE 24.7/32.7, normal-vision dE 33.6, contrast >=3:1
COLOR_CR = "#2a78d6"
COLOR_FULL = "#eb6834"
INK, INK2, MUTED, SURFACE = "#0b0b0b", "#52514e", "#b8b7b0", "#fcfcfb"


def plot(csv_path: str, out_path: str | None = None) -> Path:
    csv_path = Path(csv_path)
    df = pd.read_csv(csv_path)
    df = df[df["ok"] == True]

    out_path = Path(out_path) if out_path else csv_path.with_suffix(".png")

    present = [t for t in TOPOLOGIES if t in df["topology"].unique()]
    fig, axes = plt.subplots(1, len(present), figsize=(5 * len(present), 5), facecolor=SURFACE)
    if len(present) == 1:
        axes = [axes]

    for ax, topo in zip(axes, present):
        ax.set_facecolor(SURFACE)
        ax.grid(True, axis="y", color=MUTED, lw=0.6, alpha=0.5)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(MUTED)
        ax.tick_params(colors=INK2, length=3)

        sub = df[df["topology"] == topo]
        xs = sorted(sub["n"].unique())

        for col, color, label in [("T_CR", COLOR_CR, "Continuous Reasoning"),
                                   ("T_FULL", COLOR_FULL, "Full Recompute")]:
            g = sub.dropna(subset=[col]).groupby("n")[col]
            if g.ngroups == 0:
                continue
            med = g.median().reindex(xs)
            q25 = g.quantile(0.25).reindex(xs)
            q75 = g.quantile(0.75).reindex(xs)
            ax.fill_between(xs, q25, q75, color=color, alpha=0.15, lw=0)
            ax.plot(xs, med, "-", color=color, lw=2, marker="o", ms=5,
                     mfc=SURFACE, mew=1.6, label=label, clip_on=False, zorder=3)

        ax.set_yscale()
        ax.set_xticks(xs)
        ax.set_title(TOPO_LABEL[topo], color=INK, fontsize=13, fontweight="bold", loc="left")
        ax.set_xlabel("nodi", color=INK2, fontsize=9)

    axes[0].set_ylabel("tempo di esecuzione (s, scala log)", color=INK2, fontsize=9)
    axes[0].legend(frameon=False, fontsize=9, labelcolor=INK2, loc="upper left")

    fig.suptitle(f"Tempo di esecuzione: Continuous Reasoning vs Full Recompute — {csv_path.name}",
                 color=INK, fontsize=13.5, fontweight="bold", x=0.02, ha="left")
    fig.text(0.02, 0.925, "mediana ± IQR aggregata su seed / flow_factor / pct_mod / epoche",
             color=INK2, fontsize=9)
    fig.tight_layout(rect=[0.01, 0.01, 0.99, 0.89])
    fig.savefig(out_path, dpi=170, facecolor=SURFACE)
    print(f"saved {out_path}")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python plot_results.py <input.csv> [output.png]")
        sys.exit(1)

    csv_arg = Path(sys.argv[1])
    if not csv_arg.exists():
        csv_arg = RESULTS_DIR / sys.argv[1]
    out_arg = sys.argv[2] if len(sys.argv) > 2 else None

    plot(str(csv_arg), out_arg)
