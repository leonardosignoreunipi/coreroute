:- consult('network_topology.pl').

% -- NODES QTIME --- 
node_qtime(Node, 0) :- host(Node, _).
node_qtime(Node, QTime) :- router(Node, QTime).

% --- CORE LOGIC ---
partition(OkFlows, KoFlows) :-
    findall(routing(FId, PId),( flow(FId, _, _, _, _), routing(FId, PId)), AllFlows),
    partition(AllFlows, OkFlows, KoFlows).

partition(AllFlows, OkFlows, KoFlows) :-
    findall(routing(FlowId, PathId), is_routing_valid(FlowId, PathId, AllFlows), OkFlows), 
    subtract(AllFlows, OkFlows, KoFlows).

crRouting(OkRoutings, KoRoutings, NewValidRoutings) :-
    KoRoutings = [routing(FlowId, _) | OtherKoRoutings],
    find_valid_paths(FlowId, NewValidPath, OkRoutings),
    crRouting([routing(FlowId, NewValidPath)|OkRoutings], OtherKoRoutings, NewValidRoutings).

crRouting(OkRoutings, KoRoutings, NewValidRoutings) :-
    KoRoutings = [routing(FlowId, PathId) | OtherKoRoutings],
    crRouting([routing(FlowId, PathId)|OkRoutings], OtherKoRoutings, NewValidRoutings).

crRouting(NewValidRoutings, [], NewValidRoutings).

is_routing_valid(FlowId, PathId, OkRoutings) :-
    routing(FlowId, PathId),
    flow(FlowId, SrcService, DstService, MaxLatency, _),
    s_path(PathId, SrcHost, DstHost, Nodes),
    Nodes = [SrcHost|_],last(Nodes, DstHost),
    host(SrcHost, ServicesAtSrcHost), member(SrcService, ServicesAtSrcHost),
    host(DstHost, ServicesAtDstHost), member(DstService, ServicesAtDstHost),

    requiredBw(FlowId, RequiredBw), check_path_bandwidth(FlowId, Nodes, RequiredBw, OkRoutings),
    path_latency(FlowId, PathId, OkRoutings, Latency), Latency =< MaxLatency.

% --- BANDWIDTH LOGIC ---
requiredBw(FlowID, UsedBw) :-
    pcktSize(PcktSize),
    flow(FlowID, _, _, _, RateInHz),
    UsedBw is RateInHz * PcktSize.

availableBandwidthLink(FlowId, Node1, Node2, OkRoutings, EffectiveBw) :-
    s_link(Node1, Node2, TotalBw, _),
    findall(Bw, 
                (
                    member(routing(OtherFlowId, PathId), OkRoutings),
                    OtherFlowId \= FlowId,
                    path_contains_link(PathId, Node1, Node2),
                    requiredBw(OtherFlowId, Bw)
                ), 
            UsedBwList),
    sum_list(UsedBwList, UsedBw),
    EffectiveBw is TotalBw - UsedBw.

check_path_bandwidth(FlowId, [Node1, Node2 | Rest], RequiredBw, OkRoutings) :-
    s_link(Node1, Node2, _, _),
    availableBandwidthLink(FlowId, Node1, Node2, OkRoutings, EffectiveBw), EffectiveBw >= RequiredBw,
    check_path_bandwidth(FlowId, [Node2 | Rest], RequiredBw, OkRoutings).
check_path_bandwidth(_, [_], _, _).


% --- LATENCY CALCULATION ---
path_latency(FlowId, PathId, OkRoutings, Latency) :-
    path(PathId, _, _, Nodes),
    path_latency_nodes(FlowId, Nodes, OkRoutings, 0, Latency).

path_latency_nodes(FlowId, [Node1, Node2 | Rest], OkRoutings, Acc, Latency) :-
    s_link(Node1, Node2, _, Length),

    availableBandwidthLink(FlowId, Node1, Node2, OkRoutings, EffectiveBw), EffectiveBw > 0,

    node_qtime(Node1, QTime1), 
    speedOfLight(SpeedOfLight), 
    pcktSize(PcktSize),

    Dtrasm is PcktSize / EffectiveBw, 
    Dprop is Length / SpeedOfLight, 
    NewAcc is Acc + QTime1 + Dtrasm + Dprop,

    path_latency_nodes(FlowId, [Node2 | Rest], OkRoutings, NewAcc, Latency).
path_latency_nodes(_, [_], _, Acc, Acc).


% --- PATHFINDING ---
find_valid_paths(FlowId, Path, OkRoutings) :-
    flow(FlowId, SrcService, DstService, MaxLatency, _),
    host(SrcHost, SrcServices), member(SrcService, SrcServices),
    host(DstHost, DstServices), member(DstService, DstServices),

    requiredBw(FlowId, RequiredBw),

    search_path(FlowId, RequiredBw, SrcHost, DstHost, [SrcHost], Path, 0, MaxLatency, OkRoutings).

search_path(_, _, Dst, Dst, Visited, Path, _, _, _) :- reverse(Visited, Path).

search_path(FlowId, RequiredBw, Current, Dst, Visited, Path, CurrLatency, MaxLatency, OkRoutings) :-
    s_link(Current, Next, _, Length),\+ member(Next, Visited),
    
    speedOfLight(SpeedOfLight),pcktSize(PcktSize),

    availableBandwidthLink(FlowId, Current, Next, OkRoutings, EffectiveBw), EffectiveBw >= RequiredBw,

    node_qtime(Current, QTime1),
    Dtrasm is PcktSize / EffectiveBw,
    Dprop is Length / SpeedOfLight,
    NewLatency is CurrLatency + Dtrasm + Dprop + QTime1,

    NewLatency =< MaxLatency,

    search_path(FlowId, RequiredBw, Next, Dst, [Next|Visited], Path, NewLatency, MaxLatency, OkRoutings).


% --- UTILS ---
s_link(X, Y, Bandwidth, Length) :- link(X, Y, Bandwidth, Length).
s_link(X, Y, Bandwidth, Length) :- link(Y, X, Bandwidth, Length).

s_path(PathId, SrcHost, DstHost, Nodes) :- 
    path(PathId, SrcHost, DstHost, Nodes).
s_path(PathId, DstHost, SrcHost, ReversedNodes) :-
    path(PathId, SrcHost, DstHost, Nodes),
    reverse(Nodes, ReversedNodes).

path_contains_link(Nodes, Node1, Node2) :-
    is_list(Nodes),
    ( append(_, [Node1, Node2 | _], Nodes) ; append(_, [Node2, Node1 | _], Nodes) ).

path_contains_link(PathId, Node1, Node2) :-
    atom(PathId),
    path(PathId, _, _, Nodes),
    ( append(_, [Node1, Node2 | _], Nodes) ; append(_, [Node2, Node1 | _], Nodes) ).