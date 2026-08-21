import hashlib
import pathlib
from collections import defaultdict

root = pathlib.Path("app")
files = [p for p in root.rglob("*.py") if "__pycache__" not in str(p)]
WIN = 8
blocks = defaultdict(list)  # hash -> list[(file, start, end)]
for f in files:
    src = f.read_text().splitlines()
    norm = []
    for ln in src:
        s = ln.strip()
        if not s or s.startswith("#"):
            norm.append(None)
            continue
        norm.append(s)
    for i in range(len(norm) - WIN + 1):
        window = norm[i : i + WIN]
        if any(w is None for w in window):
            continue
        h = hashlib.md5("\n".join(window).encode()).hexdigest()
        blocks[h].append((str(f), i + 1, i + WIN))

# merge overlapping windows into clone regions per file-pair
pair_regions = defaultdict(set)  # (fileA, fileB) -> set of (a_start, b_start)
for h, locs in blocks.items():
    if len(locs) < 2:
        continue
    for i in range(len(locs)):
        for j in range(i + 1, len(locs)):
            a, b = locs[i], locs[j]
            if a[0] == b[0]:
                continue
            key = tuple(sorted([a[0], b[0]]))
            pair_regions[key].add((a[1], b[1]) if a[0] == key[0] else (b[1], a[1]))

results = []
for (fa, fb), anchors in pair_regions.items():
    # count distinct anchor clusters (allow 3-line drift)
    clusters = []
    for aa, ab in sorted(anchors):
        placed = False
        for c in clusters:
            if abs(c[0][0] - aa) <= 3 and abs(c[0][1] - ab) <= 3:
                c.append((aa, ab))
                placed = True
                break
        if not placed:
            clusters.append([(aa, ab)])
    biggest = max(len(c) for c in clusters)
    total_anchors = len(anchors)
    results.append((total_anchors, biggest, fa, fb))

results.sort(reverse=True)
print(f"{len(results)} file pairs share duplicated blocks (window={WIN})")
for total, biggest, fa, fb in results[:25]:
    print(f"  ~{total*WIN:>4} lines dup | longest run ~{biggest*WIN} lines | {fa} <-> {fb}")
