from PIL import Image

im = Image.open('/tmp/opencode/now.png').convert('L')
W, H = im.size
px = im.load()

def local_bg_bright(x, y, r=3):
    vals = []
    for dx in range(-r, r+1, 6):
        for dy in range(-r, r+1, 6):
            nx, ny = x + dx, y + dy
            if 0 <= nx < W and 0 <= ny < H:
                vals.append(px[nx, ny])
    return sum(vals) / len(vals)

def uncovered(outside_rects, x0, y0, x1, y1, label, threshold=110, dilate=6):
    hits = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            if any(rx0 - dilate <= x <= rx1 + dilate and ry0 - dilate <= y <= ry1 + dilate
                   for (rx0, ry0, rx1, ry1) in outside_rects):
                continue
            v = px[x, y]
            if v < threshold and local_bg_bright(x, y) > 150:
                hits.append((x, y))
    if not hits:
        print(f"{label}: CLEAN")
        return
    xs = [h[0] for h in hits]; ys = [h[1] for h in hits]
    print(f"{label}: {len(hits)} px, bbox x {min(xs)}..{max(xs)}, y {min(ys)}..{max(ys)}")
    from collections import Counter
    # 8px buckets over x to show which columns carry strokes
    buckets = Counter(x // 8 for x in xs)
    print("   x-buckets(8):", sorted((k*8, v) for k, v in buckets.items()))

P = {  # pill rects (x0,y0,x1,y1) from win_dump
 'title': (51,193,325,278),
 'parked': (51,278,666,341),
 'lock': (39,1120,250,1184),
 'windows': (262,1120,473,1184),
 'trunk': (485,1120,696,1184),
 'horn': (708,1120,919,1184),
 'ac': (97,1272,376,1353),
 'energy': (645,1290,832,1375),
 'key': (199,1715,484,1796),
 'bt': (199,1784,488,1844),
 'addr': (497,1739,952,1881),
}

# 1) AC card area, excluding the AC pill
uncovered([P['ac']], 33, 1224, 479, 1670, "AC card (excl pill)")
# 2) Energy card, excluding energy pill
uncovered([P['energy']], 479, 1224, 925, 1447, "Energy card (excl pill)")
# 3) Grid tiles row, excluding the 4 pills
uncovered([P['lock'], P['windows'], P['trunk'], P['horn']], 33, 1001, 927, 1224, "Grid tiles row")
# 4) Digital key row, excluding key+bt pills
uncovered([P['key'], P['bt']], 33, 1670, 479, 1893, "Digital key row")
# 5) Header: title + parked
uncovered([P['title'], P['parked']], 22, 174, 700, 360, "Header top")
# 6) Map card (address pill covers most)
uncovered([P['addr']], 479, 1447, 925, 1670, "Map card (excl addr pill)")
