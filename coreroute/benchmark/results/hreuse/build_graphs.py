"""
strategy,
topology,
n,
flow_factor,
seed,
init_routed,
pct_mod,
epoch,
num_nodes,
num_edges,
num_flows,
T_CR,
T_FULL,
T_generate_candidates_CR,
T_prolog_strategy_CR,
T_generate_candidates_FULL,
T_prolog_strategy_FULL,
N_KO_CR,
N_R_CR,
N_KO_FULL,
N_R_FULL,
P_KO,
P_R,
Speedup,
n_links_epoch,
frac_rr_degraded,
diff_simm_tot_CR,
flows_changed_CR,
avg_latency_CR,
diff_simm_tot_FULL,
flows_changed_FULL,
avg_latency_FULL,
no_path_count_CR,
no_path_count_FULL,
ok,
error
"""

import os
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

PLOT_DIR = "graphs"
FILE_CSV = "benchmark_biased_k_shortest_path.csv"

# Assicuriamoci che la cartella di destinazione esista
os.makedirs(PLOT_DIR, exist_ok=True)

# 1. Dati aggregati per time1 e time2 (senza epoch)
def get_time_data(df):
    group_cols = ["topology", "n", "flow_factor", "pct_mod"]
    time_metrics = ["T_CR", "T_FULL", "Speedup"]
    return df.groupby(group_cols)[time_metrics].mean().reset_index()

# 2. Dati aggregati per time3 (includendo epoch)
def get_Tepoch_data(df):
    group_cols = ["topology", "n", "pct_mod", "epoch"]
    time_metrics = ["T_CR", "T_FULL", "Speedup"]
    return df.groupby(group_cols)[time_metrics].mean().reset_index()

def get_failed_data(df):
    df["failed_CR"] = ((df["N_KO_CR"] - df["N_R_CR"]) / df["num_flows"]) * 100
    df["failed_FULL"] = ((df["N_KO_FULL"] - df["N_R_FULL"]) / df["num_flows"]) * 100
    
    metrics = ["failed_CR", "failed_FULL"]
    
    group_cols = ["topology", "n", "flow_factor", "pct_mod"]
    df_failed = df.groupby(group_cols)[metrics].mean().reset_index()
    
    return df_failed

def get_avg_latency(df):
    df_tmp = df.copy()
    
    #trasformo da secondi a millisecondi
    df_tmp["avg_latency_CR"] = df_tmp["avg_latency_CR"]*1000
    df_tmp["avg_latency_FULL"] = df_tmp["avg_latency_FULL"]*1000
    
    group_cols = ["topology", "n", "flow_factor", "pct_mod", "epoch"]
    metrics = ["avg_latency_CR", "avg_latency_FULL"]
    
    df_avg_latency = df.groupby(group_cols)[metrics].mean().reset_index()
    
    return df_avg_latency

def get_symmetric_distance(df):
    group_cols = ["topology", "n", "flow_factor", "pct_mod", "epoch"]
    metrics = ["diff_simm_tot_CR", "diff_simm_tot_FULL"]
    df_symmetric_distance = df.groupby(group_cols)[metrics].mean().reset_index()
    return df_symmetric_distance

def get_flows_changed_data(df):
    df_tmp = df.copy()
    
    df_tmp["pct_flows_changed_CR"] = 100 * (df_tmp["flows_changed_CR"] / df_tmp["num_flows"])
    df_tmp["pct_flows_changed_FULL"] = 100 * (df_tmp["flows_changed_FULL"] / df_tmp["num_flows"])
    
    group_cols = ["topology", "n", "flow_factor"]
    metrics = ["pct_flows_changed_CR", "pct_flows_changed_FULL", "flows_changed_CR", "flows_changed_FULL", "T_CR", "T_FULL"]
    
    df_changed = df_tmp.groupby(group_cols)[metrics].mean().reset_index()
    return df_changed

