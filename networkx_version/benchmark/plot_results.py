"""
Reusable multi-figure benchmark plotter for any CSV produced by
epoch_benchmark.py / heuristic_benchmark.py (same fixed row schema).

Generates five figures (one PNG each):
  1. Execution time  – T_CR vs T_FULL
  2. Speed-up        – T_FULL / T_CR
  3. Quality counts  – N_KO_CR, N_R_CR, flows_changed_CR
  4. Symmetric diff  – diff_simm_tot_CR vs diff_simm_tot_FULL
  5. Average latency – avg_latency_CR vs avg_latency_FULL

Every figure has one panel per topology (er, ba, iaag).  The y-axis is
shared across topologies within each figure so scales are directly
comparable.  The x-axis is always the number of nodes.

Usage:
    python benchmark/plot_results.py <input.csv> [output_prefix]

<input.csv>      is resolved relative to benchmark/results/ if not
                 found as-is.
<output_prefix>  defaults to the input stem; files are saved as
                 <prefix>_time.png, <prefix>_speedup.png, etc.
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
COLOR_3 = "#2db87d"          # green for a third line
INK, INK2, MUTED, SURFACE = "#0b0b0b", "#52514e", "#b8b7b0", "#fcfcfb"


# ── helpers ──────────────────────────────────────────────────────────────

def _style_ax(ax):
    """Apply the common axis style."""
    ax.set_facecolor(SURFACE)
    ax.grid(True, axis="y", color=MUTED, lw=0.6, alpha=0.5)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(MUTED)
    ax.tick_params(colors=INK2, length=3)


def _plot_lines(ax, sub, xs, specs):
    """Plot median + IQR band for each (column, color, label) in *specs*.

    *specs* is a list of (col_name, color, label) tuples.
    """
    for col, color, label in specs:
        if col not in sub.columns:
            continue
        g = sub.dropna(subset=[col]).groupby("n")[col]
        if g.ngroups == 0:
            continue
        med = g.median().reindex(xs)
        q25 = g.quantile(0.25).reindex(xs)
        q75 = g.quantile(0.75).reindex(xs)
        ax.fill_between(xs, q25, q75, color=color, alpha=0.15, lw=0)
        ax.plot(xs, med, "-", color=color, lw=2, marker="o", ms=5,
                mfc=SURFACE, mew=1.6, label=label, clip_on=False, zorder=3)


def _make_figure(df, present, title, subtitle, ylabel, specs, out_path,
                 yscale="linear", ylim=None):
    """Create a figure with one panel per topology and save it."""
    fig, axes = plt.subplots(
        1, len(present),
        figsize=(5 * len(present), 5),
        facecolor=SURFACE,
        sharey=True,
    )
    if len(present) == 1:
        axes = [axes]

    for ax, topo in zip(axes, present):
        _style_ax(ax)
        sub = df[df["topology"] == topo]
        xs = sorted(sub["n"].unique())
        _plot_lines(ax, sub, xs, specs)
        ax.set_yscale(yscale)
        if ylim is not None:
            ax.set_ylim(ylim)
        ax.set_xticks(xs)
        ax.set_title(TOPO_LABEL[topo], color=INK, fontsize=13,
                     fontweight="bold", loc="left")
        ax.set_xlabel("nodi", color=INK2, fontsize=9)

    axes[0].set_ylabel(ylabel, color=INK2, fontsize=9)
    axes[0].legend(frameon=False, fontsize=9, labelcolor=INK2,
                   loc="upper left")

    fig.suptitle(title, color=INK, fontsize=13.5, fontweight="bold",
                 x=0.02, ha="left")
    fig.text(0.02, 0.925, subtitle, color=INK2, fontsize=9)
    fig.tight_layout(rect=[0.01, 0.01, 0.99, 0.89])
    fig.savefig(out_path, dpi=170, facecolor=SURFACE)
    plt.close(fig)
    print(f"saved {out_path}")


# ── public entry point ───────────────────────────────────────────────────

def plot(csv_path: str, out_prefix: str | None = None) -> list[Path]:
    csv_path = Path(csv_path)
    df = pd.read_csv(csv_path)
    df = df[df["ok"] == True]

    base = Path(out_prefix) if out_prefix else csv_path.with_suffix("")
    present = [t for t in TOPOLOGIES if t in df["topology"].unique()]
    subtitle = "mediana ± IQR aggregata su seed / flow_factor / pct_mod / epoche"
    saved: list[Path] = []

    # 1 ── Execution time ────────────────────────────────────────────────
    _make_figure(
        df, present,
        title=f"Tempo di esecuzione — {csv_path.name}",
        subtitle=subtitle,
        ylabel="tempo di esecuzione (s)",
        specs=[
            ("T_CR",   COLOR_CR,   "Continuous Reasoning"),
            ("T_FULL", COLOR_FULL, "Full Recompute"),
        ],
        out_path=(p := base.parent / f"{base.name}_time.png"),
    )
    saved.append(p)

    # 2 ── Speed-up ──────────────────────────────────────────────────────
    _make_figure(
        df, present,
        title=f"Speed-up (T_FULL / T_CR) — {csv_path.name}",
        subtitle=subtitle,
        ylabel="speed-up",
        specs=[
            ("Speedup", COLOR_CR, "Speed-up"),
        ],
        out_path=(p := base.parent / f"{base.name}_speedup.png"),
    )
    saved.append(p)

    # 3 ── Quality counts ────────────────────────────────────────────────
    _make_figure(
        df, present,
        title=f"Metriche di qualità CR — {csv_path.name}",
        subtitle=subtitle,
        ylabel="conteggio",
        specs=[
            ("N_KO_CR",          COLOR_FULL, "N_KO_CR"),
            ("N_R_CR",           COLOR_CR,   "N_R_CR"),
            ("flows_changed_CR", COLOR_3,    "flows_changed_CR"),
        ],
        out_path=(p := base.parent / f"{base.name}_quality.png"),
        ylim=(0, 250),
    )
    saved.append(p)

    # 4 ── Symmetric difference ──────────────────────────────────────────
    _make_figure(
        df, present,
        title=f"Differenza simmetrica totale — {csv_path.name}",
        subtitle=subtitle,
        ylabel="diff simmetrica totale",
        specs=[
            ("diff_simm_tot_CR",   COLOR_CR,   "CR"),
            ("diff_simm_tot_FULL", COLOR_FULL, "Full Recompute"),
        ],
        out_path=(p := base.parent / f"{base.name}_diffsimm.png"),
    )
    saved.append(p)

    # 5 ── Average latency ───────────────────────────────────────────────
    _make_figure(
        df, present,
        title=f"Latenza media — {csv_path.name}",
        subtitle=subtitle,
        ylabel="latenza media",
        specs=[
            ("avg_latency_CR",   COLOR_CR,   "CR"),
            ("avg_latency_FULL", COLOR_FULL, "Full Recompute"),
        ],
        out_path=(p := base.parent / f"{base.name}_latency.png"),
    )
    saved.append(p)

    return saved


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python plot_results.py <input.csv> [output_prefix]")
        sys.exit(1)

    csv_arg = Path(sys.argv[1])
    if not csv_arg.exists():
        csv_arg = RESULTS_DIR / sys.argv[1]
    out_arg = sys.argv[2] if len(sys.argv) > 2 else None

    plot(str(csv_arg), out_arg)
