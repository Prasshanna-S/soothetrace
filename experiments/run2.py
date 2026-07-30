"""Experiment 2 - retrieval at the EPISODE level (the real product unit).

run.py matched 1.5 s slices. The product matches a whole cry episode, so segments are
averaged per recording into one fingerprint before comparison.

Result (docs/FINDINGS.md §2), over 421 episodes / 207 babies:
  top-1 same baby 30.5%  (chance 0.7%)  -> ~43x chance
  median rank of a true same-baby episode: 7 of 421
  top-5 45.7% | top-10 53.3%

Note how conservative that is: the pool is 207 DIFFERENT babies. The product searches one
baby's handful of prior episodes - a far easier task. And this is a hand-rolled MFCC
fingerprint with zero learning.

Usage: python run2.py   (needs donateacry-corpus cloned alongside)
"""
import numpy as np, glob, collections
from feats import load, fingerprint, parse, SR

ROOT = "donateacry-corpus/donateacry_corpus_cleaned_and_updated_data"
SEG, HOP = int(1.5*SR), int(0.75*SR)

recs = collections.OrderedDict()
for p in sorted(glob.glob(f"{ROOT}/*/*.wav")):
    m = parse(p)
    y = load(p) if m else None
    if y is None or len(y) < SEG: continue
    fps = [fingerprint(y[s:s+SEG]) for s in range(0, len(y)-SEG+1, HOP)]
    fps = [f for f in fps if f is not None and np.all(np.isfinite(f))]
    if fps:
        recs[f"{m['uuid']}|{m['ts']}"] = {"uuid": m['uuid'], "lab": m['label'],
                                          "fp": np.mean(fps, 0)}

keys = list(recs)
X = np.array([recs[k]["fp"] for k in keys])
# ⚠️ mandatory normalization - see docs/FINDINGS.md §5
X = (X - X.mean(0)) / (X.std(0) + 1e-9)
X = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
S = X @ X.T
np.fill_diagonal(S, -9)

uu = np.array([recs[k]["uuid"] for k in keys])
cnt = collections.Counter(uu)
multi = {u for u, c in cnt.items() if c >= 2}

hits = tot = 0
ranks = []
for i, k in enumerate(keys):
    if uu[i] not in multi: continue
    order = np.argsort(-S[i]); tot += 1
    hits += uu[order[0]] == uu[i]
    ranks.append(1 + int(np.where(uu[order] == uu[i])[0][0]))

chance = np.mean([(cnt[u]-1)/(len(keys)-1) for u in uu if u in multi])
print(f"EPISODE-LEVEL retrieval over {len(keys)} episodes / {len(set(uu))} babies")
print(f"  top-1 same baby : {hits/tot:6.1%}   (chance {chance:.1%})")
print(f"  median rank of a true same-baby episode: {int(np.median(ranks))} of {len(keys)}")
print(f"  top-5 : {np.mean([r<=5 for r in ranks]):.1%}   top-10 : {np.mean([r<=10 for r in ranks]):.1%}")