def get_flows_vs_time_data(df_changed):
    keys = ["topology", "n", "flow_factor"]
    
    # 1. Ramo CR
    df_cr = df_changed[keys + ["pct_flows_changed_CR", "flows_changed_CR", "T_CR"]].copy()
    df_cr = df_cr.rename(columns={"flows_changed_CR": "flows_changed", "T_CR": "time", "pct_flows_changed_CR": "pct_flows_changed"})
    df_cr["method"] = "CR"
    
    # 2. Ramo FULL
    df_full = df_changed[keys + ["pct_flows_changed_FULL","flows_changed_FULL", "T_FULL"]].copy()
    df_full = df_full.rename(columns={"flows_changed_FULL": "flows_changed", "T_FULL": "time", "pct_flows_changed_FULL": "pct_flows_changed"})
    df_full["method"] = "From Scratch"
    
    # 3. Unione verticale
    df_combined = pd.concat([df_cr, df_full], ignore_index=True)
    return df_combined

def get_symm_dist_failed(df):
    group = ["topology", "n", "flow_factor", "pct_mod"]
    metrics = ["diff_simm_tot_CR", "diff_simm_tot_FULL", "avg_latency_CR", "avg_latency_FULL"]
    
    #df_tmp = df.groupby(group)[metrics].mean().reset_index()
    df_tmp = df.copy()
    
    df_tmp["avg_latency_CR"] = df_tmp["avg_latency_CR"] * 1000
    df_tmp["avg_latency_FULL"] = df_tmp["avg_latency_FULL"] * 1000
    
    df_cr = df_tmp.copy()
    df_cr = df_cr.rename(columns={"diff_simm_tot_CR": "diff_simm", "avg_latency_CR": "avg_latency"})
    df_cr["method"] = "CR"
    
    df_full = df_tmp.copy()
    df_full = df_full.rename(columns={"diff_simm_tot_FULL": "diff_simm", "avg_latency_FULL": "avg_latency"})
    df_full["method"] = "From Scratch"
    
    df_combined = pd.concat([df_cr, df_full], ignore_index=True)
    
    return df_combined

def get_ko_vs_changed_data(df):
    df_tmp = df.copy()
    df_tmp["pct_ko_CR"] = 100 * df_tmp["N_KO_CR"] / df_tmp["num_flows"]
    df_tmp["pct_changed_CR"] = 100 * df_tmp["flows_changed_CR"] / df_tmp["num_flows"]
    df_tmp["pct_changed_FULL"] = 100 * df_tmp["flows_changed_FULL"] / df_tmp["num_flows"]
    group_cols = ["topology", "n", "flow_factor", "pct_mod"]
    metrics = ["pct_ko_CR", "pct_changed_CR", "pct_changed_FULL"]
    return df_tmp.groupby(group_cols)[metrics].mean().reset_index()

def get_ko_time(df):
    df_tmp = df.copy()
    df_tmp["pct_flows_ko"] = 100 * (df_tmp["N_KO_CR"] / df_tmp["num_flows"])
    
    group = ["topology", "n", "flow_factor", "pct_mod"]
    metrics = ["pct_flows_ko", "T_CR", "T_FULL"]
        
    
    df_tmp = df_tmp.groupby(group)[metrics].mean().reset_index()
    
    
    df_cr = df_tmp.copy()
    df_cr = df_cr.rename(columns={"T_CR": "time"})
    df_cr["method"] = "CR"
    
    df_full = df_tmp.copy()
    df_full = df_full.rename(columns={"T_FULL": "time"})
    df_full["method"] = "FULL"
    
    df_combined = pd.concat([df_cr, df_full], ignore_index=True)
    
    return df_combined

df = pd.read_csv(FILE_CSV)
df = df[df["ok"]]
df_time = get_time_data(df)
df_epoch = get_Tepoch_data(df)
df_failed = get_failed_data(df)
df_avg_latency = get_avg_latency(df)
df_symmetric_distance = get_symmetric_distance(df)
df_changed = get_flows_changed_data(df)
df_changed_time = get_flows_vs_time_data(df_changed)
df_symm_failed = get_symm_dist_failed(df)
df_ko_changed = get_ko_vs_changed_data(df)
df_ko_time = get_ko_time(df)

