from pathlib import Path

import pandas as pd
import seaborn as sns

import matplotlib
matplotlib.use("Agg")            # salva su file, non apre finestre
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Patch

HERE = Path(__file__).parent
CSV_PATH = HERE / "data.csv"
OUT_DIR = HERE / "graphs"
OUT_DIR.mkdir(exist_ok=True)

# --------------------------------------------------------------------------- identita' delle strategie

EURISTICHE = ["biased_k_shortest_path", "biased_k_shortest_path_latency", "latency_biased_paths"]
OTTIMO = "exhaustive_optimal"
STRATEGIE = EURISTICHE + [OTTIMO]

# Un solo punto in cui una strategia e' legata al suo stile visivo (colore
# Okabe-Ito, colorblind-safe, + linestyle + marker): ogni funzione plot_*
# pesca da qui, cosi' la stessa strategia e' sempre disegnata allo stesso
# modo in tutte le figure del file. L'ottimo esaustivo si distingue per
# colore (arancio) e marcatore (rombo), linea piena come le euristiche.
STRATEGY_STYLES: dict[str, dict] = {
    "biased_k_shortest_path":         dict(color="#0072B2", linestyle="-",  marker="o", label="biased_k_shortest_path"),
    "biased_k_shortest_path_latency": dict(color="#E69F00", linestyle="-",  marker="s", label="biased_k_shortest_path_latency"),
    "latency_biased_paths":           dict(color="#009E73", linestyle="-",  marker="^", label="latency_biased_paths"),
    "exhaustive_optimal":             dict(color="#D55E00", linestyle="-",  marker="D", label="exhaustive_optimal"),
}
COLORI = {s: st["color"] for s, st in STRATEGY_STYLES.items()}   # scorciatoia per il solo colore

# nome completo per legende ed etichette -- come STRATEGY_STYLES, un solo punto
# cosi' ogni figura usa lo stesso nome per la stessa strategia
NOME_STRATEGIA = {
    "biased_k_shortest_path": "Reuse",
    "biased_k_shortest_path_latency": "ReuseDelay",
    "latency_biased_paths": "Delay",
    "exhaustive_optimal": "Exhaustive",
}

NOME_TOPO = {"iaag": "IAAG", "er": "ER", "ba": "BA"}
TOPOLOGIE_ORDINATE = ["iaag", "er", "ba"]   # per numero di archi crescente

INK = "#1A1A1A"
INK_SOFT = "#5A5A5A"
GRIGIO = "#CFCFCF"


# =================================================================== caricamento dati

def carica_dati() -> pd.DataFrame:
    return pd.read_csv(CSV_PATH)


# =================================================================== utility condivise (non statistiche di dominio)

def _colore_testo(sfondo_hex: str) -> str:
    """Bianco o nero: qualunque resti piu' leggibile sopra quel colore di sfondo."""
    r, g, b = (int(sfondo_hex[i:i + 2], 16) / 255 for i in (1, 3, 5))
    canale = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    luminanza = 0.2126 * canale(r) + 0.7152 * canale(g) + 0.0722 * canale(b)
    return "white" if luminanza < 0.35 else INK


def _pulisci_assi(ax: Axes, *, asse_griglia: str = "y", which: str = "major",
                   alpha: float = 0.25, spine_visibili: tuple[str, ...] = ("bottom", "left")) -> None:
    """Stile comune a tutte le figure del modulo: griglia leggera dietro ai
    dati, bordi ridotti alle sole spine elencate in spine_visibili."""
    ax.grid(True, axis=asse_griglia, which=which, alpha=alpha)
    ax.set_axisbelow(True)
    for lato in ("top", "right", "bottom", "left"):
        if lato not in spine_visibili:
            ax.spines[lato].set_visible(False)


def _patch_legenda(strategie: list[str]) -> list[Patch]:
    """Handle di legenda a blocco di colore (per grafici a barre), nello
    stesso ordine e con lo stesso colore di STRATEGY_STYLES."""
    return [Patch(facecolor=COLORI[s], label=STRATEGY_STYLES[s]["label"]) for s in strategie]


def _salva(fig: Figure, nome_file: str, dpi: int = 170) -> None:
    out = OUT_DIR / nome_file
    fig.savefig(out, dpi=dpi, facecolor="white")
    plt.close(fig)
    print(f"salvato: {out}")


# =================================================================== G2: accuratezza a epoca 0

