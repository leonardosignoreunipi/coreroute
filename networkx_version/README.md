# 🌐 Hybrid SDN Controller (Python + Prolog)

Questo progetto implementa un **controller Software Defined Networking (SDN) ibrido** progettato per il *Traffic Engineering*.  
L’architettura combina la potenza dell’elaborazione di grafi in Python con la capacità di inferenza logica di SWI-Prolog, creando un sistema intelligente e adattivo.

L’obiettivo è **allocare dinamicamente i flussi di rete** rispettando vincoli stringenti — come banda, latenza e policy di servizio — e gestire la congestione attraverso tecniche di *Incremental Rerouting* e *Quality of Service (QoS)*.

---

## 🏗️ Architettura Ibrida

Il sistema è strutturato in due componenti principali, ciascuno con responsabilità ben definite, che comunicano tramite la libreria **Janus-SWI**.

### 🧠 Cervello Procedurale (Python + NetworkX)
Gestisce lo stato della rete e il calcolo dei percorsi:
- Costruzione del grafo della rete
- Calcolo dei percorsi alternativi in caso di guasti o congestione
- Ordinamento dei flussi secondo priorità QoS
- Esplorazione delle alternative tramite **Min-Heap**

### ⚖️ Cervello Logico (Prolog)
Agisce come *Policy Engine*:
- Valuta lo stato globale della rete (*partition*)
- Approva o rifiuta le proposte di routing
- Applica vincoli rigorosi su:
  - Capacità residua dei link
  - Tempi di accodamento (*qtime*)
  - Coerenza globale della rete

---

## ✨ Funzionalità Principali

### 🔄 Riallocazione Adattiva (Min-Heap Rerouting)
Quando un flusso fallisce, il sistema seleziona il percorso alternativo con la minima deviazione rispetto all’originale, grazie a una struttura **Min-Heap**.

### ⚡ QoS e Priority Queue (“Elephants and Mice”)
I flussi vengono ordinati automaticamente dal più leggero al più pesante:
- Evita starvation
- Migliora l’efficienza globale
- Favorisce il completamento rapido dei flussi piccoli

### 🧹 Prevenzione dello “Stato Fantasma”
I flussi non instradabili vengono rimossi dalla Knowledge Base Prolog:
- Libera immediatamente risorse logiche
- Mantiene la consistenza del sistema

### 📊 Vincoli Multipli
Il controller valuta simultaneamente:
- **Banda disponibile** (considerando solo traffico concorrente reale)
- **Latenza del percorso**, includendo:
  - Velocità di propagazione
  - Dimensione dei pacchetti
  - Tempi di accodamento

---

## 📂 Struttura del Repository# 🌐 Hybrid SDN Controller (Python + Prolog)

Questo progetto implementa un **controller Software Defined Networking (SDN) ibrido** progettato per il *Traffic Engineering*.  
L’architettura combina la potenza dell’elaborazione di grafi in Python con la capacità di inferenza logica di SWI-Prolog, creando un sistema intelligente e adattivo.

L’obiettivo è **allocare dinamicamente i flussi di rete** rispettando vincoli stringenti — come banda, latenza e policy di servizio — e gestire la congestione attraverso tecniche di *Incremental Rerouting* e *Quality of Service (QoS)*.

---

## 🏗️ Architettura Ibrida

Il sistema è strutturato in due componenti principali, ciascuno con responsabilità ben definite, che comunicano tramite la libreria **Janus-SWI**.

### 🧠 Cervello Procedurale (Python + NetworkX)
Gestisce lo stato della rete e il calcolo dei percorsi:
- Costruzione del grafo della rete
- Calcolo dei percorsi alternativi in caso di guasti o congestione
- Ordinamento dei flussi secondo priorità QoS
- Esplorazione delle alternative tramite **Min-Heap**

### ⚖️ Cervello Logico (Prolog)
Agisce come *Policy Engine*:
- Valuta lo stato globale della rete (*partition*)
- Approva o rifiuta le proposte di routing
- Applica vincoli rigorosi su:
  - Capacità residua dei link
  - Tempi di accodamento (*qtime*)
  - Coerenza globale della rete

---

## ✨ Funzionalità Principali

### 🔄 Riallocazione Adattiva (Min-Heap Rerouting)
Quando un flusso fallisce, il sistema seleziona il percorso alternativo con la minima deviazione rispetto all’originale, grazie a una struttura **Min-Heap**.

### ⚡ QoS e Priority Queue (“Elephants and Mice”)
I flussi vengono ordinati automaticamente dal più leggero al più pesante:
- Evita starvation
- Migliora l’efficienza globale
- Favorisce il completamento rapido dei flussi piccoli

### 🧹 Prevenzione dello “Stato Fantasma”
I flussi non instradabili vengono rimossi dalla Knowledge Base Prolog:
- Libera immediatamente risorse logiche
- Mantiene la consistenza del sistema

### 📊 Vincoli Multipli
Il controller valuta simultaneamente:
- **Banda disponibile** (considerando solo traffico concorrente reale)
- **Latenza del percorso**, includendo:
  - Velocità di propagazione
  - Dimensione dei pacchetti
  - Tempi di accodamento

---

## 📂 Struttura del Repository