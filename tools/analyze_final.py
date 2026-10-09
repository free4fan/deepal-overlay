import re

correct_bounds = 'bounds="' + r'\[(-?\d+),(-?\d+)\]' + r'\[(-?\d+),(-?\d+)\]' + '"'
node_re = re.compile(r'text="([^"]*)"[^>]*' + correct_bounds)

data = open('/tmp/opencode/car_dump.xml', encoding='utf-8').read()
nodes = [(m.group(1),) + tuple(map(int, m.groups()[1:])) for m in node_re.finditer(data)]
print("a11y nodes:", len(nodes))

out = open('/tmp/opencode/win_dump.txt', encoding='utf-8').read()
pw = re.compile('Window' + r'\{' + r'[0-9a-f]+ u0 com\.walter\.overlay\}:.*?mAttrs=\{' +
                r'\(' + r'(-?\d+)' + r',' + r'(-?\d+)' + r'\)\(' +
                r'(\d+)' + r'x' + r'(\d+)' + r'\)', re.S)
rects = [tuple(map(int, m.groups())) for m in pw.finditer(out)]
print("overlay windows:", len(rects))

def pill_for(node):
    t, l, tt, r, b = node
    cx, cy = (l + r) / 2, (tt + b) / 2
    cands = [q for q in rects if q[0] <= cx <= q[0] + q[2] and q[1] <= cy <= q[1] + q[3]]
    if not cands:
        return None
    return min(cands, key=lambda q: q[2] * q[3])

print(f"\n{'CJK source':<28} {'node (x,y) w x h':>22}  {'pill (x,y) w x h':>22}  status")
for node in sorted(nodes, key=lambda n: (n[2], n[1])):
    t, l, tt, r, b = node
    if not t:
        continue
    q = pill_for(node)
    if q:
        px, py, pw_, ph = q
        if px <= l and py <= tt and px + pw_ >= r and py + ph >= b:
            st = 'COVERED'
        else:
            edges = []
            if px > l: edges.append(f"left {l-px}px")
            if py > tt: edges.append(f"top {tt-py}px")
            if px + pw_ < r: edges.append(f"right {r-(px+pw_)}px")
            if py + ph < b: edges.append(f"bottom {b-(py+ph)}px")
            st = 'EXPOSED: ' + ', '.join(edges)
        pill_s = f"({px},{py}) {pw_}x{ph}"
    else:
        pill_s = "-"
        st = 'NO PILL'
    node_s = f"({l},{tt}) {r-l}x{b-tt}"
    print(f"{t:<28} {node_s:>22}  {pill_s:>22}  {st}")
