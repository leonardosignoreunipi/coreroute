"""
Plot dei risultati dell'esperimento finale (Task 6), seguendo PLOTTING_PLAN.md.

Legge  benchmark/results/epoch_drift_biased_k_latency.csv
Produce 12 figure PNG in  benchmark/results/plots_finali/

Come funziona il file (per orientarti):
  - in alto: costanti (colori, percorsi, config di riferimento);
  - due funzioni-aiuto riusate ovunque:  _stile(ax)  e  _banda(...);
  - una funzione per ogni figura ( fig1_...  fig2_...  ...  figV3_... );
  - main() le chiama tutte.

Ogni figura fissa n=1000 e flow_factor=1.0 (la config di massima contesa) e
aggrega SOLO sui 10 seed, disegnando la mediana con una banda tra 25° e 75°
percentile (IQR). Per lanciarlo:

    python benchmark/plot_results.py
"""

from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")            # salva su file senza aprire finestre
import matplotlib.pyplot as plt

# ---------------------------------------------------------------------------
# COSTANTI
# ---------------------------------------------------------------------------

BENCHMARK_DIR = Path(__file__).parent
CSV_PATH  = BENCHMARK_DIR / "results" / "epoch_drift_biased_k_latency.csv"
OUT_DIR   = BENCHMARK_DIR / "results" / "plots_finali"

# config di riferimento: la cella dove CR e FULL si distinguono di più
N_RIF   = 1000
FF_RIF  = 1.0
PCT_RIF = 30           # degrado moderato: 30% di archi perturbati per epoca (fig. 3)

# colori per il confronto CR vs FULL
COL_CR   = "#2a78d6"   # blu
COL_FULL = "#eb6834"   # arancione

# colori per il destino dei flussi (figura 3): tre quantità annidate
COL_KO      = "#eb6834"   # arancione — flussi che hanno perso il percorso
COL_R       = "#2a78d6"   # blu       — reinstradati con successo
COL_CHANGED = "#008300"   # verde     — con percorso effettivamente cambiato

# colori quando ogni linea è una TOPOLOGIA (figure 2)
COL_TOPO = {"iaag": "#e87ba4", "er": "#2a78d6", "ba": "#008300"}

TOPOLOGIE = ["iaag","er", "ba"]
NOME_TOPO = {"er": "ER", "ba": "BA", "iaag": "IAAG"}

# colori "testo" per assi/griglia
INK, INK2, GRIGIO, SFONDO = "#0b0b0b", "#52514e", "#b8b7b0", "#fcfcfb"


# ---------------------------------------------------------------------------
# FUNZIONI-AIUTO (usate da tutte le figure)
# ---------------------------------------------------------------------------

def _stile(ax):
    """Applica lo stile comune a un pannello (griglia leggera, assi puliti)."""
    ax.set_facecolor(SFONDO)
    ax.grid(True, axis="y", color=GRIGIO, lw=0.6, alpha=0.5)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(GRIGIO)
    ax.spines["bottom"].set_color(GRIGIO)
    ax.tick_params(colors=INK2, length=3)


def _banda(ax, sub, x_col, y_col, colore, etichetta, linestyle="-", marker="o"):
    """
    Disegna, in funzione di x_col, la MEDIANA di y_col sui seed, con una
    banda ombreggiata tra il 25° e il 75° percentile (IQR).

    sub : porzione del DataFrame già filtrata (topologia, n, ff fissi).
    """
    gruppi = sub.groupby(x_col)[y_col]
    x   = sorted(sub[x_col].unique())
    med = gruppi.median().reindex(x)
    q25 = gruppi.quantile(0.25).reindex(x)
    q75 = gruppi.quantile(0.75).reindex(x)
    ax.fill_between(x, q25, q75, color=colore, alpha=0.15, lw=0)
    ax.plot(x, med, linestyle, color=colore, lw=2, marker=marker, ms=5,
            mfc=SFONDO, mew=1.6, label=etichetta, clip_on=False, zorder=3)
    ax.set_xticks(x)   # solo i valori realmente testati, niente tick inventati