def prepara_dati_accuratezza(df: pd.DataFrame) -> pd.DataFrame:
    """Confronto a EPOCA 0 fra ogni euristica e l'ottimo esaustivo sulla
    terna (flussi non riparati, distanza simmetrica, latenza media): stessa
    terna esatta = stessa qualita' di riparazione su quella cella.

    Una cella = una riconfigurazione (topologia, n, num_flussi, seed,
    pct_mod) a epoca 0. Tenute solo le celle con tutte e 4 le strategie
    presenti e completate con successo, e in cui l'ottimo aveva almeno un
    flusso da riparare (altrimenti la terna e' banale: nessuno ha nulla da
    fare, tutti "vincono" per costruzione).

    Ritorna un DataFrame tidy, una riga per (cella, euristica): colonne
    'topology' (raddoppiata con topology="tutte" per il gruppo aggregato),
    'cella_id', 'strategy', 'coincide' (bool) e 'migliore' (bool: l'euristica
    avrebbe una terna migliore dell'ottimo -- a stato identico non dovrebbe
    mai capitare, serve solo come controllo di integrita').
    """
    chiavi_cella = ["topology", "n", "num_flows", "seed", "pct_mod"]
    e0 = df[(df["epoch"] == 0) & (df["ok"])]

    piv = e0.pivot_table(index=chiavi_cella, columns="strategy",
                          values=["N_KO", "N_RR", "diff_simm_tot", "avg_latency"])
    piv = piv.dropna()                            # solo celle con tutte e 4 le strategie
    piv = piv[piv[("N_KO", OTTIMO)] > 0]           # solo celle con lavoro da fare

    frr = piv["N_KO"] - piv["N_RR"]
    ds = piv["diff_simm_tot"].round(6)
    lat = piv["avg_latency"].round(9)

    righe = []
    for s in EURISTICHE:
        coincide = (frr[s] == frr[OTTIMO]) & (ds[s] == ds[OTTIMO]) & (lat[s] == lat[OTTIMO])
        # confronto lessicografico della terna (frr, ds, lat), stesso ordine
        # di priorita' usato per definire "coincide"
        migliore = ((frr[s] < frr[OTTIMO]) |
                    ((frr[s] == frr[OTTIMO]) & (ds[s] < ds[OTTIMO])) |
                    ((frr[s] == frr[OTTIMO]) & (ds[s] == ds[OTTIMO]) & (lat[s] < lat[OTTIMO])))
        righe.append(pd.DataFrame({
            "topology": piv.index.get_level_values("topology"),
            "cella_id": range(len(piv)),
            "strategy": s,
            "coincide": coincide.to_numpy(),
            "migliore": migliore.to_numpy(),
        }))
    lungo = pd.concat(righe, ignore_index=True)

    # ogni riga conta anche per il gruppo aggregato "tutte" (una cella pesa
    # sia sulla sua topologia sia sul totale)
    lungo_tutte = lungo.copy()
    lungo_tutte["topology"] = "tutte"
    return pd.concat([lungo, lungo_tutte], ignore_index=True)


def plot_accuratezza(dati: pd.DataFrame) -> None:
    """Barre impilate al 100%: quota di celle in cui ogni euristica coincide
    esattamente con l'ottimo, un gruppo di barre per topologia + il totale."""
    GRUPPI = [*TOPOLOGIE_ORDINATE, "tutte"]
    ETICHETTE = {**NOME_TOPO, "tutte": "ALL"}
    dati = dati.assign(pct=dati["coincide"] * 100)

    fig, ax = plt.subplots(figsize=(12.5, 6.6))
    fig.patch.set_facecolor("white")
    sns.barplot(data=dati, x="topology", y="pct", hue="strategy", order=GRUPPI,
                hue_order=EURISTICHE, palette=COLORI, errorbar=("ci", 95),
                capsize=0.1, err_kws=dict(color=INK, linewidth=1.2), legend=False, ax=ax)

    for cont, strat in zip(ax.containers, EURISTICHE):
        etichette = ["100%" if v.get_height() >= 99.95 else f"{v.get_height():.0f}%" for v in cont]
        ax.bar_label(cont, labels=etichette, padding=-36, fontsize=16,
                     fontweight="bold", color=_colore_testo(COLORI[strat]))

    for x, gruppo in zip(ax.get_xticks(), GRUPPI):
        ax.text(x, -6, ETICHETTE[gruppo], ha="center", va="top", fontsize=16, color=INK)

    ax.set_ylim(0, 108)
    ax.set_xticks([])
    ax.set_xlabel("")   # sns imposta "topology" come xlabel di default, la copriamo con le etichette sotto
    ax.set_ylabel("Share of repairs matching optimal (%)", fontsize=16)
    ax.tick_params(axis="y", labelsize=16)
    _pulisci_assi(ax, spine_visibili=("left",))

    legenda = [Patch(facecolor=COLORI[s], label=NOME_STRATEGIA[s]) for s in EURISTICHE]
    ax.legend(handles=legenda, frameon=False, fontsize=16, loc="upper center",
              bbox_to_anchor=(0.5, 1.08), ncol=3)

    fig.tight_layout(rect=[0, 0.03, 1, 0.95])
    _salva(fig, "accuratezza.png")


