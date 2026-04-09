:- consult('network_topology.pl').

:- dynamic routing/2.
:- dynamic path/4. 

% -- NODES QTIME --- 
node_qtime(Node, 0) :- host(Node, _).
node_qtime(Node, QTime) :- router(Node, QTime).

% --- CORE LOGIC ---
fast_reroute(FlowId, PathId, NewPath) :-
    still_valid_path(FlowId, PathId, ValidNodes),
    path(PathId, _, _, Nodes),
    last(Nodes, Dst),
    last(ValidNodes, Current),
    flow(FlowId, _, _, MaxLatency, RateInHz),

    pcktSize(PcktSize),
    RequiredBw is RateInHz * PcktSize,

    reverse(ValidNodes, ReversedValidNodes),

    path_latency_nodes(FlowId, ValidNodes, 0, AccLatency),

    search_path(FlowId, RequiredBw, Current, Dst, ReversedValidNodes, NewPath, AccLatency, MaxLatency).

still_valid_path(FlowId, PathId, ValidNodes) :-
    routing(FlowId, PathId),
    flow(FlowId, _, _, MaxLatency, RateInHz),

    pcktSize(PcktSize),
    RequiredBw is RateInHz * PcktSize,

    path(PathId, _, _, Nodes), 
    build_valid_nodes_list(Nodes, FlowId, ValidNodes, RequiredBw, MaxLatency, 0).

build_valid_nodes_list([LastNode],_, LastNode, _, _, _).
build_valid_nodes_list([Node1, Node2 | Rest],FlowId, ValidNodes, RequireBw, MaxLatency, AccLatency) :-
    s_link(Node1, Node2, Bandwidth, Length),
    available_bandwidth(FlowId, Node1, Node2, Bandwidth, EffectiveBw),
    

    pcktSize(PcktSize),

    node_qtime(Node1, QTime1),
    speedOfLight(SpeedOfLight),
    Dtrasm is PcktSize / EffectiveBw,
    Dprop is Length / SpeedOfLight,
    NewAccLatency is AccLatency + Dtrasm + Dprop + QTime1,

    ((NewAccLatency =< MaxLatency, EffectiveBw >= RequireBw) ->
        ValidNodes = [Node1 | RestValidNodes],
        build_valid_nodes_list([Node2 | Rest], FlowId, RestValidNodes, RequireBw, MaxLatency, NewAccLatency)
        ;
        ValidNodes = [Node1]
    ).
partition(OkFlows, KoFlows) :-
    findall(routing(FId, PId),( flow(FId, _, _, _, _), routing(FId, PId)), AllFlows),
    partition(AllFlows, OkFlows, KoFlows).

% Divide i routing in validi e non validi
partition(AllFlows, OkFlows, KoFlows) :-
    findall(routing(FlowId, PathId), is_routing_valid(FlowId, PathId), OkFlows), 
    subtract(AllFlows, OkFlows, KoFlows).


%% crRouting(+OkFlows, +KoFlows, -NewValidRouting) :- ...
%costruisce a partire da un vecchio routing un nuovo routing valido, riallocando i flussi non validi su percorsi alternativi, se esistono
crRouting(OkFlows, KoFlows, NewValidRouting) :-
    retract_ko_flows(KoFlows),
    reallocate_ko_flows(KoFlows, OkFlows, NewValidRouting). 

reallocate_ko_flows([], AccRouting, AccRouting).

reallocate_ko_flows([routing(FlowId, _) | Tail], AccRouting, FinalRouting) :- 
    ( find_valid_paths(FlowId, Path) ->
        %then
        gensym(new_p, NewPathId),

        Path = [SrcHost|_], last(Path, DstHost),

        assertz(path(NewPathId, SrcHost, DstHost, Path)),

        assertz(routing(FlowId, NewPathId)), 
        
        reallocate_ko_flows(Tail, [routing(FlowId, NewPathId) | AccRouting], FinalRouting)
    ; 
        %else TODO: CORREGGERE    
        reallocate_ko_flows(Tail, AccRouting, FinalRouting)
    ).

    
