:- dynamic host/2.
:- dynamic router/2.
:- dynamic link/4.
:- dynamic path/4.
:- dynamic flow/5.
:- dynamic routing/2.
:- dynamic pathsCandidates/2.
:- dynamic speedOfLight/1.
:- dynamic pcktSize/2.

node_qtime(Node, 0) :- host(Node, _).
node_qtime(Node, QTime) :- router(Node, QTime).

partition(OkFlows, KoFlows) :-
    findall(routing(FId, PId),( flow(FId, _, _, _, _), routing(FId, PId)), AllFlows),
    partition(AllFlows, OkFlows, KoFlows).

partition(AllFlows, OkFlows, KoFlows) :-
    findall(routing(FlowId, PathId), (routing(FlowId,PathId),validPath(FlowId, PathId, AllFlows)), OkFlows), 
    subtract(AllFlows, OkFlows, KoFlows).

crRouting([routing(FlowId, _)|Tail], OldRoutings, NewRoutings) :-
    reRoute(FlowId, OldRoutings, NewValidPathId), 
    crRouting(Tail, [routing(FlowId, NewValidPathId)|OldRoutings], NewRoutings).
 crRouting([routing(FlowId, PathId)|Tail], OldRoutings, NewRoutings) :-
     crRouting(Tail, [routing(FlowId, PathId)|OldRoutings], NewRoutings).
crRouting([], NewValidRoutings, NewValidRoutings).

reRoute(FlowId, Routings, NextPathId) :-
    nextCandidate(FlowId, NextPathId), 
    validPath(FlowId, NextPathId, Routings).

nextCandidate(FlowId, NextPathId) :-
    pathsCandidates(FlowId, PathCandidates),
    member(NextPathId, PathCandidates).

validPath(FlowId, PathId, OkRoutings) :-
    flow(FlowId, SrcService, DstService, MaxLatency, _),
    path(PathId, SrcHost, DstHost, Nodes),
    Nodes = [SrcHost|_],last(Nodes, DstHost),
    host(SrcHost, ServicesAtSrcHost), member(SrcService, ServicesAtSrcHost),
    host(DstHost, ServicesAtDstHost), member(DstService, ServicesAtDstHost),

    requiredBandwidth(FlowId, UsedBw), checkBandwidthPath(FlowId, Nodes, UsedBw, OkRoutings),
    checkLatencyPath(FlowId, PathId, OkRoutings, Latency), MaxLatency >= Latency.

requiredBandwidth(FlowId, UsedBw) :-
    pcktSize(FlowId, PcktSize),
    flow(FlowId, _, _, _, RateInHz),
    UsedBw is RateInHz * PcktSize.

availableBandwidthLink(FlowId, Node1, Node2, OkRoutings, EffectiveBw) :-
    s_link(Node1, Node2, TotalBw, _),
    findall(Bw, 
                (
                    member(routing(OtherFlowId, PathId), OkRoutings),
                    OtherFlowId \= FlowId,
                    path_contains_link(PathId, Node1, Node2),
                    requiredBandwidth(OtherFlowId, Bw)
                ), 
            UsedBwList),
    sum_list(UsedBwList, UsedBw),
    EffectiveBw is TotalBw - UsedBw.

checkBandwidthPath(FlowId, [Node1, Node2 | Rest], RequiredBandwidth, OkRoutings) :-
    s_link(Node1, Node2, _, _),
    availableBandwidthLink(FlowId, Node1, Node2, OkRoutings, EffectiveBw), EffectiveBw >= RequiredBandwidth,
    checkBandwidthPath(FlowId, [Node2 | Rest], RequiredBandwidth, OkRoutings).
checkBandwidthPath(_, [_], _, _).

checkLatencyPath(FlowId, PathId, OkRoutings, Latency) :-
    path(PathId, _, _, Nodes),
    path_latency_nodes(FlowId, Nodes, OkRoutings, 0, Latency).

path_latency_nodes(FlowId, [Node1, Node2 | Rest], OkRoutings, OldDelay, NewDelay) :-
    flow(FlowId, _, _, MaxLatency, _), 
    availableBandwidthLink(FlowId, Node1, Node2, OkRoutings, EffectiveBw), EffectiveBw > 0,
    hopLatency(FlowId, Node1, Node2, Delay), 
    TmpDelay is OldDelay + Delay, TmpDelay =< MaxLatency,
    path_latency_nodes(FlowId, [Node2 | Rest], OkRoutings, TmpDelay, NewDelay).
path_latency_nodes(_, [_], _, Delay, Delay).

hopLatency(FlowId, Node1, Node2, Delay) :-
    s_link(Node1, Node2, Bandwidth, Length),
    node_qtime(Node1, QTime1), 
    speedOfLight(SpeedOfLight), 
    pcktSize(FlowId, PcktSize),
    Dtrasm is PcktSize / Bandwidth, 
    Dprop is Length / SpeedOfLight, 
    Delay is QTime1 + Dtrasm + Dprop.

find_valid_paths(FlowId, Path, OkRoutings) :-
    flow(FlowId, SrcService, DstService, MaxLatency, _),
    host(SrcHost, SrcServices), member(SrcService, SrcServices),
    host(DstHost, DstServices), member(DstService, DstServices),

    requiredBandwidth(FlowId, requiredBandwidth),

    search_path(FlowId, requiredBandwidth, SrcHost, DstHost, [SrcHost], Path, 0, MaxLatency, OkRoutings).

search_path(_, _, Dst, Dst, Visited, Path, _, _, _) :- reverse(Visited, Path).

search_path(FlowId, requiredBandwidth, Current, Dst, Visited, Path, CurrLatency, MaxLatency, OkRoutings) :-
    s_link(Current, Next, _, Length),\+ member(Next, Visited),
    
    speedOfLight(SpeedOfLight),pcktSize(_,PcktSize),

    availableBandwidthLink(FlowId, Current, Next, OkRoutings, EffectiveBw), EffectiveBw >= requiredBandwidth,

    node_qtime(Current, QTime1),
    Dtrasm is PcktSize / EffectiveBw,
    Dprop is Length / SpeedOfLight,
    NewLatency is CurrLatency + Dtrasm + Dprop + QTime1,

    NewLatency =< MaxLatency,

    search_path(FlowId, requiredBandwidth, Next, Dst, [Next|Visited], Path, NewLatency, MaxLatency, OkRoutings).

% --- UTILS ---
s_link(X, Y, Bandwidth, Length) :- link(X, Y, Bandwidth, Length).
s_link(X, Y, Bandwidth, Length) :- link(Y, X, Bandwidth, Length).

s_path(PathId, SrcHost, DstHost, Nodes) :- 
    path(PathId, SrcHost, DstHost, Nodes).
s_path(PathId, DstHost, SrcHost, ReversedNodes) :-
    path(PathId, SrcHost, DstHost, Nodes),
    reverse(Nodes, ReversedNodes).

path_contains_link(PathId, Node1, Node2) :-
    atom(PathId),
    path(PathId, _, _, Nodes),
    ( append(_, [Node1, Node2 | _], Nodes) ; append(_, [Node2, Node1 | _], Nodes) ).