def time1():
    g = sns.relplot(
        data=df_time,
        x="n",
        y="Speedup",
        hue="flow_factor",
        col="topology", 
        row="pct_mod",
        kind="line",
        markers=True,
        height=3,
        palette="colorblind",
        aspect=1.2
    )
    g.fig.subplots_adjust(top=0.9)
    g.fig.suptitle("Speedup vs Dimensione Rete (n)", fontsize=14)
    g.set_axis_labels("Dimensione rete (n)", "Speedup")
    g.set(xticks=sorted(df_time["n"].unique()))
    
    # Salvataggio nella cartella PLOT_DIR
    g.set_axis_labels(x_var="nodes",y_var="speedup")
    g.savefig(os.path.join(PLOT_DIR, "speedupplot_nodes.png"), dpi=300)


def time2():
    g = sns.relplot(
        data=df_time,
        x="flow_factor",
        y="Speedup",
        hue="pct_mod",
        col="topology", 
        row="n",
        kind="line",
        markers=True,
        height=3,
        palette="colorblind",
        aspect=1.2
    )
    g.figure.subplots_adjust(top=0.9)
    g.figure.suptitle("Speedup vs Flow Factor", fontsize=14)
    g.set_axis_labels("flow factor", "speedup")
    g.set(xticks=sorted(df_time["flow_factor"].unique()))
    
    # Salvataggio nella cartella PLOT_DIR
    g.savefig(os.path.join(PLOT_DIR, "speedupplot_flowFactor.png"), dpi=300)


def speedup_vs_epoch():
    g = sns.relplot(
        data=df_epoch,         
        x="epoch",
        y="Speedup",                
        hue="pct_mod",
        col="topology", 
        row="n",
        kind="line",
        markers=True,
        height=3,
        palette="colorblind",
        aspect=1.2, 
        errorbar="sd"
    )
    g.figure.subplots_adjust(top=0.9)
    g.figure.suptitle("Speedup vs Epoch", fontsize=14)
    g.set_axis_labels("epoch", "speedup")
    g.set(xticks=[1, 5, 10, 15, 20], xlim=(1, 20))
    
    # Salvataggio nella cartella PLOT_DIR
    g.savefig(os.path.join(PLOT_DIR, "speedupplot_epoch.png"), dpi=300)

def time4():
    df_melted = df_time.melt(
        id_vars=["topology", "n", "flow_factor", "pct_mod"],   
        value_vars=["T_CR", "T_FULL"],                        
        var_name="method", #nuova colonna che conterrà T_CR/T_FULL.
        value_name="time" #nuova colonna che contiene il tempo.
    )
    g = sns.relplot(
        data=df_melted,         
        x="n",
        y="time",                
        hue="method",
        style="pct_mod",
        col="topology", 
        row="flow_factor",
        kind="line",
        markers=True,
        height=3,
        palette="colorblind",
        aspect=1.2
    )
    
    g.set_axis_labels(x_var="nodes", y_var="time (s)")
    g.set(xticks=sorted(df["n"].unique()))
    g.savefig(os.path.join(PLOT_DIR, "timeplot_nodes.png"), dpi=300)
    
def time5():
    df_melted = df_time.melt(
        id_vars=["topology", "n", "flow_factor", "pct_mod"],   
        value_vars=["T_CR", "T_FULL"],                        
        var_name="method", #nuova colonna che conterrà T_CR/T_FULL.
        value_name="time" #nuova colonna che contiene il tempo.
    )
    
    g = sns.relplot(
        data=df_melted,         
        x="flow_factor",
        y="time",                
        hue="method",
        style="pct_mod",
        col="topology", 
        row="n",
        kind="line",
        markers=True,
        height=3,
        palette="colorblind",
        aspect=1.2
    )
    g.set_axis_labels(x_var="flow_factor", y_var="time (s)")
    g.set(xticks=sorted(df["flow_factor"].unique()))
    g.savefig(os.path.join(PLOT_DIR, "timeplot_flowfactor.png"), dpi=300)
    
