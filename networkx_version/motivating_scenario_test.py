"""Usa e getta: scenario motivante, degrado di r2-r3, CR con strategia esaustiva.
Eseguire dalla cartella del repo: python3 motivating_scenario_test.py
"""

import time
from ConfigLoader import ConfigLoader
from PhysicalNetwork import PhysicalNetwork
from JanusKB import JanusKB
from RoutingEngine import RoutingEngine
from SDNcontroller import SDNcontroller

NUOVA_BW_R2_R3 = 5.0  # Mbps

config = ConfigLoader("motivating_scenario.json").load()
network = PhysicalNetwork(config)
kb = JanusKB(config, "routing_core.pl")
engine = RoutingEngine(network, kb, config)
ctrl = SDNcontroller(network, kb, config, engine)

kb.clear_kb()
kb.initialize_kb()

print("--- prima del degrado ---")
for r in engine.get_partition()[0]:
    print(f"  {r.flow_id} -> {r.path_id}: {kb.get_path_by_id(r.path_id)}")

network.graph["r2"]["r3"]["bw"] = NUOVA_BW_R2_R3
kb.update_links_bandwidth([("r2", "r3", NUOVA_BW_R2_R3)])

engine.STRATEGY = engine.all_simple_candidates
engine.prolog_strategy = engine.resolve_exhaustive_routing

t0 = time.perf_counter()
new_valid, n_ko, n_rr, no_path = ctrl.continuous_reasoning()
elapsed = time.perf_counter() - t0

print(f"\n--- dopo (r2-r3 a {NUOVA_BW_R2_R3} Mbps) ---")
print(f"KO: {n_ko}  rerouted: {n_rr}  no_path: {no_path}  tempo: {elapsed:.4f}s")
for r in new_valid:
    print(f"  {r.flow_id} -> {r.path_id}: {kb.get_path_by_id(r.path_id)}")
