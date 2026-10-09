from PIL import Image

im = Image.open('/tmp/opencode/now.png').convert('L')
W, H = im.size
px = im.load()

# for each dark pixel, classify its local background: bright (>150) => on white card (UNCOVERED),
# dark (<=150) => on pill (ghost, acceptable)
def bg_bright(x, y):
    vals = []
    for dx in (-3, 3):
        for dy in (-3, 3):
            nx, ny = x + dx, y + dy
            if 0 <= nx < W and 0 <= ny < H:
                vals.append(px[nx, ny])
    return sum(vals) / len(vals)

def scan_uncovered(x0, y0, x1, y1, label, threshold=110):
    """find dark stroke pixels on bright background (i.e. CJK visible on the app's white cards)"""
    hits = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            v = px[x, y]
            if v < threshold and bg_bright(x, y) > 150:
                hits.append((x, y, v))
    if not hits:
        print(f"{label}: clean")
        return
    xs = [h[0] for h in hits]; ys = [h[1] for h in hits]
    print(f"{label}: {len(hits)} uncovered dark px, bbox x {min(xs)}..{max(xs)}, y {min(ys)}..{max(ys)}")
    # print a coarse histogram to see shape
    from collections import Counter
    cols = Counter(h[0] // 2 for h in hits)
    print("   cols:", sorted(cols.items())[:40])

# Regions of interest (device coords from a11y dump + margin), pill rects from win_dump:
# AC card: node 空调 (97,1283)-(173,1342), pill (97,1272) 279x81 -> (97..376, 1272..1353)
scan_uncovered(60, 1262, 200, 1365, "AC left sliver (x<97)")
scan_uncovered(90, 1345, 240, 1400, "AC below node (车内31.5 line, expected CJK visible - ref)")
# Energy: node 能量管理 (645,1302)-(797,1363), pill (645,1290) 187x85 -> (645..832,1290..1375)
scan_uncovered(600, 1285, 648, 1380, "Energy left sliver (x<645)")
# Digital key: node (199,1725)-(351,1786) pill (199,1715) 285x81 -> (199..484,1715..1796)
scan_uncovered(160, 1720, 202, 1800, "Key left sliver")
# My car title: node (51,205)-(215,266), pill (51,193) 274x85 -> (51..325,193..278)
scan_uncovered(30, 195, 54, 280, "Title left sliver")
# Grid tiles row: pills (39..250),(262..473),(485..696),(708..919) y 1120..1184; nodes y 1129..1175
scan_uncovered(30, 1122, 930, 1188, "Grid row whole", threshold=110)
