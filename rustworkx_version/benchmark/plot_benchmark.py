#!/usr/bin/env python3
"""
Aggregazione e visualizzazione di benchmark_cr.csv.

Schema colonne (in ordine nel CSV):
    topology      : er | ba | iaag
    n             : numero di router
    flow_factor   : fattore di flusso
    seed          : seed della ripetizione
    pct_mod       : livello di perturbazione
    num_nodes     : router + host
    num_edges     : numero di archi
    T_CR          : tempo continuous reasoning
    T_FULL        : tempo per calcolare tutti i flussi
    N_KO          : numero di flussi andati KO
    N_R           : numero di flussi reroutati (N_R <= N_KO)
    P_KO          : N_KO / #flussi
    P_R           : N_R / #flussi
    speedup       : T_FULL / T_CR
    n_link_mod    : numero di link modificati

Aggrega sulle 10 ripetizioni per ogni combinazione
(topology, pct_mod, flow_factor, num_nodes) calcolando media, std e
intervallo di confidenza al 95%, poi produce barplot e line/scatter plot
per tre metriche:
    1. Reasoning time (T_CR) vs num_nodes
    2. Flussi reroutati (N_R) vs num_nodes
    3. Speedup            vs num_nodes

Ogni subplot della griglia corrisponde a una coppia (topology, pct_mod);
dentro ogni subplot una linea / gruppo di barre per ogni flow_factor.
Le barre d'errore sono gli IC al 95%.
"""

import argparse

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

sns.set_theme(style="whitegrid", context="talk")

# Chiavi di raggruppamento e metriche da plottare
GROUP_KEYS = ["topology", "pct_mod", "flow_factor", "num_nodes"]
METRICS = [
    ("T_CR",    "Reasoning Time (s)", "reasoning_time"),
    ("N_R",     "Rerouted Flows",     "rerouted_flows"),
    ("Speedup", "Speedup",            "speedup"),
]


def aggregate(df):
    """Media, std, count e IC 95% (1.96*SEM) per ogni combinazione."""
    metric_cols = [m for m, _, _ in METRICS]

    def ci95(s):
        s = s.dropna()
        n = len(s)
        if n < 2:
            return 0.0
        return 1.96 * s.std(ddof=1) / np.sqrt(n)

    agg = df.groupby(GROUP_KEYS, observed=True)[metric_cols].agg(
        ["mean", "std", "count", ci95]
    )
    agg.columns = [f"{m}_{stat}" for m, stat in agg.columns]
    return agg.reset_index()


def lineplot(df, metric, ylabel, outfile):
    """Line/scatter con IC 95%, faccette per (topology, pct_mod)."""
    g = sns.relplot(
        data=df,
        x="num_nodes",
        y=metric,
        hue="flow_factor",
        col="topology",
        row="pct_mod",
        kind="line",
        marker="o",
        errorbar=("ci", 95),
        palette="viridis",
        facet_kws={"sharey": False, "margin_titles": True},
        height=4,
        aspect=1.2,
    )
    g.set_axis_labels("Number of nodes", ylabel)
    g.set_titles(col_template="{col_name}", row_template="pct_mod={row_name}")
    if g.legend is not None:
        g.legend.set_title("flow_factor")
    g.figure.suptitle(f"{ylabel} vs Number of Nodes", y=1.02, fontsize=18)
    g.savefig(outfile, dpi=150, bbox_inches="tight")
    plt.close(g.figure)
    print(f"  scritto {outfile}")


def barplot(df, metric, ylabel, outfile):
    """Barplot con IC 95%, faccette per (topology, pct_mod)."""
    g = sns.catplot(
        data=df,
        x="num_nodes",
        y=metric,
        hue="flow_factor",
        col="topology",
        row="pct_mod",
        kind="bar",
        errorbar=("ci", 95),
        capsize=0.15,
        err_kws={"linewidth": 1.2},
        palette="viridis",
        height=4,
        aspect=1.2,
        sharey=False,
    )
    g.set_axis_labels("Number of nodes", ylabel)
    g.set_titles(col_template="{col_name}", row_template="pct_mod={row_name}")
    if g.legend is not None:
        g.legend.set_title("flow_factor")
    g.figure.suptitle(f"{ylabel} vs Number of Nodes", y=1.02, fontsize=18)
    g.savefig(outfile, dpi=150, bbox_inches="tight")
    plt.close(g.figure)
    print(f"  scritto {outfile}")


def main():
    p = argparse.ArgumentParser(description="Aggrega e plotta benchmark_cr_severe.csv")
    p.add_argument("--csv", default="results/benchmark_cr_severe.csv")
    p.add_argument("--outdir", default="./results")
    args = p.parse_args()

    df = pd.read_csv(args.csv)

    agg = aggregate(df)
    agg_path = f"{args.outdir}/benchmark_cr_aggregated.csv"
    agg.to_csv(agg_path, index=False)
    print(f"Tabella aggregata ({len(agg)} righe) -> {agg_path}")

    print("Genero i plot:")
    for metric, ylabel, tag in METRICS:
        lineplot(df, metric, ylabel, f"{args.outdir}/line_{tag}_severe.png")
        barplot(df, metric, ylabel, f"{args.outdir}/bar_{tag}_severe.png")

    print("Fatto.")


if __name__ == "__main__":
    main()