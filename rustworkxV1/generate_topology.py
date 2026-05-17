import rustworkx as rx
import random
import json

def generate_sdn_topology(num_routers=30, num_hosts=10, num_flows=1, filename="topology_stress_test.json"):
    print(f"Generazione topologia in corso...")
    
    # 1. GENERAZIONE RETE CORE (ROUTERS)
    # Usiamo Barabasi-Albert: crea reti scale-free simili a Internet. 
    # Il parametro '2' indica che ogni nuovo router si collega a 2 router esistenti.
    core_graph = rx.barabasi_albert_graph(num_routers, 2)
    
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
            bw = 10000.0
            length = 1.0
        else:
            # Se è un collegamento router-router, la banda varia per creare colli di bottiglia
            bw = random.choice([512.0, 1024.0, 2048.0, 4096.0])
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
        
        # Calcoliamo il percorso iniziale per questo flusso
        try:
            # Calcolo dei cammini minimi (hop count) dalla sorgente
            paths_from_src = rx.dijkstra_shortest_paths(core_graph, rx_src, target=rx_dst)
            
            # Estraiamo l'array di nodi per la nostra destinazione
            path_indices = paths_from_src[rx_dst]
            path_nodes = [idx_to_id[idx] for idx in path_indices]
            
            path_id = f"p_{flow_id}_init"
            
            paths.append({
                "id": path_id,
                "src": src_id,
                "dst": dst_id,
                "nodes": path_nodes
            })
            
            routings.append({
                "flow_id": flow_id,
                "path_id": path_id
            })
            
        except KeyError:
            print(f"Attenzione: Nessun percorso possibile tra {src_id} e {dst_id}")

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
    generate_sdn_topology(
        num_routers=2**10,
        num_hosts=2,
        num_flows=3,
        filename="massive_topology.json"
    )