def lineplot_reroutefailed():
    df_melted = df_failed.melt(
        id_vars=["topology", "n", "flow_factor", "pct_mod"],
        value_vars=["failed_CR", "failed_FULL"],
        var_name="method",
        value_name="num_failed"
        )

    df_filtrato = df_melted[df_melted["pct_mod"].isin([0.1, 0.3, 0.5])].copy()

    df_filtrato["method"] = df_filtrato["method"].replace({
        "failed_CR": "CR",
        "failed_FULL": "From Scratch"
    })
    df_filtrato["pct_mod"] = df_filtrato["pct_mod"].map(lambda p: f"{int(p * 100)}%")
    df_filtrato = df_filtrato.rename(columns={"method": "Method", "pct_mod": "Perturbation"})

    g = sns.relplot(
        data=df_filtrato,
        x="flow_factor",
        y="num_failed",
        hue="Method",
        col="topology",
        row="n",
        style="Perturbation",
        kind="line",
        markers=True,
        height=3,
        palette="colorblind",
        errorbar=None,
        facet_kws={'sharex': False},
        aspect=1.2
    )

    g.set_axis_labels(x_var="Flow Factor", y_var="(%) Flows Left Broken")
    g.set(xticks=sorted(df["flow_factor"].unique()))
    g.savefig(os.path.join(PLOT_DIR, "failed_numflows.png"), dpi=300)
    
def avg_latency():
    df_melted = df_avg_latency.melt(
        id_vars=["topology", "n", "flow_factor", "pct_mod"],   
        value_vars=["avg_latency_CR", "avg_latency_FULL"],                        
        var_name="method", #nuova colonna che conterrà avg_latency_CR/avg_latency_FULL.
        value_name="time" #nuova colonna che contiene il tempo.
        )
    df_melted["method"] = df_melted["method"].replace({
        "avg_latency_CR": "CR",
        "avg_latency_FULL": "FULL"
    })
    g = sns.relplot(
            data=df_melted,         
            x="n",
            y="time",                
            hue="method",
            col="topology", 
            row="flow_factor",
            kind="line",
            markers=True,
            height=3,
            palette="colorblind",
            errorbar=None,
            facet_kws={'sharex': False},
            aspect=1.2
        )
    
    g.set(xticks=sorted(df["n"].unique()))
    g.set_axis_labels(x_var="nodes", y_var="time (ms)")
    g.savefig(os.path.join(PLOT_DIR, "avg_latency.png"), dpi=300)

def symmetric_distance():
    df_melted = df_symmetric_distance.melt(
            id_vars=["topology", "n", "flow_factor", "pct_mod"],   
            value_vars=["diff_simm_tot_CR", "diff_simm_tot_FULL"],                        
            var_name="method", #nuova colonna che conterrà avg_latency_CR/avg_latency_FULL.
            value_name="disruption" #nuova colonna che contiene il tempo.
            )
    
    g = sns.relplot(
                data=df_melted,         
                x="n",
                y="disruption",                
                hue="method",
                col="topology", 
                row="flow_factor",
                kind="line",
                markers=True,
                height=3,
                palette="colorblind",
                errorbar=None,
                facet_kws={'sharex': False},
                aspect=1.2
            )
    
    g.set_axis_labels(x_var="nodes", y_var="symm. distance")
    g.set(xticks=sorted(df["n"].unique()))
    g.savefig(os.path.join(PLOT_DIR, "symmetric_distance.png"), dpi=300)

def flowchanged_vs_nodes():
    # 1. Melt per avere T_CR e T_FULL su una colonna 'method'
    df_melted = df_changed.melt(
        id_vars=["topology", "n", "flow_factor", "pct_mod"],
        value_vars=["flows_changed_CR", "flows_changed_FULL"],
        var_name="method",
        value_name="flows_changed"
    )
    
    # 2. Relplot a griglia
    g = sns.relplot(
        data=df_melted,
        x="n",
        y="flows_changed",
        hue="method",
        col="topology",
        row="flow_factor",
        kind="line",
        markers=True,
        height=3,
        palette="colorblind",
        errorbar=None,
        aspect=1.2
    )
    
    # 3. Personalizzazioni grafiche e assi
    g.set(ylim=(0, None))  # Parte da 0
    g.figure.subplots_adjust(top=0.9)
    g.set_axis_labels("Nodes", "Flow path changed")
    g.set(xticks=sorted(df["n"].unique()))
    
    # 4. Salvataggio
    g.savefig(os.path.join(PLOT_DIR, "flows_changed_nodes.png"), dpi=300)
    
