import os
import glob
import subprocess
import re
import json

# 1. Configurazione
cartella_test = "topologies"
script_test = "run_test.py"
kb_file = "routing_core.pl"

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
    match = re.search(r"topo_(ba|er|iaag)_R(\d+)_H(\d+)_F(\d+)\.json", nome_base)
    
    if not match:
        continue
        
    gtype = match.group(1)
    num_routers = int(match.group(2))
    num_flows = int(match.group(4))
    num_hosts = int(match.group(3))
    
    print(f"[{i}/{len(file_topologie)}] Esecuzione su {gtype.upper()} | Router: {num_routers} | Host: {num_hosts} | Flussi: {num_flows}")
    
    comando = [
        "python3", script_test, 
        file_topo,      # argv[1]
    ]
    
    try:
        # Eseguiamo il test e catturiamo l'output stampato nel terminale
        result = subprocess.run(comando, capture_output=True, text=True, check=True, timeout = 600)
        output = result.stdout
        
        # Cerchiamo la stringa con i dati completi (se test.py stampa RESULTDATA)
        match_data = re.search(r"RESULTDATA:(\d+),(\d+),(\d+),([\d\.]+),([\d\.]+),(\d+)", output)

        if match_data:
            num_edges_reali = int(match_data.group(1))
            num_nodes_reali = int(match_data.group(2))
            num_flows_reali = int(match_data.group(3))
            exec_time = float(match_data.group(4))
            nocr_time = float(match_data.group(5))
            flussi_ko = int(match_data.group(6))

            dati_risultati.append({
                "file_test": nome_base,
                "topologia": TOPOLOGIA_NAMES.get(gtype, gtype),
                "nodi_iniziali": num_routers,
                "nodi_reali_caricati": num_nodes_reali,
                "archi_rimanenti": num_edges_reali,
                "flussi": num_flows_reali,
                "flussi_ko": flussi_ko,
                "tempo_cr_sec": exec_time,
                "tempo_non_cr_sec": nocr_time,
            })
        else:
            # Fallback: se RESULTDATA non c'è, prendiamo solo il tempo stampato a schermo
            time_match = re.search(r"Tempo CR:\s*([\d\.]+)\s*secondi", output)
            if time_match:
                exec_time = float(time_match.group(1))
                dati_risultati.append({
                    "file_test": nome_base,
                    "topologia": TOPOLOGIA_NAMES.get(gtype, gtype),
                    "nodi_iniziali": num_routers,
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
    output_file = "benchmark.json"
    
    # Scriviamo la lista di dizionari nel file JSON in formato leggibile (indent=4)
    with open(output_file, "w") as f:
        json.dump(dati_risultati, f, indent=4)
        
    print(f"\n✅ Benchmark completato! Tutti i {len(dati_risultati)} risultati sono stati salvati in '{output_file}'.")