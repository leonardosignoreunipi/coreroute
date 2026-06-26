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

    def continuos_reasoning(self):
        """
        Esegue un ciclo di continuos reasoning 
        [1] inizializza la KB
        [2] Esegue la partition
        [3] effettua il rerouting
        [5] return newRotuings, n_f_ko, n_f_rerouted
        """
        try:
            ok_flows, ko_flows = self.engine.get_partition()
        except Exception as e:
            logger.error(f"Partition query failed: {e}")
            raise SDNcontrollerError(f"Partition query failed: {e}")
        new_valid_routings, failed_routings = self.engine.cr_routing(ok_flows, ko_flows)
        self.kb.update_janus_kb(new_valid_routings)
            
        logger.info(f"continuos_reasoning: {len(failed_routings)} flows could not be rerouted")
        logger.debug(f"NewValidRoutings: {new_valid_routings}, FailedRoutings: {failed_routings}")
        
        return new_valid_routings, len(ko_flows), len(new_valid_routings) - len(ok_flows)
        

    def full_recompute(self):
        """
        Esegue una completa riallocazione dei flussi: 
        [1] reset dei routings attuali nella kb 
        [2] effettura cr_routing inviando tutti i flussi ko!!!
        [3] aggiorna la kb col nuovo routing valido
        [4] return newValidRouting, f_ko, f_rerouted 
        """
        self.kb.reset_all_routings()
        ko_flows = [Routing(flow_id=str(f.id), path_id=f"p_{f.id}_init")
            for f in self.config.flows.values()]
        new_valid_routings, failedRoutings = self.engine.cr_routing([], ko_flows)
        logger.debug(f"Full recompute: NewValidRoutings: {new_valid_routings} FailedRoutings: {failedRoutings}")
        self.kb.update_janus_kb(new_valid_routings)
        return new_valid_routings, len(ko_flows), len(new_valid_routings)

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
    controller.kb.initialize_kb()
    newValidRoutings, koroutings, reroutedRoutings = controller.continuos_reasoning()
    print(f"newValidRoutings: {newValidRoutings}\nkoRoutings: {koroutings}\nreroutedRoutings: {reroutedRoutings}")
    controller.kb.update_janus_kb(newValidRoutings)
    

if __name__ == "__main__":
    __main__()