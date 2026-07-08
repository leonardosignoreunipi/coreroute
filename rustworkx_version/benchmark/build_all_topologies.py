import subprocess
import os
import math
import sys

sys.path.insert(0, os.path.dirname(__file__))

OUTPUT_DIR = "topologies"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# PDF parameters
GRAPH_TYPES   = ["er", "ba", "iaag"]
SIZES         = [1000]          # |V| (routers)
FLOW_FACTORS  = [1.00]       # |F| = factor × |V|
SEEDS = [104729, 224737, 350377, 479909, 611953, 742073, 871871, 1003001, 1234567, 15485863]

def num_hosts(n):
    return max(2, n // 10)

total = len(GRAPH_TYPES) * len(SIZES) * len(FLOW_FACTORS) * len(SEEDS)
counter = 1

print("Generating topologies...")

for gtype in GRAPH_TYPES:
    for n in SIZES:
        for ff in FLOW_FACTORS:
            for seed in SEEDS:
                num_flows = int(ff * n)
                nh = num_hosts(n)
                filename = f"{OUTPUT_DIR}/topo_{gtype}_N{n}_H{nh}_F{num_flows}_S{seed}.json"

                if os.path.exists(filename):
                    print(f"[{counter}/{total}] Skipped (exists): {filename}")
                    counter += 1
                    continue

                print(f"[{counter}/{total}] Generating: {filename}  (gtype={gtype}, n={n}, hosts={nh}, flows={num_flows})")
                cmd = [
                    "python3", "build_topology.py",
                    gtype, str(n), str(nh), str(num_flows), filename, str(seed)
                ]
                try:
                    subprocess.run(cmd, check=True)
                except subprocess.CalledProcessError as e:
                    print(f"  ERROR: {e}")
                counter += 1

print("\nDone.")
