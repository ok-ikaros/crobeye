#!/usr/bin/env python3
"""Dump per-tile flags + element class for a world-space crop of an area, so we
can see whether mis-oriented tile groups (rope fence, poker-table mats, white
table tops) share a consistent flag signature we currently ignore.

Usage: python3 inspect_room.py <area> <by0> <by1> [bx0 bx1]
Prints, grouped by element id: count, cpK, tex id (cpE), quad cpCxcpD vs full
cpAxcpB, and the distribution of (tr,fx,fy,grad) flag combos across instances.
"""
import os, sys, zipfile, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wakfu

TILE_HW, TILE_QH, Z_STEP = 43.0, 21.5, 10.0
MAPS = '/Applications/ankama/wakfu/contents/maps'


def load(area):
    elements = wakfu.parse_elements(zipfile.ZipFile(os.path.join(MAPS, 'data.jar')).read('elements.lib'))
    az = zipfile.ZipFile(os.path.join(MAPS, 'gfx', '%d.jar' % area))
    pls = []
    for n in az.namelist():
        if '_' not in n or n.startswith('META') or n in ('coord', 'groups.lib'):
            continue
        try:
            int(n.split('_')[0]); int(n.split('_')[1])
        except ValueError:
            continue
        try:
            pls += wakfu.parse_gfx_chunk(az.read(n))
        except Exception:
            pass
    return elements, pls


def main():
    area = int(sys.argv[1])
    BY0, BY1 = float(sys.argv[2]), float(sys.argv[3])
    BX0 = float(sys.argv[4]) if len(sys.argv) > 4 else -1e9
    BX1 = float(sys.argv[5]) if len(sys.argv) > 5 else 1e9
    elements, pls = load(area)

    rows = []
    for p in pls:
        e = elements.get(p['elem'])
        if e is None:
            continue
        ax = (p['col'] - p['row']) * TILE_HW
        ay = (p['col'] + p['row']) * TILE_QH - p['z'] * Z_STEP
        bx = ax - e['cpy']; by = ay - e['cpz']
        if by < BY0 or by > BY1 or bx < BX0 or bx > BX1:
            continue
        rows.append((p, e, bx, by))

    print('tiles in crop:', len(rows))
    by_elem = collections.defaultdict(list)
    for (p, e, bx, by) in rows:
        by_elem[p['elem']].append((p, e, bx, by))

    # summarize, ordered by count desc
    for elem, items in sorted(by_elem.items(), key=lambda kv: -len(kv[1])):
        e = items[0][1]
        flagdist = collections.Counter((p['tr'], p['fx'], p['fy'], p['grad']) for (p, _, _, _) in items)
        print('elem %6d  n=%3d  cpK=0x%02x  tex=%d  quad=%dx%d full=%dx%d  cpy,cpz=%d,%d'
              % (elem, len(items), e['cpK'], e['cpE'], e['cpC'], e['cpD'], e['cpA'], e['cpB'], e['cpy'], e['cpz']))
        for combo, c in sorted(flagdist.items()):
            print('        tr,fx,fy,grad=%s  x%d' % (combo, c))


if __name__ == '__main__':
    main()
