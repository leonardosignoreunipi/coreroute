from ConfigLoader import ConfigLoader
from PhysicalNetwork import PhysicalNetwork as Net
from RoutingEngine import RoutingEngine as Engine
from JanusKB import JanusKB as PrologKB
import sys


class SDNcontroller:
    def __init__(self, network: Net, kb: PrologKB, config: ConfigLoader, engine: Engine):
        self.network = network
        self.kb = kb
        self.config = config
        self.engine = engine

    def run(self):
        self.kb.initialize_kb()
        
        for flow in self.config.flows.values():
            print(f"flusso {flow.id}: src: {flow.src_service} dst: {flow.dst_service} max_latency: {flow.max_latency} rate: {flow.rate}")
        
        routings = self.kb.get_routings()
        for d in routings:
            flow_id = self.config.flows[d['FlowId']].id
            nodes = self.config.paths[d['PathId']].nodes
            print(f"{flow_id} -> {nodes}")
        
        okflows, koflows = self.engine.get_partition()
        print(f"\nOkflows: {okflows}\nKoflows: {koflows}\n")
        
        newValidRoutings = self.engine.cr_routing(okflows, koflows)
        print(f"\n\nNewValidRoutings: {newValidRoutings}")
            
        self.kb.update_janus_kb(newValidRoutings)
        #self.draw_topology()

    def continuos_reasoning(self):
        """
        Esegue il reasoning continuo del sistema SDN.
        1) okflows, koflows partition
        2) newvalidroutings from okflows, koflows
        3) update janus kb
        4) misuro quanti routing validi ottengo
        return newvalidroutings
        """
        ok_flows, ko_flows = [], []
        ok_flows, ko_flows = self.engine.get_partition()
        print(f"\n[*] Partition ottenuta: {len(ok_flows)} ok_flows, {len(ko_flows)} ko_flows.")

        new_valid_routings = self.engine.cr_routing(ok_flows, ko_flows)
        self.kb.update_janus_kb(new_valid_routings)
        
        temp_ok_flows, temp_ko_flows = self.engine.get_partition()
        print(f"[*] New valid routings: "f"{len(new_valid_routings)}. Nuova partition: {len(temp_ok_flows)} ok_flows, {len(temp_ko_flows)} ko_flows.")
        
        return new_valid_routings
        

    def draw_topology(self, save_path=None):
        """
        Disegna l'intera topologia di rete usando matplotlib.
        Distingue visivamente Host (Verdi) e Router (Azzurri), 
        mostra la banda e colora in modo evidente i percorsi di routing attivi.
        """
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches # Serve per creare la legenda
        from rustworkx.visualization import mpl_draw

        newRoutings = self.kb.get_routings()
        
        # 1. Raccogliamo tutti gli archi (link) che fanno parte dei nuovi routing
        active_edges = set()
        for d in newRoutings:
            flow_id = d['FlowId']
            nodes = self.kb.get_path(d['PathId'])
            print(f"{flow_id} -> {nodes}")
            
            # Scorriamo i nodi del path a due a due per estrarre l'arco (u, v)
            for i in range(len(nodes) - 1):
                u, v = nodes[i], nodes[i+1]
                # Aggiungiamo l'arco in entrambe le direzioni perché visivamente il grafo non è orientato
                active_edges.add((u, v))
                active_edges.add((v, u))

        # 2. Definiamo i colori dei nodi in base al 'type'
        node_colors = []
        for node_idx in self.network.graph.node_indices():
            node_data = self.network.graph.get_node_data(node_idx)
            if node_data.get("type") == "Host":
                node_colors.append('#90EE90')  # Verde chiaro per gli Host
            else:
                node_colors.append('#ADD8E6')  # Azzurro per i Router

        # 3. Definiamo i colori e gli spessori degli ARCHI (Link)
        edge_colors = []
        edge_widths = []
        
        # Scorriamo tutti gli archi fisici del grafo di rustworkx
        for u_idx, v_idx in self.network.graph.edge_list():
            # I nodi in rustworkx sono indici interi, li convertiamo in stringhe ('r1', 'h2') 
            # usando la mappa inversa che hai nella classe PhysicalNetwork
            u_id = self.network.inv_node_map[u_idx]
            v_id = self.network.inv_node_map[v_idx]
            
            # Se questo arco fisico fa parte di almeno un percorso di routing...
            if (u_id, v_id) in active_edges:
                edge_colors.append('#FF4500') # Colore Rosso/Arancio (OrangeRed) per i link attivi
                edge_widths.append(4.0)       # Link più spesso per evidenziarlo
            else:
                edge_colors.append('#D3D3D3') # Grigio chiaro per i link inattivi/vuoti
                edge_widths.append(1.0)       # Link più sottile

        # 4. Creiamo il canvas di matplotlib
        plt.figure(figsize=(14, 10))

        # 5. Disegniamo il grafo passando le nuove liste
        mpl_draw(
            self.network.graph,
            with_labels=True,
            # Estrae l'ID per scriverlo dentro il nodo (es. 'h1', 'r5')
            labels=lambda node: str(node.get("id", "")), 
            # Estrae Banda per scriverla sopra l'arco
            edge_labels=lambda edge: f"{edge.get('bw', 0)}",
            node_color=node_colors,
            node_size=1800,
            font_size=11,
            font_weight="bold",
            font_color="black",
            edge_color=edge_colors, # <--- Passiamo la lista dinamica dei colori degli archi
            width=edge_widths       # <--- Passiamo la lista dinamica degli spessori
        )

        plt.title("Topologia SDN - Percorsi Attivati dal Controller", fontsize=18, fontweight='bold')
        
        # Aggiungiamo una legenda in alto a sinistra
        legend_handles = [
            mpatches.Patch(color='#FF4500', label='Link Attivi (Attraversati da Flussi)'),
            mpatches.Patch(color='#D3D3D3', label='Link Inattivi (Senza traffico)')
        ]
        plt.legend(handles=legend_handles, loc='upper left', fontsize=12)
        
        # 6. Opzione per salvare il grafico (utile per la tesi)
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"Topologia salvata con successo in: {save_path}")
            
        plt.show()

def __main__():
    if len(sys.argv) == 2:
        topology_file = sys.argv[1]
    else:
        print("Usage: python SDNcontroller.py <topology_file>")
        sys.exit(1)

    config = ConfigLoader(topology_file).load()
    network = Net(config)
    kb = PrologKB(config, "routing_core.pl")
    engine = Engine(network, kb, config)
    controller = SDNcontroller(network, kb, config, engine)
    controller.run()

if __name__ == "__main__":
    __main__()