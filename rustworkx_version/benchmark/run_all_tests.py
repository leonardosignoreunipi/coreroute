import os
import glob
import subprocess
import re
import json

# 1. Configurazione
cartella_test = "topologies"
script_test = "run_test.py"
kb_file = "routing_core.pl"
OUTPUT_FILE = "results/benchmark_k_shortest_path.json"

TOPOLOGIA_NAMES = {
    "ba":   "Barabasi-Albert",
    "er":   "Erdos-Renyi",
    "iaag": "Internet (Holme-Kim)",
}

# Trova tutti i json generati
file_topologie = glob.glob(os.path.join(cartella_test, "*.json"))
dati_risultati = []

print(f"🚀 Trovati {len(file_topologie)} file di test. Inizio esecuzione benchmark...")

# 2. Esecuzione Automatizzata
for i, file_topo in enumerate(file_topologie, 1):
    # Estraiamo i parametri direttamente dal nome del file
    nome_base = os.path.basename(file_topo)
    match = re.search(r"topo_(ba|er|iaag)_N(\d+)_F(\d+)_S(\d+)\.json", nome_base)
    
    if not match:
        continue
        
    gtype = match.group(1)
    num_nodes = int(match.group(2))
    num_flows = int(match.group(3))
    seed = int(match.group(4))

    print(f"[{i}/{len(file_topologie)}] Esecuzione su {gtype.upper()} | Router: {num_nodes} | Flussi: {num_flows} | Seed: {seed}")
    
    comando = [
        "python3", script_test, 
        file_topo,      # argv[1]
    ]
    
    try:
        # Eseguiamo il test e catturiamo l'output stampato nel terminale
        result = subprocess.run(comando, capture_output=True, text=True, check=True, timeout = 600)
        output = result.stdout

        # Cerchiamo la riga con il dizionario di ritorno di run_test.main() serializzato in JSON
        match_data = re.search(r"RESULTJSON:(\{.*\})", output)

        if match_data:
            res = json.loads(match_data.group(1))

            dati_risultati.append({
                "file_test": nome_base,
                "topologia": TOPOLOGIA_NAMES.get(gtype, gtype),
                "nodi_iniziali": num_nodes,
                "nodi_reali_caricati": res["num_nodes"],
                "archi_rimanenti": res["num_edges"],
                "flussi": res["num_flows"],
                "flussi_ko": res["n_ko"],
                "flussi_rerouted": res["n_r"],
                "flussi_ko_full": res["n_full_ko"],
                "flussi_rerouted_full": res["n_full_rr"],
                "link_modificati": res["n_modified"],
                "tempo_cr_sec": res["t_cr"],
                "tempo_non_cr_sec": res["t_full"],
            })
        else:
            # Fallback: se RESULTDATA non c'è, prendiamo solo il tempo stampato a schermo
            time_match = re.search(r"Tempo CR:\s*([\d\.]+)\s*secondi", output)
            if time_match:
                exec_time = float(time_match.group(1))
                dati_risultati.append({
                    "file_test": nome_base,
                    "topologia": TOPOLOGIA_NAMES.get(gtype, gtype),
                    "nodi_iniziali": num_nodes,
                    "flussi": num_flows,
                    "tempo_cr_sec": exec_time
                })
            else:
                print(f"  -> ⚠️ Tempo non trovato nell'output di {nome_base}")
                
    except subprocess.CalledProcessError as e:
        print(f"  -> ❌ Errore durante l'esecuzione di {nome_base}.")
        print(f"     Dettaglio: {e.stderr.strip()}")

# 3. Salvataggio in JSON
if not dati_risultati:
    print("\nNessun dato raccolto. Il file benchmark.json non è stato generato.")
else:
    
    if not os.path.exists("results"):
        os.mkdir("results")
    
    # Scriviamo la lista di dizionari nel file JSON in formato leggibile (indent=4)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(dati_risultati, f, indent=4)
        
    print(f"\n✅ Benchmark completato! Tutti i {len(dati_risultati)} risultati sono stati salvati in '{OUTPUT_FILE}'.")