# =================================================================== G6: griglia topologia x num_flows

def prepara_dati_tempo_griglia(df: pd.DataFrame) -> pd.DataFrame:
    """T_CR medio per ogni (strategia, topologia, num_flows, n), su tutti i
    pct_mod/seed/epoche che condividono questi 4 valori."""
    valide = df[df["ok"]]
    return (valide.groupby(["strategy", "topology", "num_flows", "n"])["T_CR"]
                  .mean().rename("tempo_medio").reset_index())


def plot_tempo_griglia(dati: pd.DataFrame) -> None:
    """Griglia 4x3: una riga per num_flows, una colonna per topologia, una
    linea per strategia. 12 celle, tutte le combinazioni possibili di questi
    due parametri (la topologia sposta il tempo molto di piu' di pct_mod,
    per questo e' lei ad avere un asse della griglia).

    Asse Y in scala log, condiviso per RIGA (sharey="row"): i pannelli con
    lo stesso num_flows condividono la scala, cosi' si confrontano a colpo
    d'occhio fra topologie diverse; righe con num_flows diverso possono
    avere scale diverse, dato che il tempo cresce parecchio con i flussi.
    """
    NODI = [20, 25, 30, 35, 40]
    NUM_FLOWS = sorted(dati["num_flows"].unique())

    fig, assi = plt.subplots(len(NUM_FLOWS), len(TOPOLOGIE_ORDINATE), figsize=(12, 14),
                              sharex=True, sharey="row")
    fig.patch.set_facecolor("white")

    for riga, num_flows in enumerate(NUM_FLOWS):
        for colonna, topo in enumerate(TOPOLOGIE_ORDINATE):
            ax = assi[riga][colonna]
            for strat in STRATEGIE:
                stile = STRATEGY_STYLES[strat]
                sotto = (dati[(dati["strategy"] == strat) & (dati["topology"] == topo) & (dati["num_flows"] == num_flows)]
                         .set_index("n").reindex(NODI))
                ax.plot(NODI, sotto["tempo_medio"], linestyle=stile["linestyle"], marker=stile["marker"],
                        color=stile["color"], lw=1.8, ms=4.5, label=NOME_STRATEGIA[strat])

            ax.set_yscale("linear")     # esplicito, come richiesto
            ax.set_xticks(NODI)      # altrimenti matplotlib sceglie tick decimali (22.5, 27.5, ...)
            ax.set_title(NOME_TOPO[topo], fontsize=16, color=INK)   # ripetuto su ogni riga: una riga ritagliata da sola resta etichettata
            _pulisci_assi(ax, alpha=0.2)
            ax.tick_params(axis="both", labelsize=16)
            if riga == len(NUM_FLOWS) - 1 and colonna == len(TOPOLOGIE_ORDINATE) // 2:
                ax.set_xlabel("Infrastructure Size", fontsize=16)
            if colonna == 0:
                ax.set_ylabel("Execution Time [s]", fontsize=16)

        # limite superiore uniforme per riga: 10^2 deve comparire come tick
        # in tutte le righe, non solo in quelle (flussi=5,6) dove i dati
        # arrivano naturalmente cosi' in alto
        assi[riga][0].set_ylim(top=100)

        # legenda per riga, nel pannello IAAG (colonna 0): le curve restano
        # piatte vicino allo zero per l'intera riga, quindi l'angolo in alto
        # a sinistra e' sempre libero da dati
        handles, labels = assi[riga][0].get_legend_handles_labels()
        assi[riga][0].legend(handles, labels, frameon=False, fontsize=16, loc="upper left")

    fig.tight_layout()
    _salva(fig, "tempo_griglia_topologia_flussi.png")


