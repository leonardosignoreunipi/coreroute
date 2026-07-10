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

    def continuous_reasoning(self):
        """
        Esegue un ciclo di continuous reasoning 
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
        self.kb.update_janus_kb(new_valid_routings, failed_routings)
            
        logger.info(f"continuous_reasoning: {len(failed_routings)} flows could not be rerouted")
        logger.debug(f"NewValidRoutings: {new_valid_routings}, FailedRoutings: {failed_routings}")
        
        return new_valid_routings, len(ko_flows), len(new_valid_routings) - len(ok_flows)
        

    def full_recompute(self):
        """
        Esegue una completa riallocazione dei flussi: 
        [1] reset dei routings attuali nella kb 
        [2] effettura cr_routing inviando tutti i flussi ko!!!
        [3] aggiorna la kb col nuovo routing valido
        [4] return newValidRouting, f_ko, f_rerouted 
        
        return newValidRouting, f_ko, f_rerouted
        
        newValidRouting: lista di Routing validi
        f_ko: numero di flussi KO
        f_rerouted: numero di flussi che sono stati rerouted con successo
        """
        #self.kb.reset_all_routings() inutile cr_routing non guarda la kb ma solo le liste passate come argomento
        ko_flows = [Routing(flow_id=str(f.id), path_id=f"p_{f.id}_init")
            for f in self.config.flows.values()]
        new_valid_routings, failedRoutings = self.engine.cr_routing([], ko_flows)
        logger.debug(f"Full recompute: NewValidRoutings: {new_valid_routings} FailedRoutings: {failedRoutings}")
        self.kb.update_janus_kb(new_valid_routings, failedRoutings)
        return new_valid_routings, len(ko_flows), len(new_valid_routings)