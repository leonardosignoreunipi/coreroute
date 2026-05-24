import rustworkx as rx
import random
import json
import sys

def generate_sdn_topology(num_routers=30, num_hosts=10, num_flows=1, filename="topology_stress_test.json"):
    print(f"Generazione topologia in corso...")
    
    # 1. GENERAZIONE RETE CORE (ROUTERS)
    core_graph = rx.barabasi_albert_graph(num_routers, 2)
    #er_graph = rx.undirected_gnp_random_graph(100, 0.05, seed=42)
    #internet_graph = rx.PyGraph.read_edgelist("as-733.txt", delim=" ")
    
    routers = []
    # Mappatura indici rustworkx -> ID stringa (es. 0 -> "r0")
    idx_to_id = {}
    
    for i in core_graph.node_indices():
        router_id = f"r{i}"
        routers.append({"id": router_id, "qtime": 1.0})
        idx_to_id[i] = router_id

    # 2. GENERAZIONE DEGLI HOSTS
    hosts = []
    # Aggiungiamo gli host come nuovi nodi nel grafo di rustworkx per calcolare i percorsi
    for i in range(num_hosts):
        host_id = f"h{i}"
        service_id = f"s{i}"
        hosts.append({"id": host_id, "services": [service_id]})
        
        # Scegliamo un router casuale a cui collegare l'host (Edge Router)
        target_router_idx = random.randint(0, num_routers - 1)
        
        # Aggiungiamo l'host al grafo
        new_host_idx = core_graph.add_node(host_id)
        idx_to_id[new_host_idx] = host_id
        
        # Colleghiamo l'host al router nel grafo (senza payload per ora)
        core_graph.add_edge(new_host_idx, target_router_idx, None)

    # 3. ESTRAZIONE E FORMATAZIONE DEI LINKS
    links = []
    for u, v in core_graph.edge_list():
        src_id = idx_to_id[u]
        dst_id = idx_to_id[v]
        
        # Se è un collegamento host-router, diamo molta banda (nessun collo di bottiglia locale)
        if src_id.startswith('h') or dst_id.startswith('h'):
            bw = num_flows * 2048
            length = 1.0
        else:
            # LINK CORE (Router -> Router)
            # Scaliamo realisticamente in base al carico della simulazione
            if num_flows <= 20:
                # Simulazione Piccola: Link da 2, 4 e 10 Gbps
                bw = random.choice([2048.0, 4096.0, 10000.0])
            elif num_flows <= 150:
                # Simulazione Media: Backbone da 40 Gbps e 100 Gbps
                bw = random.choice([40000.0, 100000.0])
            else:
                # Simulazione Massiva (1000+ flussi): Backbone Ultra-Broadband (100G / 400G)
                bw = random.choice([100000.0, 400000.0])
            length = float(random.randint(1, 3))
            
        links.append({
            "src": src_id,
            "dst": dst_id,
            "bw": bw,
            "length": length
        })

    # 4. GENERAZIONE FLUSSI E PRE-ASSEGNAZIONE PATHS (STATO ZERO)
    flows = []
    paths = []
    routings = []
    
    for i in range(num_flows):
        flow_id = f"f{i}"
        
        # Selezioniamo sorgente e destinazione distinte
        src_host_idx = random.randint(0, num_hosts - 1)
        dst_host_idx = random.randint(0, num_hosts - 1)
        while src_host_idx == dst_host_idx:
            dst_host_idx = random.randint(0, num_hosts - 1)
            
        # Calcoliamo gli indici esatti in rustworkx (gli host partono da num_routers)
        rx_src = num_routers + src_host_idx
        rx_dst = num_routers + dst_host_idx
        
        src_id = idx_to_id[rx_src]
        dst_id = idx_to_id[rx_dst]
        
        flows.append({
            "id": flow_id,
            "src_service": hosts[src_host_idx]["services"][0],
            "dst_service": hosts[dst_host_idx]["services"][0],
            "max_latency": 150.0,
            "rate": float(random.randint(1, 4))
        })
        
        path_id = f"p_{flow_id}_init"
        paths.append({"id": path_id, "src": hosts[src_host_idx]["id"], "dst": hosts[dst_host_idx]["id"], "nodes": []})
        routings.append({"flow_id": flow_id, "path_id": path_id})

    # 5. SALVATAGGIO IN JSON
    topology = {
        "constants": {
            "SPEED_OF_LIGHT": 300000.0,
            "PCKT_SIZE": 256.0
        },
        "flows": flows,
        "routers": routers,
        "hosts": hosts,
        "links": links,
        "paths": paths,
        "routings": routings
    }

    with open(filename, 'w') as f:
        json.dump(topology, f, indent=2)
        
    print(f"Finito! Topologia '{filename}' generata con successo.")
    print(f"Risultato: {len(routers)} Routers, {len(hosts)} Hosts, {len(flows)} Flussi, {len(links)} Links.")

# --- ESECUZIONE ---
if __name__ == "__main__":
    # Puoi giocare con questi parametri per generare topologie microscopiche o gigantesche

    if len(sys.argv) == 5:
        num_routers = int(sys.argv[1])
        num_hosts = int(sys.argv[2])
        num_flows = int(sys.argv[3])
        filename = sys.argv[4]
    else:
        print("Usage: python generate_topology.py <num_routers> <num_hosts> <num_flows> <filename>")
        sys.exit(0)
    
    generate_sdn_topology(
        num_routers,
        num_hosts,
        num_flows,
        filename
    )