def _nuova_figura_per_topologia(titolo, sottotitolo, ylabel, xlabel):
    """Crea una figura con un pannello per topologia (er, ba, iaag) e titoli."""
    # sharey=True: stesso asse y su tutti e tre i pannelli, così le topologie
    # sono confrontabili a colpo d'occhio (solo il pannello di sinistra mostra i tick).
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), facecolor=SFONDO, sharey=True)
    for ax, topo in zip(axes, TOPOLOGIE):
        _stile(ax)
        ax.set_title(NOME_TOPO[topo], color=INK, fontsize=13, fontweight="bold", loc="left")
        ax.set_xlabel(xlabel, color=INK2, fontsize=9)
    axes[0].set_ylabel(ylabel, color=INK2, fontsize=9)
    fig.suptitle(titolo, color=INK, fontsize=14, fontweight="bold", x=0.02, ha="left")
    fig.text(0.02, 0.9, sottotitolo, color=INK2, fontsize=9)
    return fig, axes


def _legenda_in_alto(fig, ax, titolo=None):
    """Legenda in alto a destra, all'altezza del titolo.

    Usa fig.legend (livello FIGURA) e non ax.legend (livello PANNELLO):
    ax.legend la incollerebbe al primo pannello, mai al bordo della figura.
    Le voci vengono lette dal pannello `ax` e impilate una per riga (ncol=1),
    cosi' le etichette restano leggibili anche quando sono lunghe.
    """
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, title=titolo, frameon=False, fontsize=9,
               labelcolor=INK2, loc="upper right", bbox_to_anchor=(0.99, 1.0),
               ncol=1, handlelength=1.6, labelspacing=0.4)


def _salva(fig, nome_file):
    """Salva la figura in OUT_DIR e chiude."""
    # top a 0.82: la legenda di _legenda_in_alto e' verticale (una voce per riga),
    # quindi scende sotto il titolo e serve piu' spazio libero in cima.
    fig.tight_layout(rect=[0.01, 0.01, 0.99, 0.82])
    percorso = OUT_DIR / nome_file
    fig.savefig(percorso, dpi=170, facecolor=SFONDO)
    plt.close(fig)
    print("salvato", percorso)

def fig1_costo_riconfigurazione(df):
    """CR vs FULL sul costo di riconfigurazione. x=pct_mod, ultima epoca."""
    last = df[df.epoch == df.epoch.max()]                
    fig, axes = _nuova_figura_per_topologia(
        "Costo di riconfigurazione: CR vs FULL",
        "(epoch=12, n=1000, flows=1000) · mediana ± IQR sui seed",
        "#ri-configurazioni totali", "percentuale archi perturbati (%)")
    for ax, topo in zip(axes, TOPOLOGIE):
        sub = last[(last.topology == topo) & (last.n == N_RIF) & (last.flow_factor == FF_RIF)]
        _banda(ax, sub, "pct_mod", "diff_simm_tot_CR",   COL_CR,   "Continuous Reasoning")
        _banda(ax, sub, "pct_mod", "diff_simm_tot_FULL", COL_FULL, "Full Recompute")
    _legenda_in_alto(fig, axes[0])
    _salva(fig, "fig1_costo_riconfig.png")


