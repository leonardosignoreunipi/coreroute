
:- discontiguous link/4.
:- discontiguous path/4.

% Constants
speedOfLight(300000000). % in metres per second
pcktSize(0.8). % in bits, assuming 1000 bytes packet size


% host(HostId, ServicesDeployedToHost).
host(h1, [s1]).
host(h2, [s2]).

% router(RouterId, AvgQTime).
router(r1, 1).
router(r2, 10).

% h1---r1---r2---h2
% link(From, To, BandwidthInMbps, LengthInMetres).
link(h1, r1, 1000000, 10).
link(r1, r2, 10000000, 100).
link(r1, h2, 10000000, 10).
link(r2, h2, 10000000, 10).

% path(PathId,SrcHost, DstHost, [ListOfNodesInPath]).
path(p1, h1, h2, [h1, r1, r2, h2]).

% flow(FlowId, SourceService, DestinationService, MaxLatency).
% TODO: add time duration or data size to flow?
flow(f1, s1, s2, 15).
flow(f2, s1, s2, 1).

% routing(FlowId, PathId). 
% indicates that the flow with FlowId is routed through the path with PathId.
routing(f1, p1).
routing(f2, p1).



%%% regole %%%

%% routing che non soddisfa i requisiti di valid
rOK(FlowID, PathID) :- 
    valid(FlowID, PathID).

%% routing che non soddisfa i requisiti di valid
rKO(FlowID, PathID) :-  
    \+valid(FlowID, PathID).


%% regola per verificare se un routing è valido, ovvero se il percorso soddisfa i requisiti del flusso (servizi, latenza)
valid(FlowId,PathId) :-
    routing(FlowId, PathId), %verifica che il routing esista nei fatti
    flow(FlowId, SrcService, DstService, MaxLatency), %%verifica che il flusso esista nei fatti e recupera i servizi e la latenza massima
    s_path(PathId, SrcHost, DstHost, [SrcHost|Nodes]), %%verifica che il percorso esista nei fatti e recupera i nodi del percorso, verificando che il primo nodo sia la sorgente
    last(Nodes, DstHost), %%verifica che l'ultimo nodo del percorso sia la destinazione
    host(SrcHost, ServicesAtSrcHost), member(SrcService, ServicesAtSrcHost), %%verifica che il servizio sorgente sia effettivamente deployato sull'host sorgente
    host(DstHost, ServicesAtDstHost), member(DstService, ServicesAtDstHost),
    pathLatency(PathId, Latency), % TODO: find a more elegant solution than cut !
    Latency =< MaxLatency.

pathLatency(PathId, Latency) :-
    path(PathId, _, _, Nodes),
    pathLatency(Nodes, 0, Latency).

% Hp: we consider that paths are already acyclic, so we don't need to check for cycles in the path.
pathLatency([Node1, Node2 | Rest], Acc, Latency) :-
    s_link(Node1, Node2, Bandwidth, Length),
    node(Node1, QTime1), node(Node2, _),
    speedOfLight(SpeedOfLight), pcktSize(PckSize),
    Dtrasm is PckSize / Bandwidth, % in seconds, PckSize is in bits and Bandwidth is in bits per second
    Dprop is Length / SpeedOfLight, % in seconds, Length is in metres and SpeedOfLight is in metres per second
    NewAcc is Acc + QTime1 + Dtrasm + Dprop,
    pathLatency([Node2 | Rest], NewAcc, Latency).
pathLatency([_], Acc, Acc).

node(Node,0) :- host(Node, _).
node(Node, QTime) :- router(Node, QTime).


% trova_path_validi(+FlowID, -Path)
% Trova tutti i percorsi possibili tra sorgente e destinazione
% del flusso FlowID che rispettano il vincolo di latenza massima.
trova_path_validi(FlowID, Path) :-
    flow(FlowID, SrcService, DstService, MaxLatency),
    host(SrcHost, SrcServices), member(SrcService, SrcServices),
    host(DstHost, DstServices), member(DstService, DstServices),
    searchPath(SrcHost, DstHost, [SrcHost], Path),
    pathLatency(Path, 0, Latency),
    Latency =< MaxLatency.

% Caso Base: siamo arrivati alla destinazione
searchPath(Dst, Dst, Visited, Path) :-
    reverse(Visited, Path).

% Caso Ricorsivo: cerca un nodo adiacente e continua la ricerca
searchPath(Current, Dst, Visited, Path) :-
    s_link(Current, Next, _, _),
    \+ member(Next, Visited),
    searchPath(Next, Dst, [Next|Visited], Path).

%%%% Utils for symmetric links %%%%
s_link(X, Y, Bandwidth, Length) :- %cambiato altrimenti entrava in loop infinito
    link(Y, X, Bandwidth, Length).
s_link(X, Y, Bandwidth, Length) :-
    link(X, Y, Bandwidth, Length).

s_path(PathId, SrcHost, DstHost, Nodes) :-
    path(PathId, SrcHost, DstHost, Nodes).

s_path(PathId,DstHost,SrcHost,ReversedNodes) :-
    path(PathId, SrcHost, DstHost, Nodes),
    reverse(Nodes, ReversedNodes).



