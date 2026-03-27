:- module(routing_core, [
    is_routing_valid/2,
    find_valid_paths/2,
    search_path/8, 
    path_latency/3
]).

:- consult('network_topology.pl'). % Carica i dati della rete

% --- CORE LOGIC ---

%% is_routing_valid(+FlowId, +PathId)
% Verifica se un routing assegnato è valido per i requisiti del flusso
is_routing_valid(FlowId, PathId) :-
    routing(FlowId, PathId),
    flow(FlowId, SrcService, DstService, MaxLatency, RateInHz),
    s_path(PathId, SrcHost, DstHost, Nodes),
    Nodes = [SrcHost|_], % Verifica che il primo nodo sia la sorgente
    last(Nodes, DstHost),
    host(SrcHost, ServicesAtSrcHost), member(SrcService, ServicesAtSrcHost),
    host(DstHost, ServicesAtDstHost), member(DstService, ServicesAtDstHost),

    % 1. CONTROLLO BANDA: Verifica che ogni link del path abbia banda sufficiente
    pcktSize(PcktSize),
    RequiredBw is RateInHz * PcktSize, % Calcolo della banda richiesta
    check_path_bandwidth(FlowId, Nodes, RequiredBw),

    % 2. CONTROLLO LATENZA: Verifica che la latenza totale del path sia inferiore al massimo consentito
    path_latency(FlowId, PathId, Latency),
    Latency =< MaxLatency.

%% find_valid_paths(+FlowID, -Path)
% Trova tutti i percorsi che rispettano il vincolo di latenza e banda.
find_valid_paths(FlowId, Path) :-
    flow(FlowId, SrcService, DstService, MaxLatency, RateInHz),
    host(SrcHost, SrcServices), member(SrcService, SrcServices),
    host(DstHost, DstServices), member(DstService, DstServices),

    pcktSize(PcktSize),
    RequiredBw is RateInHz * PcktSize,

    search_path(FlowId, RequiredBw, SrcHost, DstHost, [SrcHost], Path, 0, MaxLatency).

% --- BANDWIDTH LOGIC ---

%% available_bandwidth(+CurrentFlowId, +Node1, +Node2, +TotalBw, -EffectiveBw)
% Calcola la banda residua sottraendo quella usata dagli ALTRI flussi allocati su quel link
available_bandwidth(CurrentFlowId, Node1, Node2, TotalBw, EffectiveBw) :-
    findall(Bw,
        (
            routing(OtherFlowId, PathId),      
            OtherFlowId \= CurrentFlowId, %tutti tranne questo flusso     
            path_contains_link(PathId, Node1, Node2), 
            flow(OtherFlowId, _, _, _, RateInHz),
            
            pcktSize(PcktSize),
            Bw is RateInHz * PcktSize % Calcolo della banda usata da questo flusso sul link
        ),
        UsedBwList),                           
    sum_list(UsedBwList, UsedBw),              
    EffectiveBw is TotalBw - UsedBw.           

%% check_path_bandwidth(+FlowId, +NodesList, +RequiredBw)
% Scansiona la lista dei nodi e verifica che ogni link abbia banda residua >= RequiredBw
check_path_bandwidth(_, [_], _). % Caso base: siamo arrivati all'ultimo nodo
check_path_bandwidth(FlowId, [Node1, Node2 | Rest], RequiredBw) :-
    s_link(Node1, Node2, TotalBw, _),
    available_bandwidth(FlowId, Node1, Node2, TotalBw, EffectiveBw),
    EffectiveBw >= RequiredBw, % Fallisce se la banda residua non basta
    check_path_bandwidth(FlowId, [Node2 | Rest], RequiredBw).

% --- LATENCY CALCULATION ---

path_latency(FlowId, PathId, Latency) :-
    path(PathId, _, _, Nodes),
    path_latency_nodes(FlowId, Nodes, 0, Latency).

path_latency_nodes(FlowId, [Node1, Node2 | Rest], Acc, Latency) :-
    s_link(Node1, Node2, Bandwidth, Length),

    available_bandwidth(FlowId, Node1, Node2, Bandwidth, EffectiveBw), % Considera la banda residua per il calcolo della latenza
    EffectiveBw > 0, % Se la banda residua è zero, il link è congestionato e la latenza è infinita (fallisce)

    node_qtime(Node1, QTime1), 
    speedOfLight(SpeedOfLight), 
    pcktSize(PcktSize),

    Dtrasm is PcktSize / EffectiveBw, 
    Dprop is Length / SpeedOfLight, 
    NewAcc is Acc + QTime1 + Dtrasm + Dprop,

    path_latency_nodes(FlowId, [Node2 | Rest], NewAcc, Latency).
path_latency_nodes(FlowId, [_], Acc, Acc).

node_qtime(Node, 0) :- host(Node, _).
node_qtime(Node, QTime) :- router(Node, QTime).

% --- PATHFINDING ---

search_path(FlowId, RequiredBw, Dst, Dst, Visited, Path, CurrLatency, MaxLatency) :-
    reverse(Visited, Path).

% Ricerca ricorsiva di un percorso che soddisfi i QoS
search_path(FlowId, RequiredBw, Current, Dst, Visited, Path, CurrLatency, MaxLatency) :-
    s_link(Current, Next, Bandwidth, Length),
    \+ member(Next, Visited),

    % Calcola la nuova latenza accumulata
    speedOfLight(SpeedOfLight),
    pcktSize(PcktSize),

    available_bandwidth(FlowId, Current, Next, Bandwidth, EffectiveBw),
    EffectiveBw >= RequiredBw,

    node_qtime(Current, QTime1),
    Dtrasm is PcktSize / EffectiveBw,
    Dprop is Length / SpeedOfLight,
    NewLatency is CurrLatency + Dtrasm + Dprop + QTime1,

    % Verifica che la latenza non superi il limite
    NewLatency =< MaxLatency,

    search_path(FlowId, RequiredBw, Next, Dst, [Next|Visited], Path, NewLatency, MaxLatency).

% --- UTILS ---

s_link(X, Y, Bandwidth, Length) :- link(X, Y, Bandwidth, Length).
s_link(X, Y, Bandwidth, Length) :- link(Y, X, Bandwidth, Length).

s_path(PathId, SrcHost, DstHost, Nodes) :- 
    path(PathId, SrcHost, DstHost, Nodes).
s_path(PathId, DstHost, SrcHost, ReversedNodes) :-
    path(PathId, SrcHost, DstHost, Nodes),
    reverse(Nodes, ReversedNodes).

% Verifica se un percorso transita su un determinato link
path_contains_link(PathId, Node1, Node2) :-
    s_path(PathId, _, _, Nodes),
    ( append(_, [Node1, Node2 | _], Nodes) ; append(_, [Node2, Node1 | _], Nodes) ).