def fig2_rapporto_cr_full(df):
    """% di ri-configurazioni risparmiate da CR rispetto a FULL. Un pannello
    per topologia (invece di 3 linee sovrapposte): così ogni banda di
    fiducia (IQR) è isolata e si legge senza incrociarsi con le altre."""
    last = df[df.epoch == df.epoch.max()].copy()
    # risparmio per ogni riga (= per seed), poi mediana sui seed
    last["risparmio_%"] = 100 * (1 - last.diff_simm_tot_CR / last.diff_simm_tot_FULL)

    fig, axes = _nuova_figura_per_topologia(
        "% Ri-configurazioni risparmiate cr-routing grazie all'euristica W02-latency",
        "(epoch=12, n=1000, flows=1000) · mediana ± IQR sui seed",
        "riconfigurazioni-cr/ri-configurazioni-full (%)", " % archi perturbati ")
    for ax, topo in zip(axes, TOPOLOGIE):
        sub = last[(last.topology == topo) & (last.n == N_RIF) & (last.flow_factor == FF_RIF)]
        _banda(ax, sub, "pct_mod", "risparmio_%", COL_TOPO[topo], NOME_TOPO[topo])
    _salva(fig, "fig2_rapporto_riconfig_cr_full.png")


def fig3_flussi_nel_tempo(df):
    """Che fine fanno i flussi, epoca per epoca (solo CR).

    Tre quantita' ANNIDATE (KO >= reinstradati >= cambiati):
      N_KO_CR          flussi che hanno perso il percorso -> da gestire
      N_R_CR           di quelli, quanti CR e' riuscito a reinstradare
      flows_changed_CR di quelli, quanti hanno davvero cambiato percorso

    I due divari sono il messaggio, percio' quello alto (KO - reinstradati =
    flussi rimasti senza rotta) e' ombreggiato invece di essere lasciato al
    calcolo mentale del lettore.
    Il degrado e' fissato al 30% di archi perturbati (degrado moderato, non il
    caso peggiore): a 20% la banda dei falliti sparisce su BA e IAAG (4 flussi
    su ~60-80) e le curve sono troppo rumorose; a 50% il divario
    reinstradati-cambiati si comprime. A 30% si vedono bene entrambi.
    """
    base_all = df[(df.n == N_RIF) & (df.flow_factor == FF_RIF) & (df.pct_mod == PCT_RIF)]
    fig, axes = _nuova_figura_per_topologia(
        "Correttezza nel reinstradamento flussi ko - CR",
        f"n=1000, flows=1000, {PCT_RIF:.0f}% di archi perturbati per epoca · mediana sui seed",
        "numero di flussi", "epoca")
    for ax, topo in zip(axes, TOPOLOGIE):
        sub = base_all[base_all.topology == topo]
        g = sub.groupby("epoch")
        ep      = sorted(sub.epoch.unique())
        ko      = g.N_KO_CR.median().reindex(ep)
        rerout  = g.N_R_CR.median().reindex(ep)
        changed = g.flows_changed_CR.median().reindex(ep)

        # il divario KO - reinstradati = flussi rimasti senza rotta valida
        ax.fill_between(ep, rerout, ko, color=COL_KO, alpha=0.15, lw=0, label="divario = falliti")
        ax.plot(ep, ko,      "-o", color=COL_KO,      lw=2, ms=4, mfc=SFONDO, label="KO (senza percorso)", clip_on=False, zorder=3)
        ax.plot(ep, rerout,  "-o", color=COL_R,       lw=2, ms=4, mfc=SFONDO, label="reinstradati",         clip_on=False, zorder=3)
        ax.plot(ep, changed, "-o", color=COL_CHANGED, lw=2, ms=4, mfc=SFONDO, label="percorso cambiato", clip_on=False, zorder=3)
        ax.set_xticks(ep)
    _legenda_in_alto(fig, axes[0])
    _salva(fig, "fig3_flussi_nel_tempo.png")


