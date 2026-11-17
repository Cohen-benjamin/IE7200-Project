"""Make the 40 benchmark subsets and store them in data/benchmark_subsets_k9.csv.

Run once (the file is committed; the benchmarks only READ it, they never draw random numbers):
    python experiments/make_subsets.py

Each subset has K stops (9: the largest size brute force solves in about 4 seconds).
- 20 CLUSTERED subsets: every stop is tried as a cluster centre, the K nearest stops are taken (ties go to the lower
  LocationIndex), and repeated groups are dropped. Only the distance matrix is used, so no random numbers are involved.
  There are only 20 different clustered groups of 9 in this data, so 20 is all there are.
- 20 RANDOM subsets: seeds 0, 1, 2, ... each give one random group of K stops; a group already seen is skipped, until
  there are 20. The seed is stored in the file, but the stored stops (not the seed) are what the benchmarks use, so the
  results do not depend on Python's random generator staying the same.
Units: stop numbers are LocationIndex values from the data.
"""
import sys
from pathlib import Path

import pandas as pd

# Let "import dispatch" work without "pip install -e ." by adding the src/ folder to Python's search path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dispatch.ingest.data import load_instance
from dispatch.solvers import brute

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "csv"                          # where the instance CSVs live
OUT_FILE = ROOT / "data" / "benchmark_subsets_k9.csv"     # the stored subsets (committed)
K = 9                                                     # stops per subset
N_RANDOM = 20                                             # random groups to add (20 clustered + 20 random = 40 subsets)


def make_subsets(instance, k: int = K, n_random: int = N_RANDOM) -> pd.DataFrame:
    """Build the subsets table: 'clustered' rows first, then 'random' rows.

    Inputs:
        instance: the full instance.
        k: stops per subset.
        n_random: how many random subsets to add.
    Output:
        DataFrame with subset_id, kind, k, stops (space-separated LocationIndex values), source
        (the cluster centre, or the random seed that produced the group).
    """
    rows = []
    seen = set()                                          # groups already taken, so no subset appears twice
    # --- Clustered: every stop as a centre, in stop order; keep the first centre of each distinct group.
    for centre in instance.stops:
        group = brute.cluster_around(instance, centre, k)
        if group not in seen:
            seen.add(group)
            rows.append(("clustered", group, f"centre {centre}"))
    # --- Random: next seed, skip groups already seen, until n_random are added.
    added, seed = 0, 0
    while added < n_random:
        group = brute.draw_subset(instance, k, seed, "random")
        if group not in seen:
            seen.add(group)
            rows.append(("random", group, f"seed {seed}"))
            added += 1
        seed += 1
    table = [{"subset_id": i, "kind": kind, "k": k, "stops": " ".join(str(s) for s in group), "source": source}
             for i, (kind, group, source) in enumerate(rows)]
    return pd.DataFrame(table)


def main() -> None:
    """Write the subsets file and print how many of each kind it holds."""
    table = make_subsets(load_instance(DATA_DIR))
    table.to_csv(OUT_FILE, index=False)
    print(f"Wrote {len(table)} subsets ({table.groupby('kind').size().to_dict()}) to {OUT_FILE}")


if __name__ == "__main__":
    main()
