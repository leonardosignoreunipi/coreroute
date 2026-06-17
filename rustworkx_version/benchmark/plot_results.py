import json
import sys
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.lines as mlines
from pathlib import Path
from collections import defaultdict
from datetime import datetime

FASCE = [
    (1,   15,  "1–15",   "#2196F3"),
    (16,  50,  "16–50",  "#4CAF50"),
    (51,  150, "51–150", "#FF9800"),
    (151, 9999,"150+",   "#F44336"),
]

def fascia(n):
    for lo, hi, label, color in FASCE:
        if lo <= n <= hi:
            return label, color
    return None, None


# Accept an optional benchmark.json path as first argument; default to sibling file.
benchmark_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "benchmark.json"

with open(benchmark_file) as f:
    data = json.load(f)

# Each run gets its own timestamped subfolder under results/
run_label = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
out_dir = Path(__file__).parent / "results" / run_label
out_dir.mkdir(parents=True, exist_ok=True)
print(f"Saving plots to: {out_dir}")

topologie = ["Erdos-Renyi", "Barabasi-Albert", "Internet (Holme-Kim)"]

# ── Grafici trend (linee per fascia di flussi) ────────────────────────────────
for topo in topologie:
    subset = [d for d in data if d["topologia"] == topo]

    fig, ax = plt.subplots(figsize=(10, 6))

    gruppi: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for d in subset:
        lbl, _ = fascia(d["flussi"])
        if lbl:
            gruppi[lbl][d["nodi_iniziali"]].append(d["tempo_cr_sec"])

    legend_handles = []
    for lo, hi, lbl, color in FASCE:
        if lbl not in gruppi:
            continue
        nodi_dict = gruppi[lbl]
        nodi_sorted = sorted(nodi_dict)

        for n in nodi_sorted:
            ax.scatter(
                [n] * len(nodi_dict[n]),
                nodi_dict[n],
                color=color, alpha=0.65, s=55, zorder=3,
                edgecolors="white", linewidths=0.4,
            )

        medie = [np.mean(nodi_dict[n]) for n in nodi_sorted]
        ax.plot(nodi_sorted, medie, color=color, linewidth=2, zorder=2)

        legend_handles.append(
            mlines.Line2D([], [], color=color, linewidth=2,
                          marker="o", markersize=7, label=f"Flussi {lbl}")
        )

    ax.set_xlabel("Numero di nodi", fontsize=12)
    ax.set_ylabel("Tempo CR (s)", fontsize=12)
    ax.set_title(f"Benchmark — {topo}", fontsize=14)
    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.xaxis.set_major_formatter(plt.ScalarFormatter())
    ax.grid(True, which="both", linestyle="--", alpha=0.35)
    ax.legend(handles=legend_handles, title="Fascia di flussi",
              fontsize=10, title_fontsize=10, loc="upper left")

    plt.tight_layout()
    safe = topo.lower().replace("-", "_").replace(" ", "_")
    out = out_dir / f"benchmark_{safe}.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Salvato: {out}")
    plt.close()


# ── Grafici a colonne (richiedono tempo_non_cr_sec e flussi_ko) ───────────────
bar_data = [d for d in data if "tempo_non_cr_sec" in d and "flussi_ko" in d]

if not bar_data:
    print("ℹ️  Dati per i grafici a colonne non trovati. "
          "Riesegui run_benchmark.py per generarli.")
else:
    for topo in topologie:
        subset = [d for d in bar_data if d["topologia"] == topo]
        if not subset:
            continue

        nodi_unici = sorted(set(d["nodi_iniziali"] for d in subset))

        nocr_means, cr_means = [], []
        total_flow_means, ko_flow_means = [], []
        labels = []

        for n in nodi_unici:
            tests = [d for d in subset if d["nodi_iniziali"] == n]
            if not tests:
                continue
            nocr_means.append(np.mean([d["tempo_non_cr_sec"] for d in tests]))
            cr_means.append(np.mean([d["tempo_cr_sec"] for d in tests]))
            total_flow_means.append(np.mean([d["flussi"] for d in tests]))
            ko_flow_means.append(np.mean([d["flussi_ko"] for d in tests]))
            labels.append(str(n))

        if not labels:
            continue

        x = np.arange(len(labels))
        width = 0.35
        safe = topo.lower().replace("-", "_").replace(" ", "_")

        # ── Bar chart 1: confronto tempi ──────────────────────────────────────
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.bar(x - width / 2, nocr_means, width,
               label="Riallocazione totale (non-CR)", color="#90CAF9", edgecolor="white")
        ax.bar(x + width / 2, cr_means, width,
               label="Continuous Reasoning (solo KO)", color="#EF9A9A", edgecolor="white")

        ax.set_xlabel("Numero di nodi", fontsize=12)
        ax.set_ylabel("Tempo medio (s)", fontsize=12)
        ax.set_title(f"Confronto tempi di riallocazione — {topo}", fontsize=14)
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_yscale("log")
        ax.legend(fontsize=10)
        ax.grid(axis="y", which="both", linestyle="--", alpha=0.4)

        plt.tight_layout()
        out = out_dir / f"benchmark_tempo_bars_{safe}.png"
        plt.savefig(out, dpi=150, bbox_inches="tight")
        print(f"Salvato: {out}")
        plt.close()

        # ── Bar chart 2: confronto flussi riallocati ──────────────────────────
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.bar(x - width / 2, total_flow_means, width,
               label="Flussi totali (riallocazione classica)", color="#90CAF9", edgecolor="white")
        ax.bar(x + width / 2, ko_flow_means, width,
               label="Flussi KO (Continuous Reasoning)", color="#EF9A9A", edgecolor="white")

        ax.set_xlabel("Numero di nodi", fontsize=12)
        ax.set_ylabel("Numero medio di flussi", fontsize=12)
        ax.set_title(f"Confronto flussi riallocati — {topo}", fontsize=14)
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.legend(fontsize=10)
        ax.grid(axis="y", linestyle="--", alpha=0.4)

        plt.tight_layout()
        out = out_dir / f"benchmark_flussi_bars_{safe}.png"
        plt.savefig(out, dpi=150, bbox_inches="tight")
        print(f"Salvato: {out}")
        plt.close()