def fig3b_flussi_toccati(df):
    """Quanti flussi il controller deve DISTURBARE: CR vs FULL.

    Stessa cella della fig. 3 (n=1000, ff=1.0, PCT_RIF) ma alla sola ultima
    epoca, dove FULL e' misurato. Metrica piu' concreta della differenza
    simmetrica di archi: "quanti flussi cambiano percorso" si legge senza
    conoscere il modello di costo.

    La riga nera e' il numero di flussi che si erano DAVVERO rotti (N_KO_CR):
    e' il riferimento che rende leggibile il punto chiave, cioe' che FULL
    tocca molti piu' flussi di quanti ne fossero guasti - sposta flussi sani.
    Solo 3 gruppi di barre, quindi i valori sono etichettati direttamente:
    la figura serve proprio a leggere quei numeri.
    """
    last = df[(df.epoch == df.epoch.max()) & (df.n == N_RIF) & (df.flow_factor == FF_RIF) & (df.pct_mod == PCT_RIF)]

    fig, ax = plt.subplots(figsize=(9, 5.5), facecolor=SFONDO)
    _stile(ax)
    larghezza = 0.32
    for i, topo in enumerate(TOPOLOGIE):
        s  = last[last.topology == topo]
        cr, full, ko = (s.flows_changed_CR.median(), s.flows_changed_FULL.median(), s.N_KO_CR.median())
        # etichette solo sul primo gruppo: la legenda non va ripetuta 3 volte
        et = (lambda testo: testo if i == 0 else None)
        ax.bar(i - larghezza/2, cr,   width=larghezza, color=COL_CR, label=et("Continuous Reasoning"))
        ax.bar(i + larghezza/2, full, width=larghezza, color=COL_FULL, label=et("Full Recompute"))
        # riferimento: quanti flussi erano realmente KO
        ax.hlines(ko, i - 0.44, i + 0.44, color=INK, lw=1.6, ls="--", zorder=4, label=et("flussi realmente guasti (KO)"))
        for x, v in ((i - larghezza/2, cr), (i + larghezza/2, full)):
            ax.text(x, v + 12, f"{v:.0f}", ha="center", color=INK2, fontsize=9)

    ax.set_xticks(range(len(TOPOLOGIE)))
    ax.set_xticklabels([NOME_TOPO[t] for t in TOPOLOGIE], color=INK2)
    ax.set_ylabel("flussi che cambiano percorso", color=INK2, fontsize=9)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK2, loc="upper left")
    fig.suptitle("Flussi che cambiano percorso: CR vs FULL", color=INK, fontsize=14, fontweight="bold", x=0.02, ha="left")
    fig.text(0.02, 0.90, f"ultima epoca, n=1000, ff=1.0, {PCT_RIF:.0f}% di archi perturbati · mediana sui seed", color=INK2, fontsize=9)
    _salva(fig, "fig3b_flussi_toccati.png")


def fig4a_tempo_vs_nodi(df):
    """Tempo al crescere della rete: CR e' sensibile al degrado, FULL no.

    x = numero di nodi, y = tempo. Ultima epoca (dove FULL e' misurato), ff=1.0.

    CR: una linea per livello di perturbazione (blu via via piu' scuro). Il
    VENTAGLIO che si apre e' di per se' la sensibilita' di CR al degrado:
    a n=1000 il tempo varia 2.3-3.6x passando dal 10% al 50% di archi perturbati.

    FULL: una linea sola, mediana + IQR calcolata su TUTTI i pct insieme oltre
    che sui seed. E' una deroga deliberata alla regola d'oro n.1 (non mescolare
    dimensioni in una banda): qui mescolarle e' il punto, perche' la banda resta
    stretta (1.3-6.5%) e questo DIMOSTRA che FULL non vede la perturbazione.
    Fra i pct T_FULL varia 1.01-1.09x, cioe' nulla.

    Le bande IQR delle linee CR sono omesse: sarebbero 4 bande sovrapposte e
    illeggibili, e la dispersione che conta (quella fra pct) e' gia' resa dal
    ventaglio stesso.
    """
    last = df[(df.epoch == df.epoch.max()) & (df.flow_factor == FF_RIF)]
    pct_livelli = sorted(last.pct_mod.unique())

    fig, axes = _nuova_figura_per_topologia(
        "Tempi di esecuzione: CR vs FULL",
        "(epoch=12, flows=1000) · CR: una linea per livello di perturbazione · "
        "FULL: linea unica, banda IQR, invisibile per la poca varianza",
        "tempo (s)", "#nodi")
    for ax, topo in zip(axes, TOPOLOGIE):
        sub = last[last.topology == topo]
        # FULL per primo, cosi' la banda resta sotto le linee di CR
        _banda(ax, sub, "n", "T_FULL", COL_FULL, "FULL — tutti i pct")
        for i, pct in enumerate(pct_livelli):
            s   = sub[sub.pct_mod == pct]
            n   = sorted(s.n.unique())
            med = s.groupby("n").T_CR.median().reindex(n)
            # blu via via piu' scuro al crescere della perturbazione
            colore = plt.cm.Blues(0.45 + 0.55 * i / (len(pct_livelli) - 1))
            ax.plot(n, med, "-o", color=colore, lw=2, ms=4, mfc=SFONDO, mew=1.4, label=f"CR {pct:.0f}%", clip_on=False, zorder=3)
    _legenda_in_alto(fig, axes[0])
    _salva(fig, "fig4a_tempo_vs_nodi.png")


