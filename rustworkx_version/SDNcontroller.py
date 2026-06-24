from ConfigLoader import ConfigLoader
from PhysicalNetwork import PhysicalNetwork as Net
from RoutingEngine import RoutingEngine as Engine
from JanusKB import JanusKB as PrologKB
from models import Routing
import sys
import logging

logger = logging.getLogger(__name__)

class SDNcontrollerError(Exception):
    """"Custom SDNcontrollerError"""
    pass
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

    def continuos_reasoning(self):
        """
        Esegue il reasoning continuo del sistema SDN.
        1) okflows, koflows partition
        2) newvalidroutings from okflows, koflows
        3) update janus kb
        Returns (new_valid_routings, n_ko_flows).
        """
        try:
            ok_flows, ko_flows = self.engine.get_partition()
        except Exception as e:
            logger.error(f"Partition query failed: {e}")
            raise SDNcontrollerError(f"Partition query failed: {e}")

        ko_old_paths = {r.flow_id: r.path_id for r in ko_flows}
        new_valid_routings = self.engine.cr_routing(ok_flows, ko_flows)
        self.kb.update_janus_kb(new_valid_routings)

        n_rerouted = sum(
            1 for r in new_valid_routings
            if r.flow_id in ko_old_paths and r.path_id != ko_old_paths[r.flow_id]
        )
        return new_valid_routings, len(ko_flows), n_rerouted
        

    def full_recompute(self):
        """Route ALL flows from scratch on the current network state (post-perturbation).
        Treats every flow as KO regardless of its current routing.
        Returns (new_valid_routings, n_rerouted)."""
        self.kb.reset_all_routings()
        ko_flows = [Routing(flow_id=str(f.id), path_id=f"p_{f.id}_init")
            for f in self.config.flows.values()]
        new_valid_routings = self.engine.cr_routing([], ko_flows)
        self.kb.update_janus_kb(new_valid_routings)
        return new_valid_routings, len(ko_flows)

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