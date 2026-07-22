import networkx as nx
import random
import json
import sys
import math
import logging

logger = logging.getLogger(__name__)

# Realistic parameter set (metro/enterprise SDN scenario). What governs benchmark
# behaviour is the flow-demand / link-capacity RATIO (Dtrasm = required_bw/bw,
# contention, pruning): capacities and rates are scaled by the same x10 factor
# w.r.t. the exploratory runs, so contention and latency distributions are
# unchanged while absolute values match modern hardware.

# ER/BA
HOST_FRACTION = 0.10 # 10% of the total nodes are hosts, the rest are routers (modeling choice: hosts are aggregated service attachment points, the focus is the router core).
ROUTER_BW = (1000.0, 10000.0) # Router-router link bandwidth range (Mbps): 1-10 Gbps core links, modern metro/enterprise standard.

# ER/BA/IAAG
ACCESS_BW = 100000.0 # host-access link capacity (Mbps): 100 Gbps server/DC NIC, over-provisioned by design so access links never constrain routing.
PCKT_RATE = (1000.0, 40000.0) # packets/s per flow (min, max); required_bw = PCKT_SIZE * PCKT_RATE = 12-480 Mbps (HD/4K video up to elephant flows). 480 Mbps at 1500 B/pckt is exactly 40000 pkt/s.
MAX_LATENCY_RANGE = (0.05, 0.15) # per-flow max tolerable latency (s), drawn uniform: 50-150 ms, a realistic SLA for interactive/video services. NOT a binding constraint in this regime, and deliberately so: verified 22/07/2026 with a paired test (real SLA vs infinite SLA over the same perturbation sequence -> identical failure counts on all three topologies at pct=0.5, 12 epochs). With 1-10 Gbps links and 12-480 Mbps flows, checkBandwidthPath rejects congested paths long before queueing becomes significant, so capacity always binds first. Kept because it is part of the model and satisfied with margin: nominal P99 ~20 ms, zero INIT failures. Do NOT re-tune this to force failures - see CLAUDE.md "Latency model".
RR_LINK_LENGTH = (1, 100) # length range (min, max) for router-router link (km): metro/regional backbone.
ACCESS_LINK_LENGTH = 1.0 # host-router link length (km): campus/DC access span.
QTIME = 0.002 # router queueing delay (s): 2 ms per hop, typical value.
SPEED_OF_LIGHT = 200000.0 # km/s: light in fiber (n~1.5), i.e. 5 us/km.
PCKT_SIZE = 0.012 # packet size (Mb): 1500-byte Ethernet MTU frame. It's possible to set a PCKT_SIZE per flow.

# IAAG: link bandwidth range (Mbps) keyed by the unordered pair of endpoint tiers.
# Node tiers come from networkx.random_internet_as_graph:
#   T  = transit / tier-1, M = mid-level, CP = content provider, C = customer.
# Hierarchical scale: tier-1 backbone 10-100 Gbps, aggregation 2-20 Gbps.
IAAG_BW_TIERS = {
    frozenset({"T", "T"}):   (10000.0, 100000.0),
    frozenset({"T", "CP"}):  (10000.0, 50000.0),
    frozenset({"CP", "CP"}): (10000.0, 50000.0),
    frozenset({"T", "M"}):   (5000.0, 20000.0),
    frozenset({"M", "CP"}):  (5000.0, 20000.0),
    frozenset({"M", "M"}):   (2000.0, 10000.0),
}


class GenerateTopologyError(Exception):
    """Custom exception for topology generation errors."""
    pass


def _iaag_link_bw(type_u, type_v):
    """Bandwidth (Mbps) for an IAAG link, drawn from the range of its tier pair."""
    lo, hi = IAAG_BW_TIERS.get(frozenset({type_u, type_v}), ROUTER_BW)
    return float(random.uniform(lo, hi))