def fig4b_tempo_vs_pct(df):
    """Tempo CR (sale) vs FULL (piatto) al crescere del degrado. n=1000 ff=1.0."""
    last = df[df.epoch == df.epoch.max()]
    fig, axes = _nuova_figura_per_topologia(
        "Tempo di esecuzione al crescere del degrado",
        "(n=1000, flows=1.0) · mediana ± IQR sui seed",
        "tempo (s)", "% archi perturbati")
    for ax, topo in zip(axes, TOPOLOGIE):
        sub = last[(last.topology == topo) & (last.n == N_RIF) & (last.flow_factor == FF_RIF)]
        _banda(ax, sub, "pct_mod", "T_CR",   COL_CR,   "Continuous Reasoning")
        _banda(ax, sub, "pct_mod", "T_FULL", COL_FULL, "Full Recompute")
    _legenda_in_alto(fig, axes[0])
    _salva(fig, "fig4b_tempo_vs_pct.png")


def fig4c_speedup_vs_pct(df):
    """Speed-up di CR su FULL (T_FULL / T_CR) al crescere del degrado.

    x=pct_mod, ultima epoca (dove FULL è misurato). Una linea per topologia.
    Sopra la linea 1× = CR è più veloce; il vantaggio si riduce col degrado
    perché T_CR sale (più flussi da reinstradare) mentre T_FULL è quasi fisso.
    """
    last = df[df.epoch == df.epoch.max()].copy()
    last["speedup"] = last.T_FULL / last.T_CR      # quante volte CR è più veloce

    fig, ax = plt.subplots(figsize=(8, 5.5), facecolor=SFONDO)
    _stile(ax)
    ax.axhline(1, color=GRIGIO, lw=1.2, ls=":")    # riferimento: sotto = CR non più veloce
    for topo in TOPOLOGIE:
        sub = last[(last.topology == topo) & (last.n == N_RIF) & (last.flow_factor == FF_RIF)]
        _banda(ax, sub, "pct_mod", "speedup", COL_TOPO[topo], NOME_TOPO[topo])
    ax.set_xlabel("percentuale archi perturbati (%)", color=INK2, fontsize=9)
    ax.set_ylabel("speed-up  (T_FULL / T_CR)", color=INK2, fontsize=9)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK2, loc="upper right")
    fig.suptitle("Speed-up al crescere del numero di archi rr perturbati", color=INK, fontsize=14, fontweight="bold", x=0.02, ha="left")
    fig.text(0.02, 0.90, "SPEEDUP (T-cr/T-full) · (n=1000, flows=1000, epoch=12)", color=INK2, fontsize=9)
    _salva(fig, "fig4c_speedup_vs_pct.png")