# G8: tabella divario euristiche vs sub-optimal

# unita' statistica: la SEQUENZA (topologia, n, num_flussi, seed, pct_mod), non
# la singola epoca -- lo stato di routing di un'epoca e' l'input di quella dopo
CHIAVI_SEQUENZA = ["topology", "n", "num_flows", "seed", "pct_mod"]


def _sequenze_complete(df: pd.DataFrame) -> pd.DataFrame:
    """Aggrega le epoche valide a livello di sequenza (10 riparazioni consecutive),
    tenendo solo le sequenze complete (10 epoche, 4 strategie) in cui l'ottimo
    aveva almeno un flusso da ricollocare. costo_riconfig e' un rapporto PER
    SEQUENZA (diff_simm_tot / N_RR), non dalla somma grezza: isola il costo di
    UNA riparazione dalla frequenza con cui e' stata necessaria, altrimenti una
    strategia che per puro caso ripara meno flussi sembra piu' economica senza
    esserlo davvero.
    """
    valide = df[df["ok"]]
    per_seq = (valide.groupby(CHIAVI_SEQUENZA + ["strategy"]).agg(n_epoche=("epoch", "size"), n_rr_tot=("N_RR", "sum"), n_ko_tot=("N_KO", "sum"), diff_simm_tot=("diff_simm_tot", "sum"), avg_latency=("avg_latency", "mean")).reset_index())

    completa = per_seq[per_seq["n_epoche"] == 10].copy()
    n_strategie = completa.groupby(CHIAVI_SEQUENZA)["strategy"].transform("nunique")
    completa = completa[n_strategie == len(STRATEGIE)]

    ko_ottimo = completa.loc[completa["strategy"] == OTTIMO].set_index(CHIAVI_SEQUENZA)["n_ko_tot"]
    sequenze_valide = ko_ottimo[ko_ottimo > 0].index
    completa = completa[completa.set_index(CHIAVI_SEQUENZA).index.isin(sequenze_valide)]

    completa["costo_riconfig"] = completa["diff_simm_tot"] / completa["n_rr_tot"].replace(0, float("nan"))
    completa["path_delay_medio"] = completa["avg_latency"] * 1000
    completa["flussi_persi_pct"] = (1 - completa["n_rr_tot"] / completa["n_ko_tot"]) * 100
    return completa


def get_data_divario(df):
    completa = _sequenze_complete(df)
    group_cols = ["strategy", "n", "topology", "num_flows"]
    mean_cols = ["flussi_persi_pct", "costo_riconfig", "path_delay_medio"]
    tmp_df = completa.groupby(group_cols)[mean_cols].mean().reset_index()

    ottimo = (tmp_df[tmp_df["strategy"] == OTTIMO].drop(columns="strategy")
              .rename(columns={c: f"{c}_ottimo" for c in mean_cols}))
    tmp_df = tmp_df.merge(ottimo, on=["topology", "n", "num_flows"])

    # flussi_persi_pct e' gia' una percentuale: differenza assoluta in punti,
    # non rapporto -- altrimenti 0/0 (nessuno fallisce mai) da' NaN invece di 0
    tmp_df["diff_flussi_persi_pct"] = tmp_df["flussi_persi_pct"] - tmp_df["flussi_persi_pct_ottimo"]
    tmp_df["pct_diff_costo"] = (tmp_df["costo_riconfig"] - tmp_df["costo_riconfig_ottimo"]) / tmp_df["costo_riconfig_ottimo"] * 100
    tmp_df["pct_diff_lat"] = (tmp_df["path_delay_medio"] - tmp_df["path_delay_medio_ottimo"]) / tmp_df["path_delay_medio_ottimo"] * 100

    return tmp_df


ETICHETTA_METRICA = {
    "diff_flussi_persi_pct": "Failed",
    "pct_diff_costo": "Cost",
    "pct_diff_lat": "Delay",
}
ETICHETTA_ALGO = {
    "biased_k_shortest_path": "Ru",
    "biased_k_shortest_path_latency": "RuD",
    "latency_biased_paths": "De",
}
COLORI_ALGO = {ETICHETTA_ALGO[s]: COLORI[s] for s in EURISTICHE}   # sigla tabella -> colore strategia (come accuratezza.png)
NOME_ALGO = {"Ru": "Reuse", "RuD": "ReuseDelay", "De": "Delay"}   # sigla -> nome completo (legenda)


