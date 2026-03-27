% flow(FlowId, SourceService, DestinationService, MaxLatency, RateInHz).
% link(From, To, BandwidthInBps, LengthInMetres).
% path(PathId,SrcHost, DstHost, [ListOfNodesInPath]).

% Constants
speedOfLight(300000000).  % in metres per second
pcktSize(1500). % in bits, assuming 1500 bytes packet size 

% Topology
host(h1, [s1]).
host(h2, [s2]).
router(r1, 1).
router(r2, 10).

link(h1, r1, 1500, 10).
link(r1, r2, 1500, 10).
link(r2, h2, 1500, 10).


% Flows and predefined paths
path(p1, h1, h2, [h1, r1, r2, h2]).

flow(f1, s1, s2, 15, 1).
flow(f2, s1, s2, 15, 1).

routing(f1, p1).