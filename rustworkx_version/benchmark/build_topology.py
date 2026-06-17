import rustworkx as rx
import random
import json
import sys
import logging

# Worst-case required bandwidth per flow: max_rate * pckt_size = 4 * 256 = 1024 units
MAX_FLOW_BW = 4 * 256
# Worst-case perturbation retention factor (test.py degrades links by 0.2–0.7×)
MIN_RETENTION = 0.2
# Minimum link bandwidth so the graph stays routable after worst-case perturbation
MIN_LINK_BW = MAX_FLOW_BW / MIN_RETENTION  # = 5120

logger = logging.getLogger(__name__)

class GenerateTopologyError(Exception):
    """Custom exception for errors in topology generation."""
    pass

def generate_sdn_topology(graph_type = None, num_routers=None, num_hosts=None, num_flows=None, filename=None):
    
    if graph_type is None or num_routers is None or num_hosts is None or num_flows is None or filename is None:
        raise GenerateTopologyError("Missing required parameters for topology generation.")
    
    logger.info(f"Generazione topologia {graph_type} in corso...")

    if graph_type == "ba":
        core_graph = rx.barabasi_albert_graph(num_routers, 2)
    elif graph_type == "er":
        # p is chosen to keep edges manageable for Prolog (target ~2-4K max).
        # ER edges grow as n²·p/2, so p must shrink with n.
        # Floor: p > ln(n)/n (connectivity threshold); we stay ~2-3× above it.
        if num_routers <= 32:
            p_er = 0.15   # ~74 edges
        elif num_routers <= 128:
            p_er = 0.05   # ~406 edges
        elif num_routers <= 256:
            p_er = 0.03   # ~981 edges
        else:             # 512
            p_er = 0.015  # ~1966 edges  (threshold≈0.012, ratio≈1.25 → retry loop handles disconnected)
        core_graph = rx.undirected_gnp_random_graph(num_routers, p_er)
        while not rx.is_connected(core_graph):
            core_graph = rx.undirected_gnp_random_graph(num_routers, p_er)
    elif graph_type == "iaag":
        # Holme-Kim powerlaw cluster graph: scale-free degree distribution +
        # high clustering coefficient, closely matching real internet AS topology.
        # m=3 edges per new node; p=0.5 probability of triangle formation.
        try:
            import networkx as nx
        except ImportError:
            raise GenerateTopologyError(
                "networkx is required for 'iaag' topology. Install with: pip install networkx"
            )
        m_hk, p_hk = 3, 0.5
        G_nx = nx.powerlaw_cluster_graph(num_routers, m_hk, p_hk)
        while not nx.is_connected(G_nx):
            G_nx = nx.powerlaw_cluster_graph(num_routers, m_hk, p_hk)
        core_graph = rx.PyGraph()
        nx_to_rx = {}
        for node in sorted(G_nx.nodes()):
            nx_to_rx[node] = core_graph.add_node(node)
        for u, v in G_nx.edges():
            core_graph.add_edge(nx_to_rx[u], nx_to_rx[v], None)
    else:
        raise GenerateTopologyError("Graph type not supported")

    num_rr_edges = len(core_graph.edge_list())

    routers = []
    idx_to_id = {}

    for i in core_graph.node_indices():
        router_id = f"r{i}"
        routers.append({"id": router_id, "qtime": 1.0})
        idx_to_id[i] = router_id

    hosts = []
    for i in range(num_hosts):
        host_id = f"h{i}"
        service_id = f"s{i}"
        hosts.append({"id": host_id, "services": [service_id]})

        target_router_idx = random.randint(0, num_routers - 1)

        new_host_idx = core_graph.add_node(host_id)
        idx_to_id[new_host_idx] = host_id

        core_graph.add_edge(new_host_idx, target_router_idx, None)

    # 3. LINKS
    avg_path_length = 3.0
    safety = 2.0
    avg_flows_per_link = num_flows * avg_path_length / max(1, num_rr_edges)
    bw_base = max(MIN_LINK_BW, avg_flows_per_link * MAX_FLOW_BW * safety / MIN_RETENTION)
    bw_tiers = [bw_base, bw_base * 3.0, bw_base * 10.0]

    links = []
    for u, v in core_graph.edge_list():
        src_id = idx_to_id[u]
        dst_id = idx_to_id[v]

        # Host-router access links
        if src_id.startswith('h') or dst_id.startswith('h'):
            bw = bw_base * 20.0
            length = 1.0
        else:
            # Router-router links
            bw = float(random.choices(bw_tiers, weights=[0.6, 0.3, 0.1])[0])
            length = float(random.randint(1, 3))

        links.append({
            "src": src_id,
            "dst": dst_id,
            "bw": bw,
            "length": length
        })

    # 4. FLOWS, PATHS, ROUTINGS
    flows = []
    paths = []
    routings = []

    for i in range(num_flows):
        flow_id = f"f{i}"

        src_host_idx = random.randint(0, num_hosts - 1)
        valid_dst_host_idx = [j for j in range(num_hosts) if j != src_host_idx]
        dst_host_idx = random.choice(valid_dst_host_idx)

        rx_src = num_routers + src_host_idx # retrieve the index of the source host in the graph
        rx_dst = num_routers + dst_host_idx

        src_id = idx_to_id[rx_src] # retrieve the string ID of the source host
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

    # 5. SAVE IN JSON
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

    logger.info(f"Finito! Topologia '{filename}' generata con successo.")
    logger.info(f"Risultato: {len(routers)} Routers, {len(hosts)} Hosts, {len(flows)} Flussi, {len(links)} Links.")

# --- ESECUZIONE ---
if __name__ == "__main__":
    if len(sys.argv) == 6:
        graph_type = sys.argv[1]
        num_routers = int(sys.argv[2])
        num_hosts = int(sys.argv[3])
        num_flows = int(sys.argv[4])
        filename = sys.argv[5]
    else:
        print("Usage: python generate_topology.py <graph_type> <num_routers> <num_hosts> <num_flows> <filename>")
        sys.exit(0)

    generate_sdn_topology(
        graph_type,
        num_routers,
        num_hosts,
        num_flows,
        filename
    )