def generate_sdn_topology(graph_type=None, num_nodes=None, num_flows=None, filename=None, seed=None):
    
    """
    Generate a synthetic SDN topology and write it to `filename` as JSON.

    Three graph models are supported via `graph_type`:
      - "er":   Erdős-Rényi G(n, p) router core (p = log2(R)/R), regenerated until
                connected; ~HOST_FRACTION of the nodes are hosts, the rest routers.
      - "ba":   Barabási-Albert scale-free router core (m = log2(R)); same host split.
      - "iaag": networkx.random_internet_as_graph, a hierarchical AS model where
                customer (C) nodes become hosts and T/M/CP nodes become routers, so
                the host/router split emerges from the model (~75-80% hosts).

    In every model each host attaches to the router core, link bandwidths are set by
    role/tier (host-access links are over-provisioned so they never constrain
    routing), and `bw_nominal` stores the pristine bandwidth used to restore links
    after a perturbation. Flows connect random distinct host pairs; each flow is
    seeded with an empty "init" path and matching routing, so the controller starts
    with all flows unrouted (KO) — the baseline state the benchmark perturbs from.

    Args:
        graph_type: "er", "ba" or "iaag".
        num_nodes:  total number of nodes (hosts + routers) requested.
        num_flows:  number of flows to generate.
        filename:   output path for the topology JSON.
        seed:       RNG seed; makes the generated topology reproducible.

    Raises:
        GenerateTopologyError: missing arguments, unsupported graph_type, node count
        too small to split, a missing IAAG node tier, or fewer than two hosts.
    """
    
    if graph_type is None or num_nodes is None or num_flows is None or filename is None or seed is None:
        raise GenerateTopologyError("Missing required parameters for topology generation.")

    random.seed(seed)

    logger.info(f"Generating {graph_type} topology with {num_nodes} total nodes...")

    if graph_type in ("ba", "er"):
        
        num_hosts = max(2, round(HOST_FRACTION * num_nodes))
        num_routers = num_nodes - num_hosts
        
        if num_routers < 1:
            logger.error(f"num_nodes={num_nodes} too small for a valid ER/BA split.")
            raise GenerateTopologyError(f"num_nodes={num_nodes} too small for a valid ER/BA split.")

        if graph_type == "ba":
            m = max(1, int(math.log2(num_routers)))
            core_graph = nx.barabasi_albert_graph(num_routers, m, seed=seed)
            attemp = 1
            while not nx.is_connected(core_graph):
                logger.warning(f"Seed {seed} not connected (BA), retrying")
                core_graph = nx.barabasi_albert_graph(num_routers, m, seed=seed + attemp)
                attemp += 1
        else:
            p_er = math.log2(num_routers) / num_routers
            core_graph = nx.gnp_random_graph(num_routers, p_er, seed=seed)
            attemp = 1
            while not nx.is_connected(core_graph):
                logger.warning(f"Seed {seed} not connected (ER), retrying")
                core_graph = nx.gnp_random_graph(num_routers, p_er, seed=seed + attemp)
                attemp += 1

        # relabel integer router nodes 0..num_routers-1 to "r{i}" string ids
        core_graph = nx.relabel_nodes(core_graph, {i: f"r{i}" for i in core_graph.nodes()})
        routers = [{"id": f"r{i}", "qtime": QTIME} for i in range(num_routers)]

        # Attach each host to one random router via a high-capacity access link.
        # Host nodes keep their string id ("h{i}"); routers were relabelled to "r{i}" above.
        hosts = []
        for i in range(num_hosts):
            host_id = f"h{i}"
            hosts.append({"id": host_id, "services": [f"s{i}"]})
            target_router = f"r{random.randint(0, num_routers - 1)}"
            core_graph.add_node(host_id)
            core_graph.add_edge(host_id, target_router)

        # Link bandwidths: router-router ~ U(100, 1000) Mbps; host-access links get
        # high capacity so they never constrain routing.
        links = []
        for src_id, dst_id in core_graph.edges:
            if src_id.startswith('h') or dst_id.startswith('h'):
                bw = ACCESS_BW
                length = ACCESS_LINK_LENGTH
            else:
                bw = float(random.uniform(*ROUTER_BW))
                length = float(random.randint(*RR_LINK_LENGTH))
            links.append({"src": src_id, "dst": dst_id, "bw": bw, "bw_nominal": bw, "length": length})

    elif graph_type == "iaag":
        # Natural AS model: generate exactly num_nodes nodes; customer (C) nodes become
        # hosts, infrastructure (T/M/CP) nodes become routers. The split emerges from
        # the model (~75-80% hosts) rather than being imposed.
        G_nx = nx.random_internet_as_graph(num_nodes, seed=seed)
        attemp = 1
        while not nx.is_connected(G_nx):
            logger.warning(f"Seed {seed} not connected (IAAG), retrying")
            G_nx = nx.random_internet_as_graph(num_nodes, seed=seed + attemp)
            attemp += 1

        node_id = {}     # nx node -> id string ("h*" / "r*")
        node_type = {}   # id string -> AS tier ("T" / "M" / "CP" / "C")
        routers = []
        hosts = []
        r_count = 0
        h_count = 0
        for n, attr in sorted(G_nx.nodes(data = True)):
            try:
                tier = attr["type"]
            except KeyError: 
                logger.error(f"Node {n} in the IAAG topology is missing the 'type' attribute.")
                raise GenerateTopologyError(f"Failed to generate IAAG topology: Node {n} lacks the required 'type' attribute.")
            if tier == "C":
                host_id = f"h{h_count}"
                hosts.append({"id": host_id, "services": [f"s{h_count}"]})
                node_id[n] = host_id
                node_type[host_id] = tier
                h_count += 1
            else:
                router_id = f"r{r_count}"
                routers.append({"id": router_id, "qtime": QTIME})
                node_id[n] = router_id
                node_type[router_id] = tier
                r_count += 1

        if len(hosts) < 2:
            raise GenerateTopologyError(
                f"IAAG topology produced {len(hosts)} customer nodes; need at least 2 hosts for flows."
            )

        # Link bandwidths depend on the tier pair of the endpoints (backbone high,
        # customer access low).
        links = []
        for u, v in G_nx.edges():
            src_id = node_id[u]
            dst_id = node_id[v]
            if src_id.startswith('h') or dst_id.startswith('h'):
                bw = ACCESS_BW                                 
                length = ACCESS_LINK_LENGTH
            else:
                bw = _iaag_link_bw(node_type[src_id], node_type[dst_id])
                length = float(random.randint(*RR_LINK_LENGTH))
            links.append({"src": src_id, "dst": dst_id, "bw": bw, "bw_nominal": bw, "length": length})

    else:
        raise GenerateTopologyError(f"Graph type '{graph_type}' not supported. Use 'er', 'ba', or 'iaag'.")

    # Flows + initial (empty) routing state.
    # Each flow links a random distinct pair of hosts and requests a rate drawn from
    # PCKT_RATE (with PCKT_SIZE=1 the required bandwidth equals the rate).
    # Every flow is bound to an empty "init" path, so the controller starts with all
    # flows KO (unrouted) — the baseline the benchmark perturbs and reroutes from.
    num_hosts = len(hosts)
    flows = []
    routings = []
    paths = [{"id": "p_init", "src": "none", "dst": "none", "nodes": []}]
    for i in range(num_flows):
        flow_id = f"f{i}"
        src_idx = random.randint(0, num_hosts - 1)
        valid_dst = [j for j in range(num_hosts) if j != src_idx]
        dst_idx = random.choice(valid_dst)
        flows.append({
            "id": flow_id,
            "src_service": hosts[src_idx]["services"][0],
            "dst_service": hosts[dst_idx]["services"][0],
            "max_latency": float(random.uniform(*MAX_LATENCY_RANGE)),
            "rate": float(random.uniform(*PCKT_RATE))
        })
        # Use "_init" suffix to prevent naming collisions with paths generated
        # during the rerouting phase (which use the format p_1, p_2, etc.).
        routings.append({"flow_id": flow_id, "path_id": "p_init"})

    topology = {
        "constants": {
            "SPEED_OF_LIGHT": SPEED_OF_LIGHT,
            "PCKT_SIZE": PCKT_SIZE
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
            num_nodes=int(sys.argv[2]),
            num_flows=int(sys.argv[3]),
            filename=sys.argv[4],
            seed=int(sys.argv[5])
        )
    else:
        print("Usage: python build_topology.py <graph_type> <num_nodes> <num_flows> <filename> <seed>")
        sys.exit(0)