def flow_changed_time_execution():
    g = sns.relplot(
        data=df_changed_time,
        x="pct_flows_changed",
        y="time",
        hue="method",
        style="flow_factor",
        row="n",
        col="topology",
        kind="scatter",
        markers=True,
        height=3,
        palette="colorblind",
        aspect=1.2
    )
    
    g.set_axis_labels("(%) path flow changed", "Time (s)")
    g.savefig(os.path.join(PLOT_DIR, "flows_changed_time.png"), dpi=300)
    
def flow_changed_time_denso():
    def get_flows_vs_time_data_raw(df):
            """
            Prepara i dati senza fare la media, mantenendo tutti i singoli punti (epoche/seed)
            per visualizzare la densità delle distribuzioni.
            """
            df_tmp = df.copy()
        
            # Calcolo delle percentuali sui dati non aggregati
            df_tmp["pct_flows_changed_CR"] = 100 * (df_tmp["flows_changed_CR"] / df_tmp["num_flows"])
            df_tmp["pct_flows_changed_FULL"] = 100 * (df_tmp["flows_changed_FULL"] / df_tmp["num_flows"])
        
            cols = ["topology", "n", "flow_factor", "pct_mod", "epoch"]
        
            # 1. Ramo CR
            df_cr = df_tmp[cols + ["pct_flows_changed_CR", "flows_changed_CR", "T_CR"]].copy()
            df_cr = df_cr.rename(columns={
                "flows_changed_CR": "flows_changed",
                "T_CR": "time",
                "pct_flows_changed_CR": "pct_flows_changed"
            })
            df_cr["method"] = "CR"
        
            # 2. Ramo FULL
            df_full = df_tmp[cols + ["pct_flows_changed_FULL", "flows_changed_FULL", "T_FULL"]].copy()
            df_full = df_full.rename(columns={
                "flows_changed_FULL": "flows_changed",
                "T_FULL": "time",
                "pct_flows_changed_FULL": "pct_flows_changed"
            })
            df_full["method"] = "From Scratch"
        
            return pd.concat([df_cr, df_full], ignore_index=True)
    data = get_flows_vs_time_data_raw(df)
    data = data[data["flow_factor"].isin([1.0])]
    g = sns.relplot(
                data=data,
                x="pct_flows_changed",
                y="time",
                hue="method",
                row="n",
                col="topology",
                kind="scatter",
                markers=True,
                height=3,
                palette="colorblind",
                aspect=1.2
            )
            
    g.set_axis_labels("(%) path flow changed", "Time (s)")
    g.savefig(os.path.join(PLOT_DIR, "flows_changed_time_denso.png"), dpi=300)
    
def symm_dist_delay():
    g = sns.relplot(
        data=df_symm_failed,
        x="avg_latency",
        y="diff_simm",
        hue="method",
        row="n",
        col="topology",
        kind="scatter",
        markers=True,
        height=3,
        palette="colorblind",
        aspect=1.2
    )
    
    g.set_axis_labels(x_var="Path delay (ms)",y_var="Symm. distance")
    
    g.savefig(os.path.join(PLOT_DIR, "symm_dist_delay.png"), dpi=300)    

