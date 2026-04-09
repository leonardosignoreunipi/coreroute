% ==========================================
% KNOWLEDGE BASE: NETWORK TOPOLOGY
% ==========================================

% --- COSTANTI GLOBALI ---
speedOfLight(300000).  % in km/s
pcktSize(1500).        % in bit (dimensione del pacchetto) CAMBIA IN BYTE

% --- POSIZIONAMENTO SERVIZI ---
host(h1, [s1, s3]). 
host(h2, [s2, s4]). 

% --- ROUTER E QTIME ---
router(r1, 2). 
router(r2, 2). 
router(r3, 15).

% --- TOPOLOGIA FISICA (Link) ---
% link(NodoA, NodoB, BandaTotaleInBps, LunghezzaInKm).

% Accesso
link(h1, r1, 10000, 5).
link(r1, r2, 10000, 5).
link(r2, h2, 5000, 5).  %link intasato dai due flussi
link(r1, h2, 5000, 20). %link alternativo

link(r2, r3 , 10000, 5). %link alternativo
link(r3, h2, 5000, 5). %link alternativo


% --- PERCORSI PREDEFINITI ---
% path(PathId, SrcHost, DstHost, [ListOfNodes]).
path(p1, h1, h2, [h1, r1, r2, h2]).       % Percorso sul ramo superiore
path(p2, h1, h2, [h1, r1, r2, h2]).   % Percorso sul ramo inferiore

% --- FLOWS ---
% flow(FlowId, SrcSvc, DstSvc, MaxLatency, RateInHz).
flow(f1, s1, s2, 100, 2). %RequiredBw 3000bit
flow(f2, s3, s4, 150, 3). %RequiredBw 4500bit

% --- OLD ROUTING ---
% routing(FlowId, PathId).
routing(f1, p1). % f1 è instradato su p1
routing(f2, p2). % f2 è instradato su p2