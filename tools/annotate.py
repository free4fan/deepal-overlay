import re
from PIL import Image, ImageDraw

out = open('/tmp/opencode/win_dump.txt', encoding='utf-8').read()
pw = re.compile('Window' + r'\{' + r'[0-9a-f]+ u0 com\.walter\.overlay\}:.*?mAttrs=\{' +
                r'\(' + r'(-?\d+)' + r',' + r'(-?\d+)' + r'\)\(' +
                r'(\d+)' + r'x' + r'(\d+)' + r'\)', re.S)
rects = [tuple(map(int, m.groups())) for m in pw.finditer(out)]
print("rects:", len(rects))
for r in sorted(rects, key=lambda r: (r[1], r[0])):
    print(f"  ({r[0]},{r[1]}) {r[2]}x{r[3]}")

im = Image.open('/tmp/opencode/now.png').convert('RGB')
d = ImageDraw.Draw(im)
for i, (x, y, w, h) in enumerate(sorted(rects, key=lambda r: (r[1], r[0]))):
    col = (255, 0, 0) if i % 2 == 0 else (0, 130, 255)
    d.rectangle([x, y, x + w, y + h], outline=col, width=2)
    d.text((x + w - 4, y), str(i), fill=(255, 255, 0))
im.save('/tmp/opencode/annotated.png')
# zoom the AC card with annotation
im.crop((33, 1224, 925, 1460)).resize((892 * 2, 236 * 2), Image.NEAREST).save('/tmp/opencode/annotated_ac.png')
im.crop((33, 1000, 927, 1230)).resize((894, 230), Image.NEAREST).save('/tmp/opencode/annotated_grid.png')
print("saved")
