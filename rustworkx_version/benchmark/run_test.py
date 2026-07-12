import sys
import time
import random
import json
from pathlib import Path
import logging
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent.parent))

from Debugkb import DebugKB
from SDNcontroller import SDNcontroller
from ConfigLoader import ConfigLoader
from PhysicalNetwork import PhysicalNetwork as Net
from RoutingEngine import RoutingEngine as Engine
from JanusKB import JanusKB as PrologKB


class Test:
    def __init__(self, sdn_controller: SDNcontroller):
        self.sdn_controller = sdn_controller

    def perturbation(self, pct_links: float):
        """Select exactly pct_links fraction of router-router edges and update their
        bandwidth as bw = bw_nominal * r, r ~ U(0.5, 1.5).
        Returns the number of modified links."""
        graph = self.sdn_controller.network.graph
        rr_edges = [
            edge_idx for edge_idx in graph.edge_indices()
            if not self._is_access_link(graph, edge_idx)
        ]

        n_mod = max(1, int(pct_links * len(rr_edges)))
        selected = random.sample(rr_edges, min(n_mod, len(rr_edges)))

        degraded = []
        for edge_idx in selected:
            edge_data = graph.get_edge_data_by_index(edge_idx)
            bw_nominal = edge_data["bw_nominal"]
            r = random.uniform(0.5, 1.5)
            new_bw = bw_nominal * r
            edge_data["bw"] = new_bw
            graph.update_edge_by_index(edge_idx, edge_data)
            degraded.append((edge_data["u"], edge_data["v"], new_bw))

        updated = self.sdn_controller.kb.update_links_bandwidth(degraded)
        print(f"[*] Perturbation: {len(selected)} links modified ({pct_links*100:.0f}% of {len(rr_edges)} rr-links), {updated} updated in KB.")
        return len(selected)

    def _is_access_link(self, graph, edge_idx) -> bool:
        u, v = graph.get_edge_endpoints_by_index(edge_idx)
        u_id = self.sdn_controller.network.inv_node_map[u]
        v_id = self.sdn_controller.network.inv_node_map[v]
        return u_id.startswith('h') or v_id.startswith('h')


def main():
    logging.basicConfig(
        level=logging.WARNING,
        format='[%(asctime)s] %(levelname)s - %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )

    if len(sys.argv) < 2:
        print("Usage: python run_test.py <topology_file> [pct_links]")
        sys.exit(1)

    topology_file = sys.argv[1]
    pct_links = float(sys.argv[2]) if len(sys.argv) > 2 else 0.10
    kb_file = str(Path(__file__).parent.parent / "routing_core.pl")

    config = ConfigLoader(topology_file).load()
    network = Net(config)
    kb = PrologKB(config, kb_file)
    dkb = DebugKB(kb)
    engine = Engine(network, kb, config)
    controller = SDNcontroller(network, kb, config, engine)
    controller.kb.initialize_kb()

    num_nodes = network.graph.num_nodes()
    num_edges = network.graph.num_edges()
    num_flows = len(config.flows)
    logger.debug(f"[1] Topology loaded: {num_nodes} nodes, {num_edges} edges, {num_flows} flows.")

    dkb.saves_snapshot_kb("\n\nSnapshot kb before Init\n\n")

    # --- [STEP 1] Init: CR routing with all flows KO (= full recompute on clean state) ---
    logger.debug("[2] Init routing (all flows KO → full recompute)...")
    newRoutings, n_ko, n_rr = controller.full_recompute()
    logger.debug(f"START ROUTING {len(newRoutings)} valid routings, {n_ko} KO flows, {n_rr} rerouted.")

    dkb.saves_snapshot_kb("\n\nSnapshot kb after Init before perturbation\n\n")

    # --- [STEP 2] Perturbation ---
    logger.debug(f"[3] Applying perturbation ({pct_links*100:.0f}% of router-router links)...")
    tester = Test(controller)
    n_modified = tester.perturbation(pct_links)

    # --- [STEP 3] CR: only re-route KO flows (continuous reasoning) ---
    logger.debug("[4] Continuous Reasoning step...")
    t0 = time.perf_counter()
    _, n_ko, n_r = controller.continuous_reasoning()
    t_cr = time.perf_counter() - t0
    logger.debug(f"    CR done in {t_cr:.4f}s  |  KO flows: {n_ko}  |  rerouted: {n_r}")

    dkb.saves_snapshot_kb("Snapshot kb after CR before full recompute")

    # --- [STEP 4] Full Recompute: route ALL flows from scratch on perturbed network ---
    logger.debug("[5] Full Recompute step (all flows reset to KO)...")
    t0 = time.perf_counter()
    _, n_full_ko, n_full_rr = controller.full_recompute()
    t_full = time.perf_counter() - t0
    logger.debug(f"    Full Recompute done in {t_full:.4f}s  |  flows rerouted: {n_full_ko}")

    dkb.saves_snapshot_kb("Snapshot kb after full recompute")

    speedup = t_full / t_cr if t_cr > 0 else float('inf')
    pkt_ko = n_ko / num_flows if num_flows > 0 else 0.0
    pr = n_r / num_flows if num_flows > 0 else 0.0

    #print(f"\n✅ Results:")
    logger.debug(f"   T_CR={t_cr:.6f}s  T_FULL={t_full:.6f}s  Speedup={speedup:.2f}x")
    logger.debug(f"   N_KO={n_ko}  N_R={n_r} ")
    logger.debug(f"   N_FULL_KO = {n_full_ko} N_FULL_RR = {n_full_rr}")
    #print(f"RESULTDATA:{num_edges},{num_nodes},{num_flows},{t_cr:.6f},{t_full:.6f},{n_ko},{n_full_ko},{n_modified}, {n_full_ko}, {n_full_rr}")


    res = {
        "num_edges": num_edges,
        "num_nodes": num_nodes,
        "num_flows": num_flows,
        "t_cr": t_cr,
        "t_full": t_full,
        "n_ko": n_ko,
        "n_r": n_r,
        "n_full_ko": n_full_ko,
        "n_full_rr": n_full_rr,
        "n_modified": n_modified,
    }    

    return res


if __name__ == "__main__":
    logger.setLevel(logging.DEBUG)
    res = main()
    for key, value in res.items():
        print(f"{key}: {value}")
    print(f"RESULTJSON:{json.dumps(res)}")