def fig5_latenza(df):
    """Latenza: traiettoria di CR per epoca + FULL come punto all'ultima epoca."""
    ultima = df.epoch.max()
    fig, axes = _nuova_figura_per_topologia(
        "Latenza media al crescere delle perturbazioni con full ad epoch=12",
        "linee = CR nel tempo · punti = FULL (n=1000, flows=1000) · mediana sui seed",
        "latenza media paths (s)", "epoca")
    for ax, topo in zip(axes, TOPOLOGIE):
        base = df[(df.topology == topo) & (df.n == N_RIF) & (df.flow_factor == FF_RIF)]
        for i, pct in enumerate(sorted(base.pct_mod.unique())):
            colore = plt.cm.viridis(i / 3)          
            sub = base[base.pct_mod == pct]
            # linea CR su tutte le epoche
            med_cr = sub.groupby("epoch").avg_latency_CR.median()
            ax.plot(med_cr.index, med_cr.values, "-", color=colore, lw=2,
                    label=f"{pct:.0f}%", clip_on=False)
            # punto FULL alla sola ultima epoca, stesso colore, marker a stella
            full = sub[sub.epoch == ultima].avg_latency_FULL.median()
            ax.plot(ultima, full, marker="*", color=colore, ms=13, mec=INK, mew=0.6, clip_on=False, zorder=5)
        ax.set_xticks(sorted(base.epoch.unique()))   # solo le epoche testate
    _legenda_in_alto(fig, axes[0], titolo="degrado")
    _salva(fig, "fig5_latenza.png")


def fig5b_latenza_vs_pct(df):
    """Latenza CR vs FULL al crescere del degrado. x=pct_mod, ultima epoca.

    Vista like-for-like: entrambe le strategie esistono all'ultima epoca, quindi
    si confrontano direttamente. Mostra come la latenza sale col degrado e il
    gap (piccolo) che CR paga rispetto a FULL a ogni livello di danno.
    """
    last = df[df.epoch == df.epoch.max()]
    fig, axes = _nuova_figura_per_topologia(
        "Fig. 5b — Latenza media: CR vs FULL al crescere del degrado",
        "latenza media di percorso, ultima epoca (n=1000, ff=1.0) · mediana ± IQR sui seed",
        "latenza media di percorso (s)", "percentuale archi perturbati (%)")
    for ax, topo in zip(axes, TOPOLOGIE):
        sub = last[(last.topology == topo) & (last.n == N_RIF) & (last.flow_factor == FF_RIF)]
        _banda(ax, sub, "pct_mod", "avg_latency_CR",   COL_CR,   "Continuous Reasoning")
        _banda(ax, sub, "pct_mod", "avg_latency_FULL", COL_FULL, "Full Recompute")
    _legenda_in_alto(fig, axes[0])
    _salva(fig, "fig5b_latenza_vs_pct.png")


# ---------------------------------------------------------------------------
# FIGURE DI VALIDITA' (V1-V3)
# ---------------------------------------------------------------------------

def figV1_degrado(df):
    """Quanto è stata degradata la rete: frac_rr_degraded per epoca, per pct."""
    fig, axes = _nuova_figura_per_topologia(
        "Fig. V1 — Quanto abbiamo degradato la rete",
        "frazione di link router-router sotto la banda nominale (n=1000, ff=1.0)",
        "frazione di link degradati", "epoca")
    for ax, topo in zip(axes, TOPOLOGIE):
        base = df[(df.topology == topo) & (df.n == N_RIF) & (df.flow_factor == FF_RIF)]
        for pct in sorted(base.pct_mod.unique()):
            sub = base[base.pct_mod == pct]
            med = sub.groupby("epoch").frac_rr_degraded.median()
            ax.plot(med.index, med.values, "-o", lw=2, ms=4, mfc=SFONDO,
                    label=f"{pct:.0f}%", clip_on=False)
        ax.set_ylim(0, 1)
        ax.set_xticks(sorted(base.epoch.unique()))   # solo le epoche testate
    _legenda_in_alto(fig, axes[0], titolo="degrado")
    _salva(fig, "figV1_degrado.png")


