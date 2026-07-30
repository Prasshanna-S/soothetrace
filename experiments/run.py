"""Experiment 1 - does one baby's crying episodes separate acoustically?

The feared failure mode was NOT "nothing matches" but "everything matches": if all of one
baby's cries are near-identical, retrieval always fires and always returns whatever happened
to be logged.

Measures three similarity distributions and the AUC between them:
  A same episode | B same baby, different episode | C different babies

Result (docs/FINDINGS.md §1): A +0.383 / B +0.195 / C -0.002.
A vs B AUC 0.701 -> episodes ARE distinguishable. B vs C AUC 0.732 -> a baby has an identity.

Usage:
  git clone --depth 1 https://github.com/gveres/donateacry-corpus.git
  python run.py
"""
import numpy as np, glob, os, sys, collections, json
from feats import load, fingerprint, parse, SR

ROOT = "donateacry-corpus/donateacry_corpus_cleaned_and_updated_data"
SEG, HOP = int(1.5 * SR), int(0.75 * SR)

files = sorted(glob.glob(f"{ROOT}/*/*.wav"))
rows = []
for i, p in enumerate(files):
    meta = parse(p)
    if not meta: continue
    y = load(p)
    if y is None or len(y) < SEG: continue
    for s in range(0, len(y) - SEG + 1, HOP):
        fp = fingerprint(y[s:s + SEG])
        if fp is None or not np.all(np.isfinite(fp)): continue
        rows.append({**meta, "off": s / SR, "fp": fp,
                     "rec": f"{meta['uuid']}|{meta['ts']}"})
    if i % 60 == 0: print(f"  ...{i}/{len(files)}", file=sys.stderr)

print(f"\nsegments: {len(rows)}  from {len(set(r['rec'] for r in rows))} recordings"
      f"  / {len(set(r['uuid'] for r in rows))} babies")

# ⚠️ z-score against corpus stats BEFORE cosine. Without this every pair scores ~0.99.
X = np.array([r["fp"] for r in rows])
X = (X - X.mean(0)) / (X.std(0) + 1e-9)
X = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
S = X @ X.T

uuid = np.array([r["uuid"] for r in rows])
rec  = np.array([r["rec"] for r in rows])
lab  = np.array([r["label"] for r in rows])

byb = collections.Counter()
for u, r in {(r["uuid"], r["rec"]) for r in rows}: byb[u] += 1
multi = {u for u, c in byb.items() if c >= 2}
print(f"babies with >=2 separate recordings: {len(multi)}")

iu = np.triu_indices(len(rows), 1)
same_u = uuid[iu[0]] == uuid[iu[1]]
same_r = rec[iu[0]] == rec[iu[1]]
sim = S[iu]
in_multi = np.array([u in multi for u in uuid])[iu[0]] & \
           np.array([u in multi for u in uuid])[iu[1]]

A = sim[same_r]                              # same episode
B = sim[same_u & ~same_r & in_multi]         # same baby, DIFFERENT episode
C = sim[~same_u]                             # different babies

def d(x, y):
    return (x.mean() - y.mean()) / np.sqrt((x.var() + y.var()) / 2 + 1e-12)

def auc(pos, neg, n=300000):
    """P(random positive > random negative) - equal-sized paired sampling."""
    rs = np.random.default_rng(0)
    a = rs.choice(pos, n, replace=True)
    b = rs.choice(neg, n, replace=True)
    return (a > b).mean() + 0.5 * (a == b).mean()

print("\n=== cosine similarity distributions ===")
for nm, v in [("A same episode", A), ("B same baby, diff episode", B), ("C different babies", C)]:
    print(f"{nm:28} n={len(v):>8}  mean={v.mean():+.3f}  sd={v.std():.3f}")

print("\n=== THE DECISIVE TEST ===")
print(f"A vs B  (can similarity tell one episode from another, same baby?)")
print(f"   Cohen's d = {d(A,B):.2f}   AUC = {auc(A,B):.3f}")
print(f"B vs C  (does a baby's own cries resemble each other more than strangers'?)")
print(f"   Cohen's d = {d(B,C):.2f}   AUC = {auc(B,C):.3f}")

print("\n=== retrieval (query vs all segments from other recordings) ===")
Sx = S.copy(); np.fill_diagonal(Sx, -9)
hit_baby = tot = 0
for i in range(len(rows)):
    if uuid[i] not in multi: continue
    mask = rec != rec[i]
    if not mask.any(): continue
    j = np.where(mask)[0][np.argmax(Sx[i][mask])]
    hit_baby += uuid[j] == uuid[i]; tot += 1
base = np.mean([ (uuid == u).sum()/len(rows) for u in uuid if u in multi ])
print(f"top-1 retrieves SAME BABY: {hit_baby/tot:.1%}  (chance ~{base:.1%})  n={tot}")

json.dump({"A": float(A.mean()), "B": float(B.mean()), "C": float(C.mean()),
           "auc_AB": float(auc(A,B)), "auc_BC": float(auc(B,C)),
           "same_baby_top1": hit_baby/tot, "chance": float(base),
           "n_seg": len(rows)}, open("result.json","w"), indent=1)