def tabella_divario(dati: pd.DataFrame, nome_file: str, out_dir: Path = OUT_DIR, dpi: int = 200) -> None:
    """Tabella Ru/RuD/De x Flussi x Nodi con lo scarto percentuale dall'ottimo
    esaustivo. Intestazioni a due livelli con celle unite (flussi e nodi
    scritti una volta sola per gruppo), bordi spessi sul confine
    intestazione/dati, etichette/dati e fra ogni gruppo; il valore migliore
    di ogni (flussi, nodi, metrica) in grassetto, pari merito inclusi.
    Disegnata a mano: pd.plotting.table non unisce celle ne' allinea linee
    esterne. dati e' l'output di get_data_divario, gia' filtrato a UNA topologia.
    """
    lungo = dati.melt(id_vars=["n", "num_flows", "strategy"],
                       value_vars=list(ETICHETTA_METRICA), var_name="colonna", value_name="valore")
    lungo["metrica"] = pd.Categorical(lungo["colonna"].map(ETICHETTA_METRICA),
                                       categories=list(ETICHETTA_METRICA.values()), ordered=True)
    lungo["algo"] = pd.Categorical(lungo["strategy"].map(ETICHETTA_ALGO),
                                    categories=list(ETICHETTA_ALGO.values()), ordered=True)

    tabella = lungo.pivot_table(index=["num_flows", "algo"], columns=["n", "metrica"], values="valore")
    num_flussi = tabella.index.get_level_values("num_flows").unique().tolist()
    algi = tabella.index.get_level_values("algo").unique().tolist()
    nodi = tabella.columns.get_level_values("n").unique().tolist()
    metriche = tabella.columns.get_level_values("metrica").unique().tolist()
    n_algo, n_metrica = len(algi), len(metriche)

    LARGH_ETICH, LARGH_DATO, ALT_HEADER, ALT_DATO = 1.15, 1.0, 0.85, 0.62
    x_bordi = [0, LARGH_ETICH, 2 * LARGH_ETICH] + [2 * LARGH_ETICH + k * LARGH_DATO
                                                     for k in range(1, len(nodi) * n_metrica + 1)]
    y_bordi = [0, ALT_HEADER, 2 * ALT_HEADER] + [2 * ALT_HEADER + k * ALT_DATO
                                                   for k in range(1, len(num_flussi) * n_algo + 1)]
    largh_tot, alt_tot = x_bordi[-1], y_bordi[-1]

    fig, ax = plt.subplots(figsize=(largh_tot * 0.9 + 0.5, alt_tot * 0.9 + 0.5))
    ax.set_xlim(0, largh_tot)
    ax.set_ylim(alt_tot, 0)   # riga 0 in alto, come una tabella
    ax.axis("off")

    massimo = tabella.abs().max().max()
    cmap = plt.get_cmap("RdYlGn_r")
    colore = lambda v: cmap(0.5 + 0.5 * v / massimo, alpha=0.65) if pd.notna(v) and massimo > 0 else "white"

    def cella(x0, y0, x1, y1, testo="", grassetto=False, sfondo="white", colore_testo=INK):
        ax.add_patch(plt.Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor=sfondo, edgecolor="none", zorder=1))
        if testo:
            ax.text((x0 + x1) / 2, (y0 + y1) / 2, testo, ha="center", va="center", fontsize=9,
                     fontweight="bold" if grassetto else "normal", color=colore_testo, zorder=3)

    HEADER = "white"
    cella(x_bordi[0], y_bordi[0], x_bordi[2], y_bordi[2], "Flussi / Nodi", grassetto=True, sfondo=HEADER)

    for i, n in enumerate(nodi):
        cella(x_bordi[2 + i * n_metrica], y_bordi[0], x_bordi[2 + (i + 1) * n_metrica], y_bordi[1],
              f"n = {n}", grassetto=True, sfondo=HEADER)
        for j, m in enumerate(metriche):
            cella(x_bordi[2 + i * n_metrica + j], y_bordi[1], x_bordi[2 + i * n_metrica + j + 1], y_bordi[2],
                  m, sfondo=HEADER)

    for i, nf in enumerate(num_flussi):
        cella(x_bordi[0], y_bordi[2 + i * n_algo], x_bordi[1], y_bordi[2 + (i + 1) * n_algo],
              f"flussi = {nf}", grassetto=True, sfondo=HEADER)
        for j, a in enumerate(algi):
            cella(x_bordi[1], y_bordi[2 + i * n_algo + j], x_bordi[2], y_bordi[2 + i * n_algo + j + 1],
                  a, grassetto=True, sfondo=COLORI_ALGO[a], colore_testo=_colore_testo(COLORI_ALGO[a]))

    for i, nf in enumerate(num_flussi):
        for k, n in enumerate(nodi):
            for j2, m in enumerate(metriche):
                valori = {a: tabella.loc[(nf, a), (n, m)] for a in algi}
                validi = [v for v in valori.values() if pd.notna(v)]
                minimo = min(validi) if validi else None
                for j, a in enumerate(algi):
                    v = valori[a]
                    cella(x_bordi[2 + k * n_metrica + j2], y_bordi[2 + i * n_algo + j],
                          x_bordi[2 + k * n_metrica + j2 + 1], y_bordi[2 + i * n_algo + j + 1],
                          f"{v:+.1f}%" if pd.notna(v) else "--",
                          grassetto=(minimo is not None and v == minimo), sfondo=colore(v))

    # linee: piene (spesse) su bordi esterni, confine intestazione/dati ed
    # etichette/dati, e fra i gruppi flussi/nodi; sottili solo dentro i gruppi.
    # Nella colonna dei flussi, nella riga dei nodi e nell'angolo non passa
    # nessuna linea interna -- le etichette unite restano pulite.
    y_piene = {y_bordi[0], y_bordi[2], y_bordi[-1]} | {y_bordi[2 + i * n_algo] for i in range(len(num_flussi) + 1)}
    x_piene = {x_bordi[0], x_bordi[2], x_bordi[-1]} | {x_bordi[2 + i * n_metrica] for i in range(len(nodi) + 1)}
    L = dict(color=INK, solid_capstyle="butt", clip_on=False, zorder=2)
    for y in y_bordi:
        if y in y_piene:
            ax.plot([x_bordi[0], x_bordi[-1]], [y, y], lw=1.8, **L)
        elif y == y_bordi[1]:                       # separa "n=X" da "Failed/Cost/Delay"
            ax.plot([x_bordi[2], x_bordi[-1]], [y, y], lw=0.4, **L)
        else:                                       # sottile fra due algoritmi
            ax.plot([x_bordi[1], x_bordi[-1]], [y, y], lw=0.4, **L)
    for x in x_bordi:
        if x in x_piene:
            ax.plot([x, x], [y_bordi[0], y_bordi[-1]], lw=1.8, **L)
        elif x == x_bordi[1]:                       # separa "flussi=X" dagli algoritmi
            ax.plot([x, x], [y_bordi[2], y_bordi[-1]], lw=0.4, **L)
        else:                                       # sottile fra due metriche
            ax.plot([x, x], [y_bordi[1], y_bordi[-1]], lw=0.4, **L)

    legenda = [Patch(facecolor=COLORI_ALGO[a], edgecolor="none", label=f"{a}  =  {NOME_ALGO[a]}") for a in algi]
    ax.legend(handles=legenda, loc="upper center", bbox_to_anchor=(0.5, -0.01),
              ncol=len(algi), frameon=False, fontsize=9, handlelength=1.3, columnspacing=2.5)

    percorso = out_dir / nome_file
    fig.savefig(percorso, dpi=dpi, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    print(f"Salvato: {percorso}")


def main() -> None:
    df = carica_dati()
    plot_accuratezza(prepara_dati_accuratezza(df))
    dati_divario = get_data_divario(df)
    for topo in TOPOLOGIE_ORDINATE:
        tabella_divario(dati_divario[dati_divario["topology"] == topo], f"tabella_divario_{topo}.png")
        plot_tempo_griglia(prepara_dati_tempo_griglia(df))
    dati_generale = dati_divario.groupby(["strategy", "n", "num_flows"])[list(ETICHETTA_METRICA)].mean().reset_index()
    tabella_divario(dati_generale, "tabella_divario_generale.png")
    tabella_divario(dati_generale[(dati_generale["num_flows"] == 6) & (dati_generale["n"] == 40)], "tabella_divario_generale_f6_n40.png")


if __name__ == "__main__":
    main()
