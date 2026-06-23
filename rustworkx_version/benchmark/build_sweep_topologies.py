import subprocess
import os

cartella_output = "topologies"
os.makedirs(cartella_output, exist_ok=True)

class GeneraTopologieError(Exception):
    """Custom exception for errors in topology generation."""
    pass

RANGE_ROUTERS = [64, 128, 512, 1024, 2048] 
RANGE_FLOWS = [500]
GRAPHS_TYPE = ["er", "ba", "iaag"]

def estimated_edges(gtype, RANGE_ROUTERS):
    """Stima del numero di archi router-router in base al tipo di grafo."""
    if gtype == "ba":
        return 2 * RANGE_ROUTERS
    elif gtype == "er":
        if RANGE_ROUTERS <= 32:   p = 0.15
        elif RANGE_ROUTERS <= 128: p = 0.05
        elif RANGE_ROUTERS <= 256: p = 0.03
        else:                    p = 0.015
        return int(RANGE_ROUTERS * (RANGE_ROUTERS - 1) / 2 * p)
    elif gtype == "iaag":
        return 4 * RANGE_ROUTERS
    return RANGE_ROUTERS

contatore = 1
totale_file = sum(
    1
    for gtype in GRAPHS_TYPE
    for esp in RANGE_ROUTERS
    for _ in RANGE_FLOWS
)

print("Inizio generazione automatica delle topologie...")

for gtype in GRAPHS_TYPE:
    for num_routers in RANGE_ROUTERS:
        for num_flows in RANGE_FLOWS:
            num_hosts = max(4, int(0.1*num_routers))

            filename = f"{cartella_output}/topo_{gtype}_R{num_routers}_H{num_hosts}_F{num_flows}.json"

            if os.path.exists(filename):
                print(f"[{contatore}/{totale_file}] Saltato: {filename} esiste gia'.")
                contatore += 1
                continue

            est_edges = estimated_edges(gtype, num_routers)
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
