from ConfigLoader import ConfigLoader
from PhysicalNetwork import PhysicalNetwork as Net
from RoutingEngine import RoutingEngine as Engine
from JanusKB import JanusKB as PrologKB
from Models import Routing
import sys
import logging

logger = logging.getLogger(__name__)

class SDNcontrollerError(Exception):
    """"Custom SDNcontrollerError"""
    pass
class SDNcontroller:
    """
    Orchestrates one reasoning step over the network: reads the flow
    partition from the KB, drives the RoutingEngine to reallocate ko-flows,
    and writes the resulting routings back to the KB.
    """
    def __init__(self, network: Net, kb: PrologKB, config: ConfigLoader, engine: Engine):
        """
            Store the network, KB, config and routing engine collaborators.
        """
        self.network = network
        self.kb = kb
        self.config = config
        self.engine = engine

    def continuous_reasoning(self):
        """
        Run one continuous-reasoning cycle:
        [1] read the current flow partition from the KB
        [2] reroute the ko-flows via the routing engine
        [3] write the resulting routings back to the KB

        Returns (new_valid_routings, n_flows_ko, n_flows_rerouted).
        """
        try:
            ok_flows, ko_flows = self.engine.get_partition()
        except Exception as e:
            logger.error(f"Partition query failed: {e}")
            raise SDNcontrollerError(f"Partition query failed: {e}")
        new_valid_routings, failed_routings = self.engine.re_routing(ok_flows, ko_flows)
        self.kb.update_janus_kb(new_valid_routings, failed_routings)
            
        logger.info(f"continuous_reasoning: {len(failed_routings)} flows could not be rerouted")
        logger.debug(f"NewValidRoutings: {new_valid_routings}, FailedRoutings: {failed_routings}")
        
        return new_valid_routings, len(ko_flows), len(new_valid_routings) - len(ok_flows)
        

    def full_recompute(self):
        """
        Full reallocation of every flow:
        [1] treat all flows as ko (init empty paths)
        [2] run cr_routing passing all flows as ko
        [3] write the new valid routing back to the KB

        Returns (new_valid_routings, f_ko, f_rerouted):
            new_valid_routings: list of valid Routing objects
            f_ko: number of KO flows
            f_rerouted: number of successfully rerouted flows
        """
        ko_flows = [Routing(flow_id=str(f.id), path_id=f"p_{f.id}_init") for f in self.config.flows.values()]
        
        new_valid_routings, failedRoutings = self.engine.re_routing([], ko_flows)
        
        logger.debug(f"Full recompute: NewValidRoutings: {new_valid_routings} FailedRoutings: {failedRoutings}")
        
        self.kb.update_janus_kb(new_valid_routings, failedRoutings)
        
        return new_valid_routings, len(ko_flows), len(new_valid_routings)