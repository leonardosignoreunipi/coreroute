"""
Recupera i 4 batch (exhaustive_optimal, n=40 nf=6) andati in timeout nel run
finale di heuristic_benchmark.py (vedi heuristic_benchmark_final.log, righe
TIMEOUT). Riusa _run_batch/run_trial_batch di heuristic_benchmark.py senza
modificarlo: stesso codice, stesso comportamento, stesso schema di riga --
cambia solo quali 4 celle vengono lanciate.

Timeout alzato a 3h (dalle 1h del run originale, che e' quello che li ha
fatti scattare): se falliscono di nuovo probabilmente sono genuinamente
intrattabili entro un tempo ragionevole, non solo "poco sopra il limite".
"""
import os
import sys
import time

sys.path.insert(0, "/Users/leonardosignore/Desktop/repo-tesi/networkx_version/benchmark")
import ray
import pandas as pd
import heuristic_benchmark as hb

MISSING = [
    {"strategy": "exhaustive_optimal", "topology": "er", "n": 40, "num_flows": 6, "seed": 350377},
    {"strategy": "exhaustive_optimal", "topology": "ba", "n": 40, "num_flows": 6, "seed": 224741},
    {"strategy": "exhaustive_optimal", "topology": "ba", "n": 40, "num_flows": 6, "seed": 350377},
    {"strategy": "exhaustive_optimal", "topology": "ba", "n": 40, "num_flows": 6, "seed": 15485863},
]
BATCH_TIMEOUT = int(os.environ.get("BATCH_TIMEOUT", 10800))  # 3h

def main():
    ray.init(num_cpus=4)
    active = {hb.run_trial_batch.remote(cfg): (cfg, time.monotonic()) for cfg in MISSING}
    results = []

    while active:
        ready, _ = ray.wait(list(active), num_returns=1, timeout=30)
        now = time.monotonic()
        for ref in ready:
            cfg, t0 = active.pop(ref)
            try:
                batch_results = ray.get(ref)
            except Exception as e:
                batch_results = hb._dead_batch_rows(cfg, f"worker died: {e}")
            results.extend(batch_results)
            n_ok = sum(1 for r in batch_results if r.get("ok"))
            print(f"  {cfg['topology']} seed={cfg['seed']} -> {n_ok}/{len(batch_results)} rows ok [{now-t0:.0f}s]", flush=True)

        timed_out = [ref for ref, (_, t0) in active.items() if now - t0 > BATCH_TIMEOUT]
        for ref in timed_out:
            cfg, t0 = active.pop(ref)
            ray.cancel(ref, force=True)
            results.extend(hb._dead_batch_rows(cfg, f"batch exceeded BATCH_TIMEOUT={BATCH_TIMEOUT}s (recovery run)"))
            print(f"  [TIMEOUT] {cfg['topology']} seed={cfg['seed']} after {now-t0:.0f}s", flush=True)

    out = hb.RESULTS_DIR / "heuristic_benchmark_final_recovered.csv"
    pd.DataFrame(results).to_csv(out, index=False)
    print(f"-> {out} ({len(results)} righe)")
    ray.shutdown()

if __name__ == "__main__":
    main()