import subprocess
import os
import math

cartella_output = "topologies"
os.makedirs(cartella_output, exist_ok=True)

class GeneraTopologieError(Exception):
    """Custom exception for errors in topology generation."""
    pass

# PARAMETERS
# ER edges grow as n²·p/2 → too many Prolog facts at n=1024 → OOM.
# BA/IAAG edges grow as O(n) → safe at all sizes.
ESPONENTI_PER_TIPO = {
    "er":   [5, 7, 9, 10],  # 32, 128, 512, 1024
    "ba":   [5, 7, 9, 10],  # 32, 128, 512, 1024
    "iaag": [5, 7, 9, 10],  # 32, 128, 512, 1024
}
tipologie_grafo = list(ESPONENTI_PER_TIPO.keys())
flow_load_factors = [0.5, 1.5, 3.0] # num_flows = sqrt(estimated_edges) * load_factor

MAX_FLOWS = 500 #TODO: test with 1000 flows for large topologies
MIN_FLOWS = 5

def estimated_edges(gtype, num_routers):
    """Stima del numero di archi router-router in base al tipo di grafo."""
    if gtype == "ba":
        return 2 * num_routers        # BA m=2
    elif gtype == "er":
        if num_routers <= 32:   p = 0.15
        elif num_routers <= 128: p = 0.05
        elif num_routers <= 256: p = 0.03
        else:                    p = 0.015
        return int(num_routers * (num_routers - 1) / 2 * p)
    elif gtype == "iaag":
        return 4 * num_routers
    return num_routers

contatore = 1
totale_file = sum(
    1
    for gtype in tipologie_grafo
    for esp in ESPONENTI_PER_TIPO[gtype]
    for _ in flow_load_factors
)

print("Inizio generazione automatica delle topologie...")

for gtype in tipologie_grafo:
    for esp in ESPONENTI_PER_TIPO[gtype]:
        num_routers = 2 ** esp
        est_edges = estimated_edges(gtype, num_routers)

        for lf in flow_load_factors:
            num_flows = int(math.sqrt(est_edges) * lf)
            num_flows = max(MIN_FLOWS, min(MAX_FLOWS, num_flows)) # MIN_FLOWS <= num_flows <= MAX_FLOWS
            num_hosts = max(4, min(num_routers // 2, int(math.sqrt(num_flows) * 2) + 2)) # TODO: refine host count logic 

            filename = f"{cartella_output}/topo_{gtype}_R{num_routers}_H{num_hosts}_F{num_flows}.json"

            if os.path.exists(filename):
                print(f"[{contatore}/{totale_file}] Saltato: {filename} esiste gia'.")
                contatore += 1
                continue

            print(f"[{contatore}/{totale_file}] Generazione -> {filename} "
                  f"(R={num_routers}, H={num_hosts}, F={num_flows}, edges_est={est_edges})")

            comando = [
                "python", "build_topology.py",
                gtype, str(num_routers), str(num_hosts), str(num_flows), filename
            ]

            try:
                subprocess.run(comando, check=True)
            except subprocess.TimeoutExpired:
                raise GeneraTopologieError(f"Timeout durante la generazione della topologia: {filename}")

            contatore += 1

print("\nGenerazione completata con successo!")
