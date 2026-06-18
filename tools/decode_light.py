#!/usr/bin/env python3
"""Decode baked-lighting chunks (contents/maps/light/<area>.jar) and verify the
cellId->tile packing against the gfx floor footprint.

Container (little-endian, validated byte-exact 33/33 area-9 chunks):
  int16 baseX, baseY          signed chunk index (matches the "X_Y" entry name)
  int16 nGroups               light-colour palette size
  nGroups x { 0x80, RGBA, RGBA, RGBA }   13 bytes: marker + 3 vertex colours
  int16 tag                   small, purpose unknown (safely skipped)
  int16 nCells
  nCells x { int16 cellId, int16 paletteIdx }

CONFIRMED packing:  cellId = vy*36 + vx ,  tile = (vx//3, vy//3)
  -> 3x3 light-vertices per tile, 12x12 tiles per chunk.
  Proof: chunk 0_0's 1264 cells collapse to exactly 144 tiles (12x12) that match
  the gfx floor footprint with Jaccard = 1.000 at world offset (col-9, row-1).

CONFIRMED colour: multiply lightmap, neutral 0x80=128 (range seen 56..218),
  so tint = color/128  (128 -> 1.0x, 56 -> 0.44x, 218 -> 1.70x).

STILL OPEN: the chunk->world ORIGIN per chunk. Diagonal main chunks fit
  origin_col ~= 18*base + ~4 (+-2), but base 0_0 -> (-9,-1) is an outlier and
  non-origin rooms only reach Jaccard 0.5-0.8 vs floor-only occupancy (lit cells
  also cover walls/objects). Until the origin is pinned per area, do NOT push
  per-cell tints area-wide (would misalign and violate "look right").

Usage:
  python3 decode_light.py <area>            # summarize every light chunk
  python3 decode_light.py <area> --verify   # Jaccard-align each chunk vs gfx floor
"""
import os, sys, struct, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wakfu

MAPS = '/Applications/ankama/wakfu/contents/maps'
W = 36  # light-vertex stride (12 tiles * 3 vertices)


def parse_light(data):
    """Return dict(baseX, baseY, tag, groups=[[(r,g,b,a)x3]...], cells=[(cellId, palIdx)...])."""
    p = 0

    def rd(fmt):
        nonlocal p
        sz = struct.calcsize('<' + fmt)
        v = struct.unpack_from('<' + fmt, data, p)
        p += sz
        return v
    bx, by, ng = rd('3h')
    groups = []
    for _ in range(ng):
        p += 1                       # 0x80 marker
        groups.append([rd('4B') for _ in range(3)])
    tag, nc = rd('2h')
    cells = [rd('2h') for _ in range(nc)]
    assert p == len(data), (p, len(data))
    return dict(baseX=bx, baseY=by, tag=tag, groups=groups, cells=cells)


def light_chunks(area):
    lz = zipfile.ZipFile(os.path.join(MAPS, 'light', '%d.jar' % area))
    out = {}
    for n in lz.namelist():
        if '_' not in n or n.startswith('META'):
            continue
        out[n] = parse_light(lz.read(n))
    return out


def tile_colors(chunk):
    """Collapse a chunk's vertex cells to per-tile mean RGB (multiply lightmap)."""
    acc = {}
    for cid, pidx in chunk['cells']:
        if pidx >= len(chunk['groups']):
            continue
        tx, ty = (cid % W) // 3, (cid // W) // 3
        r = g = b = 0
        for (cr, cg, cb, _a) in chunk['groups'][pidx]:
            r += cr; g += cg; b += cb
        a = acc.setdefault((tx, ty), [0, 0, 0, 0])
        a[0] += r; a[1] += g; a[2] += b; a[3] += 3
    return {k: (v[0] // v[3], v[1] // v[3], v[2] // v[3]) for k, v in acc.items()}


def gfx_floor(area):
    gz = zipfile.ZipFile(os.path.join(MAPS, 'gfx', '%d.jar' % area))
    occ = set()
    for n in gz.namelist():
        if '_' not in n or n.startswith('META') or n in ('coord', 'groups.lib'):
            continue
        try:
            for p in wakfu.parse_gfx_chunk(gz.read(n)):
                occ.add((p['col'], p['row']))
        except Exception:
            pass
    return occ


def best_align(tiles, occ, guess):
    """Brute-force the (dcol,drow) world offset maximizing Jaccard of tiles vs occ."""
    gx, gy = guess
    best = (0.0, gx, gy)
    for ofx in range(gx - 40, gx + 40):
        for ofy in range(gy - 40, gy + 40):
            tr = {(tx + ofx, ty + ofy) for (tx, ty) in tiles}
            xs = [t[0] for t in tr]; ys = [t[1] for t in tr]
            lo = {c for c in occ if min(xs) <= c[0] <= max(xs) and min(ys) <= c[1] <= max(ys)}
            uni = len(tr | lo)
            j = len(tr & lo) / uni if uni else 0.0
            if j > best[0]:
                best = (j, ofx, ofy)
    return best


def area_lightmap(area, occ, min_tiles=8, min_prec=0.97):
    """Return {(col,row): (r,g,b)} baked light for an area.

    For each light chunk with >= min_tiles lit tiles, fit its world origin by
    precision-max against `occ` (set of occupied gfx (col,row)); keep it only if
    precision >= min_prec (every lit tile lands on a real cell). Tiny/ambiguous
    chunks are skipped, so we only emit light we can place confidently (the
    "look right, never misalign" rule). Colours are multiply tints, neutral 128.
    """
    try:
        chunks = light_chunks(area)
    except Exception:
        return {}
    lm = {}
    for name, c in chunks.items():
        tc = tile_colors(c)
        if len(tc) < min_tiles:
            continue
        tiles = set(tc.keys())
        hit, ofx, ofy = best_align_hits(tiles, occ, (18 * c['baseX'], 18 * c['baseY']))
        if hit / len(tiles) < min_prec:
            continue
        for (tx, ty), rgb in tc.items():
            lm[(tx + ofx, ty + ofy)] = rgb
    return lm


def best_align_hits(tiles, occ, guess):
    """Translate `tiles` to maximize how many land on `occ`; return (hits, dx, dy)."""
    gx, gy = guess
    best = (-1, gx, gy)
    for ofx in range(gx - 45, gx + 45):
        for ofy in range(gy - 45, gy + 45):
            hit = sum(1 for (tx, ty) in tiles if (tx + ofx, ty + ofy) in occ)
            if hit > best[0]:
                best = (hit, ofx, ofy)
    return best


def main():
    area = int(sys.argv[1])
    verify = '--verify' in sys.argv[2:]
    chunks = light_chunks(area)
    occ = gfx_floor(area) if verify else None
    for name in sorted(chunks, key=lambda n: tuple(int(x) for x in n.split('_'))):
        c = chunks[name]
        tiles = set(tile_colors(c).keys())
        line = (f"{name:>7}  base=({c['baseX']:3d},{c['baseY']:3d})  "
                f"nGroups={len(c['groups']):3d}  nCells={len(c['cells']):4d}  tiles={len(tiles):3d}")
        if verify and tiles:
            guess = (18 * c['baseX'], 18 * c['baseY'])
            j, ofx, ofy = best_align(tiles, occ, guess)
            line += f"  Jaccard={j:.2f}  origin=({ofx},{ofy})"
        print(line)


if __name__ == '__main__':
    main()
