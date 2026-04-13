% ==========================================
% KNOWLEDGE BASE: NETWORK TOPOLOGY
% ==========================================
:- dynamic host/2.
:- dynamic router/2.
:- dynamic link/4.
:- dynamic path/4.
:- dynamic flow/5.
:- dynamic routing/2.

% --- COSTANTI GLOBALI ---
speedOfLight(300000).
pcktSize(256).        

host(h1, ['s1', 's2']).
host(h2, ['s3', 's4']).


router(r1, 1).
router(r2, 1).
router(r3, 1).


link(h1, r1, 2048, 10).
link(r1, r2, 2048, 10).
link(r2, h2, 1024, 10).
link(r1, r3, 1024, 10).
link(r3, h2, 1024, 10).


flow(f1, s1, s3, 17, 3).
flow(f2, s2, s4, 17, 2).


path(p1, h1, h2, ['h1', 'r1', 'r2', 'h2']).
path(p2, h1, h2, ['h1', 'r1', 'r2', 'h2']).


routing(f1, p1).
routing(f2, p2).