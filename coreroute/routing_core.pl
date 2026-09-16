:- dynamic host/2.
:- dynamic router/2.
:- dynamic link/4.
:- dynamic path/4.
:- dynamic flow/5.
:- dynamic routing/2.
:- dynamic pathsCandidates/2.
:- dynamic propagationSpeed/1.
:- dynamic pcktSize/2.
:- set_prolog_flag(stack_limit, 12 000 000 000).

queuingDelay(Node, 0) :- host(Node, _).
queuingDelay(Node, QTime) :- router(Node, QTime).

all(Flows) :-
    findall(routing(FId, PId), (flow(FId, _, _, _, _), routing(FId, PId)), Flows).

partition(OkFlows, KoFlows) :-
    all(Flows),
    partition(Flows, OkFlows, KoFlows).

partition(Flows, OkFlows, KoFlows) :-
    findall(routing(FId, PId), (routing(FId, PId), validPath(FId, PId, Flows)), OkFlows),
    subtract(Flows, OkFlows, KoFlows).

repair([routing(FlowId,_)|Rest], Fixed, NewR, F) :-
    pathsCandidates(FlowId, Candidates),
    member(PathId, Candidates),
    validPath(FlowId, PathId, Fixed),
    repair(Rest, [routing(FlowId, PathId)|Fixed], NewR, F).
repair([Ko|Rest], Fixed, NewR, [Ko|F]) :-
    repair(Rest, Fixed, NewR, F).
repair([], Fixed, Fixed, []).

exhaustiveRouting(Flows, OldRoutings, Solutions) :-
    findall(Perm, permutation(Flows, Perm), Perms),
    loop(Perms, OldRoutings, Solutions).
 
loop([P|Perms],OldRoutings, [NewRoutings|Sols]) :-
    repair(P, OldRoutings, NewRoutings, _),
    loop(Perms, OldRoutings, Sols).
loop([], _, []).

validPath(FlowId, PathId, OkRoutings) :-
    flow(FlowId, SrcService, DstService, MaxDelay, _),
    path(PathId, SrcHost, DstHost, Nodes),
    Nodes = [SrcHost|_],last(Nodes, DstHost),
    host(SrcHost, SrcServices), member(SrcService, SrcServices),
    host(DstHost, DstServices), member(DstService, DstServices),

    requiredBandwidth(FlowId, UsedBw), pathBandwithOk(FlowId, Nodes, UsedBw, OkRoutings),
    pathDelayOk(FlowId, PathId, OkRoutings, Delay), MaxDelay >= Delay.

requiredBandwidth(FlowId, UsedBw) :-
    pcktSize(FlowId, PcktSize),
    flow(FlowId, _, _, _, RateInHz),
    UsedBw is RateInHz * PcktSize.

availableBandwidthLink(FlowId, N1, N2, OkRoutings, EffectiveBw) :-
    s_link(N1, N2, TotalBw, _),
    findall(Bw, 
                (
                    member(routing(OtherFlowId, PathId), OkRoutings),
                    OtherFlowId \= FlowId,
                    path_contains_link(PathId, N1, N2),
                    requiredBandwidth(OtherFlowId, Bw)
                ), 
            UsedBwList),
    sum_list(UsedBwList, UsedBw),
    EffectiveBw is TotalBw - UsedBw.

pathBandwithOk(FlowId, [N1, N2 | Rest], RequiredBandwidth, OkRoutings) :-
    s_link(N1, N2, _, _),
    availableBandwidthLink(FlowId, N1, N2, OkRoutings, EffectiveBw), EffectiveBw >= RequiredBandwidth,
    pathBandwithOk(FlowId, [N2 | Rest], RequiredBandwidth, OkRoutings).
pathBandwithOk(_, [_], _, _).

pathDelayOk(FlowId, PathId, OkRoutings, Delay) :-
    path(PathId, _, _, Nodes),
    path_Delay_nodes(FlowId, Nodes, OkRoutings, 0, Delay).

path_Delay_nodes(FlowId, [N1, N2 | Rest], OkRoutings, OldDelay, NewDelay) :-
    flow(FlowId, _, _, MaxDelay, _), 
    availableBandwidthLink(FlowId, N1, N2, OkRoutings, EffectiveBw), EffectiveBw > 0,
    hopDelay(FlowId, N1, N2, Delay), 
    TmpDelay is OldDelay + Delay, TmpDelay =< MaxDelay,
    path_Delay_nodes(FlowId, [N2 | Rest], OkRoutings, TmpDelay, NewDelay).
path_Delay_nodes(_, [_], _, Delay, Delay).

hopDelay(FlowId, N1, N2, Delay) :-
    s_link(N1, N2, Bandwidth, Length),
    queuingDelay(N1, QTime1), 
    propagationSpeed(V), 
    pcktSize(FlowId, PcktSize),
    Dtrasm is PcktSize / Bandwidth, 
    Dprop is Length / V, 
    Delay is QTime1 + Dtrasm + Dprop.

% --- UTILS ---
s_link(X, Y, Bandwidth, Length) :- link(X, Y, Bandwidth, Length).
s_link(X, Y, Bandwidth, Length) :- link(Y, X, Bandwidth, Length).

s_path(PathId, SrcHost, DstHost, Nodes) :- 
    path(PathId, SrcHost, DstHost, Nodes).
s_path(PathId, DstHost, SrcHost, ReversedNodes) :-
    path(PathId, SrcHost, DstHost, Nodes),
    reverse(Nodes, ReversedNodes).

path_contains_link(PathId, N1, N2) :-
    atom(PathId),
    path(PathId, _, _, Nodes),
    ( append(_, [N1, N2 | _], Nodes) ; append(_, [N2, N1 | _], Nodes) ).