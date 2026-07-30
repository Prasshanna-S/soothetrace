"""Build the POPULATION normalization baseline from the public corpus.

Run once before retrieval will work. Without a baseline, find_similar() correctly refuses
to return anything, because raw-cosine comparison scores ~0.99 for every pair
(docs/FINDINGS.md §5).

Why population rather than per-subject: the validated results normalized against 431 corpus
recordings. A subject with three episodes cannot supply stable per-dimension statistics.

Usage:
    cd experiments && git clone --depth 1 https://github.com/gveres/donateacry-corpus.git
    python tools/build_baseline.py
"""
import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import config          # noqa: E402
import fingerprint     # noqa: E402
import store           # noqa: E402

CORPUS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "experiments", "donateacry-corpus",
                      "donateacry_corpus_cleaned_and_updated_data")


def main() -> int:
    files = sorted(glob.glob(os.path.join(CORPUS, "*", "*.wav")))
    if not files:
        print(f"No corpus at {CORPUS}\n"
              f"  cd experiments && git clone --depth 1 "
              f"https://github.com/gveres/donateacry-corpus.git", file=sys.stderr)
        return 1

    vecs = []
    for i, p in enumerate(files):
        v = fingerprint.compute_windowed(p)
        if v is not None:
            vecs.append(v)
        if i % 50 == 0:
            print(f"  ...{i}/{len(files)}", file=sys.stderr)

    if len(vecs) < 20:
        print(f"Only {len(vecs)} usable fingerprints - refusing to build a baseline "
              f"from that few.", file=sys.stderr)
        return 1

    X = np.asarray(vecs, dtype=np.float32)
    store.init_db()
    store.save_baseline(config.POPULATION_KEY, X.mean(0), X.std(0), len(X))
    print(f"\npopulation baseline saved: n={len(X)} dim={X.shape[1]}")
    print(f"  mu[:4] = {np.round(X.mean(0)[:4], 3)}")
    print(f"  sd[:4] = {np.round(X.std(0)[:4], 3)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
