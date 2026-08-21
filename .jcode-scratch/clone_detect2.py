import hashlib
import pathlib
from collections import defaultdict

roots = [pathlib.Path("backend/app"), pathlib.Path("quant"), pathlib.Path("shared")]
files = []
for r in roots:
    files += [p for p in r.rglob("*.py") if "__pycache__" not in str(p) and "venv" not in str(p)]

WIN = 5
blocks = defaultdict(list)
for f in files:
    lines = f.read_text(errors="replace").splitlines()
    for i in range(len(lines) - WIN + 1):
        window = [ln.strip() for ln in lines[i : i + WIN]]
        if any(not w or w.startswith("#") for w in window):
            continue
        h = hashlib.md5("\n".join(window).encode()).hexdigest()
        blocks[h].append((str(f), i + 1))

pair_anchors = defaultdict(set)
for h, locs in blocks.items():
    if len(locs) < 2:
        continue
    for i in range(len(locs)):
        for j in range(i + 1, len(locs)):
            a, b = locs[i], locs[j]
            if a[0] == b[0]:
                continue
            key = tuple(sorted([a[0], b[0]]))
            aa, bb = (a[1], b[1]) if a[0] == key[0] else (b[1], a[1])
            pair_anchors[key].add((aa, bb))

results = []
for (fa, fb), anchors in pair_anchors.items():
    clusters = []
    for aa, ab in sorted(anchors):
        for c in clusters:
            if abs(c[-1][0] - aa) <= 2 and abs(c[-1][1] - ab) <= 2:
                c.append((aa, ab))
                break
        else:
            clusters.append([(aa, ab)])
    longest = max(len(c) for c in clusters)
    results.append((longest, len(anchors), fa, fb, max(clusters, key=len)))

results.sort(reverse=True)
print(f"{len(results)} file pairs share clones (window={WIN})")
for longest, total, fa, fb, cluster in results[:20]:
    print(f"  run~{longest*WIN:>3} lines  total~{total*WIN:>4} lines  {fa}:{cluster[0][0]} <-> {fb}:{cluster[0][1]}")