% Rimuove i routing non validi dalla KB 
retract_ko_flows([]). 
retract_ko_flows([routing(FlowId, _) | Tail]) :-
    retractall((routing(FlowId, _))), 
    retract_ko_flows(Tail).

%% is_routing_valid(+FlowId, +PathId)
% Verifica se un routing assegnato è valido per i requisiti del flusso
is_routing_valid(FlowId, PathId) :-
    routing(FlowId, PathId),
    flow(FlowId, SrcService, DstService, MaxLatency, RateInHz),
    s_path(PathId, SrcHost, DstHost, Nodes),
    Nodes = [SrcHost|_],
    last(Nodes, DstHost),
    host(SrcHost, ServicesAtSrcHost), member(SrcService, ServicesAtSrcHost),
    host(DstHost, ServicesAtDstHost), member(DstService, ServicesAtDstHost),

    % 1. CONTROLLO BANDA: Verifica che ogni link del path abbia banda sufficiente
    pcktSize(PcktSize),
    RequiredBw is RateInHz * PcktSize,
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
            dif(OtherFlowId, CurrentFlowId), %tutti tranne questo flusso     
            path_contains_link(PathId, Node1, Node2), 
            flow(OtherFlowId, _, _, _, RateInHz),
            
            pcktSize(PcktSize),
            Bw is RateInHz * PcktSize % Calcolo della banda usata da questo flusso sul link
        ),
        UsedBwList),                           
    sum_list(UsedBwList, UsedBw),              
    EffectiveBw is TotalBw - UsedBw.%free bandwith, si può fare meglio            

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

    available_bandwidth(FlowId, Node1, Node2, Bandwidth, EffectiveBw), 
    EffectiveBw > 0,

    node_qtime(Node1, QTime1), 
    speedOfLight(SpeedOfLight), 
    pcktSize(PcktSize),

    Dtrasm is PcktSize / EffectiveBw, 
    Dprop is Length / SpeedOfLight, 
    NewAcc is Acc + QTime1 + Dtrasm + Dprop,

    path_latency_nodes(FlowId, [Node2 | Rest], NewAcc, Latency).
path_latency_nodes(FlowId, [_], Acc, Acc).

% --- PATHFINDING ---
search_path(_, _, Dst, Dst, Visited, Path, _, _) :- 
    reverse(Visited, Path).

% Ricerca ricorsiva di un percorso che soddisfi i QoS effettua i controlli di banda e latenza ad ogni passo
search_path(FlowId, RequiredBw, Current, Dst, Visited, Path, CurrLatency, MaxLatency) :-
    s_link(Current, Next, Bandwidth, Length),\+ member(Next, Visited),
    
    speedOfLight(SpeedOfLight),pcktSize(PcktSize),

    available_bandwidth(FlowId, Current, Next, Bandwidth, EffectiveBw),
    EffectiveBw >= RequiredBw,

    node_qtime(Current, QTime1),
    Dtrasm is PcktSize / EffectiveBw,
    Dprop is Length / SpeedOfLight,
    NewLatency is CurrLatency + Dtrasm + Dprop + QTime1,

    NewLatency =< MaxLatency,

    search_path(FlowId, RequiredBw, Next, Dst, [Next|Visited], Path, NewLatency, MaxLatency).

% --- UTILS ---

%rende i link bidirezionali
s_link(X, Y, Bandwidth, Length) :- link(X, Y, Bandwidth, Length).
s_link(X, Y, Bandwidth, Length) :- link(Y, X, Bandwidth, Length).

% Permette di ottenere il path in entrambe le direzioni (src->dst e dst->src)
s_path(PathId, SrcHost, DstHost, Nodes) :- 
    path(PathId, SrcHost, DstHost, Nodes).
s_path(PathId, DstHost, SrcHost, ReversedNodes) :-
    path(PathId, SrcHost, DstHost, Nodes),
    reverse(Nodes, ReversedNodes).

% Verifica se un percorso transita su un determinato link
path_contains_link(PathId, Node1, Node2) :-
    path(PathId, _, _, Nodes),
    ( append(_, [Node1, Node2 | _], Nodes) ; append(_, [Node2, Node1 | _], Nodes) ).