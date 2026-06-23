import rustworkx as rx
import random
import json
import sys
import math
import logging

logger = logging.getLogger(__name__)

class GenerateTopologyError(Exception):
    pass

def generate_sdn_topology(graph_type=None, num_routers=None, num_hosts=None, num_flows=None, filename=None, seed=None):
    if graph_type is None or num_routers is None or num_hosts is None or num_flows is None or filename is None:
        raise GenerateTopologyError("Missing required parameters for topology generation.")

    if seed is not None:
        random.seed(seed)

    logger.info(f"Generating {graph_type} topology with {num_routers} routers...")

    if graph_type == "ba":
        m = max(1, int(math.log2(num_routers)))
        core_graph = rx.barabasi_albert_graph(num_routers, m, seed=seed)
        while not rx.is_connected(core_graph):
            core_graph = rx.barabasi_albert_graph(num_routers, m)
    elif graph_type == "er":
        p_er = 6 / (num_routers - 1)
        core_graph = rx.undirected_gnp_random_graph(num_routers, p_er, seed=seed)
        while not rx.is_connected(core_graph):
            core_graph = rx.undirected_gnp_random_graph(num_routers, p_er)
    elif graph_type == "iaag":
        try:
            import networkx as nx
        except ImportError:
            raise GenerateTopologyError("networkx is required for 'iaag'. Install with: pip install networkx")
        G_nx = nx.powerlaw_cluster_graph(num_routers, m=3, p=0.1, seed=seed)
        while not nx.is_connected(G_nx):
            G_nx = nx.powerlaw_cluster_graph(num_routers, m=3, p=0.1)
        core_graph = rx.PyGraph()
        nx_to_rx = {}
        for node in sorted(G_nx.nodes()):
            nx_to_rx[node] = core_graph.add_node(node)
        for u, v in G_nx.edges():
            core_graph.add_edge(nx_to_rx[u], nx_to_rx[v], None)
    else:
        raise GenerateTopologyError(f"Graph type '{graph_type}' not supported. Use 'er', 'ba', or 'iaag'.")

    idx_to_id = {}
    routers = []
    for i in core_graph.node_indices():
        router_id = f"r{i}"
        routers.append({"id": router_id, "qtime": 0.0})
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

    # Link bandwidths: bw_nominal ~ U(100, 1000) Mbps for router-router links
    # Host-access links get high capacity so they never constrain routing
    links = []
    for u, v in core_graph.edge_list():
        src_id = idx_to_id[u]
        dst_id = idx_to_id[v]
        if src_id.startswith('h') or dst_id.startswith('h'):
            bw = 10000.0
            bw_nominal = 10000.0
            length = 1.0
        else:
            bw_nominal = float(random.uniform(100.0, 1000.0))
            bw = bw_nominal
            length = float(random.randint(1, 10))
        links.append({"src": src_id, "dst": dst_id, "bw": bw, "bw_nominal": bw_nominal, "length": length})

    # Flows: random host pairs, rate ~ U(1, 50) (with pckt_size=1 → required_bw = rate)
    flows = []
    paths = []
    routings = []
    for i in range(num_flows):
        flow_id = f"f{i}"
        src_idx = random.randint(0, num_hosts - 1)
        valid_dst = [j for j in range(num_hosts) if j != src_idx]
        dst_idx = random.choice(valid_dst)
        flows.append({
            "id": flow_id,
            "src_service": hosts[src_idx]["services"][0],
            "dst_service": hosts[dst_idx]["services"][0],
            "max_latency": 1e9,
            "rate": float(random.uniform(1.0, 50.0))
        })
        path_id = f"p_{flow_id}_init"
        paths.append({"id": path_id, "src": hosts[src_idx]["id"], "dst": hosts[dst_idx]["id"], "nodes": []})
        routings.append({"flow_id": flow_id, "path_id": path_id})

    topology = {
        "constants": {
            "SPEED_OF_LIGHT": 300000.0,
            "PCKT_SIZE": 1.0
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

    logger.info(f"Done: '{filename}' — {len(routers)} routers, {len(hosts)} hosts, {len(flows)} flows, {len(links)} links.")


if __name__ == "__main__":
    if len(sys.argv) == 6:
        generate_sdn_topology(
            graph_type=sys.argv[1],
            num_routers=int(sys.argv[2]),
            num_hosts=int(sys.argv[3]),
            num_flows=int(sys.argv[4]),
            filename=sys.argv[5],
        )
    else:
        print("Usage: python build_topology.py <graph_type> <num_routers> <num_hosts> <num_flows> <filename>")
        sys.exit(0)