def ko_vs_changed():
    df_melted = df_ko_changed.melt(
        id_vars=["topology", "n", "flow_factor", "pct_mod"],
        value_vars=["pct_ko_CR", "pct_changed_CR", "pct_changed_FULL"],
        var_name="serie", value_name="pct_flussi",
    )
    df_melted["serie"] = df_melted["serie"].replace({
        "pct_ko_CR": "KO (CR)",
        "pct_changed_CR": "cambiati (CR)",
        "pct_changed_FULL": "cambiati (From Scratch)",
    })
    
    
    df_filtrato = df_melted[df_melted["n"].isin([250, 1000])]
    
    g = sns.relplot(
        data=df_filtrato, 
        x="pct_mod", 
        y="pct_flussi", 
        hue="serie", 
        style="n",
        col="topology", 
        row="flow_factor", 
        kind="line", 
        markers=True,
        height=3, 
        palette="colorblind", 
        errorbar=None, 
        aspect=1.2
    )
    g.set_axis_labels("(%) Perturbation", "(%) Flow path changed")
    g.set(xticks=sorted(df["pct_mod"].unique()))
    g.savefig(os.path.join(PLOT_DIR, "ko_vs_changed.png"), dpi=300)
#AUTOGENERATA DA CLAUDIA
def heatmap_speedup():
    """
    Genera una griglia di heatmap per lo Speedup (T_FULL / T_CR)
    con righe = pct_mod e colonne = topology.
    """
    topologies = sorted(df["topology"].unique())
    pct_mods = sorted(df["pct_mod"].unique())

    # Scala di colori globale per lo Speedup
    vmin = df["Speedup"].min()
    vmax = df["Speedup"].max()

    nrows = len(pct_mods)
    ncols = len(topologies)

    fig, axes = plt.subplots(
        nrows=nrows,
        ncols=ncols,
        figsize=(4.2 * ncols, 3.5 * nrows),
        squeeze=False
    )

    for row_idx, pct in enumerate(pct_mods):
        for col_idx, topo in enumerate(topologies):
            ax = axes[row_idx, col_idx]
            
            # Filtra per la specifica topologia e pct_mod
            sub_df = df[(df["topology"] == topo) & (df["pct_mod"] == pct)]
            
            # Calcola la matrice pivot dello Speedup
            piv_speedup = sub_df.groupby(["flow_factor", "n"])["Speedup"].mean().unstack()

            # Mostra la barra laterale dei colori solo sull'ultima colonna a destra
            is_last_col = (col_idx == ncols - 1)

            sns.heatmap(
                piv_speedup,
                ax=ax,
                vmin=vmin,
                vmax=vmax,
                cmap="Blues",
                annot=True,
                fmt=".1f",       # 1 cifra decimale (es. 25.9)
                cbar=is_last_col,
                linewidths=0.5,
                linecolor="white",
                cbar_kws={"label": "Speedup"} if is_last_col else None,
            )

            # Titolo del singolo grafico
            ax.set_title(f"{topo.upper()} | Perturbation: {pct}", fontsize=11)
            
            # Mostra label 'Nodes' solo nell'ultima riga in basso
            ax.set_xlabel("Nodes" if row_idx == nrows - 1 else "")
            
            # Mostra label 'Flow factor' solo nella prima colonna a sinistra
            ax.set_ylabel(f"Flow factor" if col_idx == 0 else "")
            
            ax.invert_yaxis()

    fig.suptitle("Speedup Heatmap Grid", fontsize=14, y=0.99)
    fig.tight_layout(rect=[0, 0, 1, 0.98])
    
    # Salvataggio
    fig.savefig(os.path.join(PLOT_DIR, "heatmap_speedup_grid.png"), dpi=300)
    plt.close(fig)

def ko_time():
    df_tmp = get_ko_time(df)
    
    g = sns.relplot(
        data=df_tmp, 
        x="pct_flows_ko", 
        y="time", 
        hue="method",
        col="topology", 
        row="flow_factor", 
        kind="line", 
        markers=True,
        height=3, 
        palette="colorblind", 
        aspect=1.2
    )
    
    g.set_axis_labels("(%) Flows ko","Time (s)")
    g.savefig("ko_time.png", dpi=300)
    
    

def main():
    sns.set_theme(style="darkgrid")
    
    heatmap_speedup()
    flow_changed_time_denso()
    symm_dist_delay()
    lineplot_reroutefailed()
    speedup_vs_epoch()
    flow_changed_time_execution()
    ko_vs_changed()
    
    # Mostra a video tutte e tre le figure
    #plt.show()

if __name__ == "__main__":
    main()