def figV2_copertura(df):
    """Frazione di flussi che restano senza rotta (non servibili). CR vs FULL."""
    last = df[df.epoch == df.epoch.max()].copy()
    # flussi falliti = KO non reinstradati; poi come frazione del totale
    last["P_failed_CR"]   = (last.N_KO_CR   - last.N_R_CR)   / last.num_flows
    last["P_failed_FULL"] = (last.N_KO_FULL - last.N_R_FULL) / last.num_flows

    fig, axes = _nuova_figura_per_topologia(
        "Copertura del servizio",
        "frazione di flussi che restano senza rotta valida, (epoch=12, n=1000, flussi=1000)",
        "frazione di flussi falliti", "% archi perturbati")
    for ax, topo in zip(axes, TOPOLOGIE):
        sub = last[(last.topology == topo) & (last.n == N_RIF) & (last.flow_factor == FF_RIF)]
        _banda(ax, sub, "pct_mod", "P_failed_CR",   COL_CR,   "Continuous Reasoning")
        _banda(ax, sub, "pct_mod", "P_failed_FULL", COL_FULL, "Full Recompute")
    _legenda_in_alto(fig, axes[0])
    _salva(fig, "figV2_copertura.png")


def figV3_fallimenti(df):
    """Perché falliscono: pruning (Stage 1) vs ragionamento Prolog. Barre impilate."""
    last = df[df.epoch == df.epoch.max()].copy()
    last["falliti"]     = last.N_KO_CR - last.N_R_CR
    last["prolog_fail"] = last.falliti - last.no_path_count_CR   # contesa/SLA

    fig, axes = _nuova_figura_per_topologia(
        "Fig. V3 — Perché i flussi falliscono: pruning vs ragionamento",
        "quasi tutti i fallimenti vengono dai vincoli in Prolog, non dalla disconnessione",
        "flussi falliti (medi)", "percentuale archi perturbati (%)")
    for ax, topo in zip(axes, TOPOLOGIE):
        sub = last[(last.topology == topo) & (last.n == N_RIF) & (last.flow_factor == FF_RIF)]
        g = sub.groupby("pct_mod")
        pct   = sorted(sub.pct_mod.unique())
        prol  = g.prolog_fail.mean().reindex(pct)
        nopath = g.no_path_count_CR.mean().reindex(pct)
        larghezza = 6
        ax.bar(pct, prol,   width=larghezza, color=COL_CR,   label="ragionamento Prolog")
        ax.bar(pct, nopath, width=larghezza, bottom=prol, color=COL_FULL, label="disconnessione (Stage 1)")
        ax.set_xticks(pct)   # solo i pct_mod testati
    _legenda_in_alto(fig, axes[0])
    _salva(fig, "figV3_fallimenti.png")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(CSV_PATH)
    df = df[df.ok == True]
    df["pct_mod"] = df.pct_mod * 100   # da frazione (0.1) a percentuale di archi perturbati (10)
    df["epoch"]   = df.epoch + 1       # le epoche si numerano da 1, non da 0 (solo per i grafici)

    # risultati
    fig1_costo_riconfigurazione(df)
    fig2_rapporto_cr_full(df)
    fig3_flussi_nel_tempo(df)
    fig3b_flussi_toccati(df)
    fig4a_tempo_vs_nodi(df)
    fig4b_tempo_vs_pct(df)
    fig4c_speedup_vs_pct(df)
    fig5_latenza(df)
    fig5b_latenza_vs_pct(df)
    # validità
    figV1_degrado(df)
    figV2_copertura(df)
    figV3_fallimenti(df)


if __name__ == "__main__":
    main()
