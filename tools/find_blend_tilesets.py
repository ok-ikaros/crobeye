#!/usr/bin/env python3
"""Pinpoint "edge-blend tile-sets" in an area so we STOP re-investigating their
baked mis-orientation (see memory: this is the game's own data, not a viewer
bug — there is no flag lever, staying faithful is the chosen behaviour).

An edge-blend tile-set = a single texture (cpE) referenced by BOTH an `0xa0`
("back" layer) and a `0xb0` ("front" layer) element — the depth-split signature
shared by the arena rope fence, the poker-felt mats, the banquet-table tops, and
the shoreline foam family. Their edge art is baked directional; whichever way an
edge faces is fixed by element selection, NOT by per-tile flags.

Usage: python3 find_blend_tilesets.py <area>
Prints each tile-set: shared texture, its 0xa0/0xb0 element ids, instance count,
and the world-space (bx,by) clusters where it occurs (so you can locate it in
the viewer). Anything it lists is faithful-by-design.
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


def cluster_centroids(coords, gap=400.0):
    """Group (bx,by) points into rough clusters by y-band, return centroids."""
    if not coords:
        return []
    coords = sorted(coords, key=lambda c: c[1])
    bands, cur = [], [coords[0]]
    for c in coords[1:]:
        if c[1] - cur[-1][1] > gap:
            bands.append(cur); cur = [c]
        else:
            cur.append(c)
    bands.append(cur)
    return [(sum(x for x, _ in b) / len(b), sum(y for _, y in b) / len(b), len(b)) for b in bands]


def main():
    area = int(sys.argv[1])
    elements, pls = load(area)

    # map texture -> {cpK class -> set(elem)}, and elem -> placements coords
    tex_classes = collections.defaultdict(lambda: collections.defaultdict(set))
    coords_by_tex = collections.defaultdict(list)
    for p in pls:
        e = elements.get(p['elem'])
        if e is None:
            continue
        k = e['cpK']
        if k not in (0x90, 0xa0, 0xb0):
            continue
        tex_classes[e['cpE']][k].add(p['elem'])
        ax = (p['col'] - p['row']) * TILE_HW
        ay = (p['col'] + p['row']) * TILE_QH - p['z'] * Z_STEP
        coords_by_tex[e['cpE']].append((ax - e['cpy'], ay - e['cpz']))

    sets = []
    for tex, classes in tex_classes.items():
        if 0xa0 in classes and 0xb0 in classes:        # the depth-split signature
            sets.append((tex, classes, coords_by_tex[tex]))
    sets.sort(key=lambda s: -len(s[2]))

    print(f"area {area}: {len(sets)} edge-blend tile-sets (0xa0+0xb0 shared texture) — all faithful-by-design\n")
    for tex, classes, coords in sets:
        elems = sorted(set().union(*classes.values()))
        cls = '/'.join('0x%02x:%s' % (k, ','.join(map(str, sorted(classes[k])))) for k in sorted(classes))
        print(f"tex {tex:<7} n={len(coords):<4} elems[{cls}]")
        for cx, cy, n in cluster_centroids(coords):
            print(f"        cluster bx={cx:7.0f} by={cy:8.0f}  x{n}")


if __name__ == '__main__':
    main()
