# Routing Adattivo in Reti Cloud-Edge SDN tramite Continuous Reasoning

Il presente repository contiene il prototipo logico-dichiarativo, sviluppato in ambiente SWI-Prolog, per la validazione e il calcolo del routing *QoS-aware* all'interno di architetture Software-Defined Networking (SDN) nel continuum Cloud-Edge.

Il progetto estende e adatta i concetti di **Continuous Reasoning** introdotti nella metodologia EDGEWISECR, traslandoli dal dominio del *service placement* a quello del *traffic engineering* e dell'orchestrazione dei flussi di rete. L'obiettivo primario è minimizzare i ricalcoli onerosi dell'intera matrice di routing, valutando dinamicamente la validità delle allocazioni correnti a fronte di mutamenti topologici o variazioni dei requisiti applicativi.

## Struttura del Progetto

Il prototipo è ingegnerizzato separando la *Knowledge Base* estensionale (lo stato della rete) dal motore inferenziale (le regole di validazione e ricerca).

* `network_topology.pl`: Costituisce lo stato corrente dell'infrastruttura. Raccoglie i fatti che descrivono i nodi (host e router), le capacità dei link (banda disponibile e latenza misurata) e le caratteristiche dei flussi di dati (servizi sorgente/destinazione, latenza massima tollerata e rate di pacchetti generati). In un'architettura di produzione, questo file funge da interfaccia dinamica, generato e aggiornato in tempo reale dal Controller SDN (es. tramite script Python associati a framework come Ryu o ONOS).
* `routing_core.pl`: È il modulo core del sistema. Implementa la logica per la validazione formale dei percorsi, il calcolo della banda residua effettiva, la stima del ritardo di trasmissione contestuale al livello di congestione e gli algoritmi di ricerca per l'individuazione di percorsi alternativi aciclici.

## Modello Teorico e Vincoli QoS

Il calcolo della Quality of Service (QoS) si basa sui seguenti principi:

1. **Banda Effettiva**: La larghezza di banda richiesta da un flusso è calcolata dinamicamente come prodotto tra il rate di emissione (Hz) e la dimensione del pacchetto (costante globale in bit). Il routing fallisce proattivamente qualora un link non disponga di banda residua sufficiente, calcolata sottraendo la banda allocata agli altri flussi concorrenti instradati sul medesimo segmento.
2. **Latenza Dinamica**: Il ritardo cumulativo di un percorso include il tempo di accodamento specifico per ogni nodo (QTime), il ritardo di propagazione fisico e un ritardo di trasmissione dipendente dallo stato di congestione, calcolato in funzione della banda residua effettiva del link.

## Prerequisiti e Avvio

L'ambiente richiede l'installazione di **SWI-Prolog**. 
Per eseguire il prototipo in locale, avviare l'interprete Prolog e caricare il modulo principale:

```prolog
?- consult('routing_core.pl').

