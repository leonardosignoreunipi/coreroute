% ==========================================
% KNOWLEDGE BASE: NETWORK TOPOLOGY
% ==========================================
:- dynamic host/2.
:- dynamic router/2.
:- dynamic link/4.
:- dynamic path/4.
:- dynamic flow/5.
:- dynamic routing/2.
:- dynamic pathsCandidates/2.
:- dynamic speedOfLight/1.
:- dynamic pcktSize/2.

speedOfLight(300000).
pcktSize(_, 256).
host(h1, ['s1', 's2']).
host(h2, ['s3', 's4']).
router(r1, 1).
router(r2, 1).
router(r3, 1).
link(h1, r1, 512, 10).
link(r1, r2, 512, 10).
link(r2, h2, 256, 10).
link(r1, r3, 256, 10).
link(r3, h2, 256, 10).
flow(f1, s1, s3, 7, 1).
flow(f2, s2, s4, 7, 1).
path(p1, h1, h2, ['h1', 'r1', 'r2', 'h2']).
path(p2, h1, h2, ['h1', 'r1', 'r2', 'h2']).
path(f2_1, h1, h2, ['h1', 'r1', 'r2', 'h2']).
path(f2_2, h1, h2, ['h1', 'r1', 'r3', 'h2']).
path(f1_1, h1, h2, ['h1', 'r1', 'r2', 'h2']).
path(f1_2, h1, h2, ['h1', 'r1', 'r3', 'h2']).
pathsCandidates(f2, ['f2_1', 'f2_2']).
pathsCandidates(f1, ['f1_1', 'f1_2']).
routing(f1, p1).
routing(f2, p2).