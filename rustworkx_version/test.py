import sys
import time
import random
from SDNcontroller import SDNcontroller
from ConfigLoader import ConfigLoader
from PhysicalNetwork import PhysicalNetwork as Net
from RoutingEngine import RoutingEngine as Engine
from JanusKB import JanusKB as PrologKB

class Test: 
    def __init__(self, sdn_controller: SDNcontroller):
        self.sdn_controller = sdn_controller
        
    def perturbation(self, p_guasto):
        """
        Simula congestione o degrado sui link router-router con probabilità p_guasto.
        Riduciamo la banda nominale in modo casuale [0.2, 0.7] e aggiorniamo Grafo e KB.
        Ritorna il numero di link degradati.
        """
        graph = self.sdn_controller.network.graph
        edges = graph.edge_indices()
        degraded_links_rx = []

        for edge_idx in edges:
            u, v = graph.get_edge_endpoints_by_index(edge_idx)
            u_id = self.sdn_controller.network.inv_node_map[u]
            v_id = self.sdn_controller.network.inv_node_map[v]

            if u_id.startswith('h') or v_id.startswith('h'): 
                continue
                
            if random.random() < p_guasto:
                edge_data = graph.get_edge_data_by_index(edge_idx)
                
                current_bw = edge_data['bw'] 
                retention_factor = random.uniform(0.2, 0.7) 
                new_bw = current_bw * retention_factor
                
                edge_data['bw'] = new_bw
                graph.update_edge_by_index(edge_idx, edge_data)
                
                try:
                    n1 = graph[u]
                    n2 = graph[v]
                    degraded_links_rx.append((n1['id'], n2['id'], new_bw))
                except IndexError:
                    print(f"Errore: node not found {u} or {v}.")

        # update KB with new bandwidths
        updated_links = self.sdn_controller.kb.update_links_bandwidth(degraded_links_rx)

        print(f"[*] Perturbazione applicata: {len(degraded_links_rx)} link degradati nel grafo, {updated_links} aggiornati nella KB.")
        return len(degraded_links_rx)


def main():   
    if len(sys.argv) < 2: 
        print("Usage: python test.py <topology_file>")
        sys.exit(1)
        
    topology_file = sys.argv[1]
    kb_file = "routing_core.pl"
    p_guasto = 0.3

    print("[1] Inizializzazione componenti in corso...")
    config = ConfigLoader(topology_file).load()
    network = Net(config)
    kb = PrologKB(config, kb_file)
    engine = Engine(network, kb, config)
    
    controller = SDNcontroller(network, kb, config, engine)
    controller.kb.initialize_kb()

    tester = Test(controller)
    
    print("[2] Inizializzazione path (Stato 0)...")
    start = time.time()
    tester.sdn_controller.continuos_reasoning() 
    end = time.time()
    
    nocr_time = end - start
    
    print(f"[3] Esecuzione perturbazione ({p_guasto}% di guasto)...")
    tester.perturbation(p_guasto)

    print("[4] Ricalcolo percorsi (Continuous Reasoning)...")
    start = time.time() 
    tester.sdn_controller.continuos_reasoning()
    end = time.time()   

    cr_time = end - start

    num_edges = len(tester.sdn_controller.network.graph.edge_list())
    num_nodes = len(tester.sdn_controller.network.graph.node_indices())
    num_flows = len(tester.sdn_controller.config.flows)
    
    print(f"\n✅ Test completato. Tempo non CR: {nocr_time:.4f} secondi | Tempo CR: {cr_time:.4f} secondi")
    print(f"📊 Nodi: {num_nodes} | Archi rimanenti: {num_edges} | Flussi: {num_flows}")
    
    return (num_edges, num_nodes, num_flows, cr_time)
        
if __name__ == "__main__":
    main()