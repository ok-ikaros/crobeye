#!/usr/bin/env python3
"""Scan every Wakfu map area and emit a browsable catalog (index.json) with a
DERIVED type classification (island / forest / town / dungeon / ...).

No semantic labels exist in the data, so we classify by COMPOSITION: the
coverage-weighted average colour of each area's tiles (water reads blue,
vegetation green, sand tan, stone/urban grey), plus structural signals
(animated-foam fraction => coastal, vertical sprites => trees/props).

Pure stdlib. Texture colours are cached by tgam id so the cost is paid once
across all 960 areas.

Usage: python3 catalog.py [--maps DIR] [--out FILE] [--limit N] [--area A]
"""
import sys, os, json, zipfile, argparse, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wakfu

TILE_HW, TILE_QH, Z_STEP = 43.0, 21.5, 10.0


def elem_avg_color(gfx_tex, tgam_names, cpE, cache):
    """Coverage avg (r,g,b) over opaque content pixels of a tgam, sampled."""
    if cpE in cache:
        return cache[cpE]
    name = f"gfx/{cpE}.tgam"
    if name not in tgam_names:
        cache[cpE] = None
        return None
    try:
        w, h, pw, ph, tex = wakfu.decode_tgam(gfx_tex.read(name))
    except Exception:
        cache[cpE] = None
        return None
    # sample up to ~24x24 grid of content pixels
    sx = max(1, w // 24)
    sy = max(1, h // 24)
    r = g = b = n = 0
    for y in range(0, h, sy):
        row = (y * pw) * 4
        for x in range(0, w, sx):
            i = row + x * 4
            a = tex[i + 3]
            if a < 40:
                continue
            r += tex[i]; g += tex[i + 1]; b += tex[i + 2]; n += 1
    res = None if n == 0 else (r / n, g / n, b / n, n)
    cache[cpE] = res
    return res


def color_bucket(r, g, b):
    """Crude perceptual bucket for a tile's average colour."""
    mx, mn = max(r, g, b), min(r, g, b)
    sat = mx - mn
    lum = (r + g + b) / 3
    if lum < 45:
        return 'dark'
    if sat < 26:               # near-grey
        return 'stone' if lum < 180 else 'lightstone'
    if b > r + 12 and b >= g - 6:
        return 'water'
    if g > r + 8 and g >= b + 8:
        return 'grass'
    if r > 150 and g > 120 and b < g and (r - b) > 25 and g > b:
        return 'sand'
    if r > g and r > b:
        return 'warm'         # wood / rock / earth
    return 'other'


def classify(buckets, foam_frac, n_sprites):
    """buckets: bucket -> coverage weight (already normalised to fractions).

    Water is a BACKGROUND plane, so a water-dominant map is only 'open-water'
    when there's essentially no land. Any meaningful land sitting in water is an
    island / coastal map (that's how a player reads it)."""
    water = buckets.get('water', 0)
    grass = buckets.get('grass', 0)
    sand = buckets.get('sand', 0)
    stone = buckets.get('stone', 0) + buckets.get('lightstone', 0)
    warm = buckets.get('warm', 0)
    dark = buckets.get('dark', 0)
    land = grass + sand + stone + warm

    # --- water-context maps ---
    if water > 0.35 and land < 0.06:
        return 'open-water'
    if water > 0.2 or foam_frac > 0.06:
        if sand > 0.06 or foam_frac > 0.05:
            return 'island'
        if grass > 0.06 or stone > 0.06:
            return 'coastal'
        return 'open-water'

    # --- land maps (renormalise within land so background doesn't skew) ---
    if grass > 0.4:
        return 'forest'
    if grass > 0.18 and grass >= stone and grass >= warm:
        return 'grassland'
    if stone > 0.4 and dark > 0.1:
        return 'dungeon'
    if stone > 0.3:
        return 'town'
    if sand > 0.4:
        return 'desert'
    if warm > 0.4 and dark > 0.05:
        return 'cavern'
    if warm > 0.4:
        return 'interior'
    if dark > 0.3:
        return 'dungeon'
    return 'mixed'


def env_preset(env_zip, chunk_names):
    """Best-effort: pull the length-prefixed ASCII preset id from an env chunk."""
    for cn in chunk_names:
        try:
            d = env_zip.read(cn)
        except KeyError:
            continue
        # scan for a run of ascii digits length>=3 preceded by a small length byte
        for i in range(len(d) - 4):
            L = d[i]
            if 2 <= L <= 8 and i + 1 + L <= len(d):
                s = d[i + 1:i + 1 + L]
                if s.isdigit():
                    return s.decode()
        return None
    return None


def scan_area(area, maps, elements, gfx_tex, tgam_names, color_cache):
    try:
        area_jar = zipfile.ZipFile(os.path.join(maps, 'gfx', f'{area}.jar'))
    except Exception:
        return None
    chunk_names = [n for n in area_jar.namelist()
                   if '_' in n and not n.startswith('META') and n not in ('coord', 'groups.lib')]
    placements = []
    for name in chunk_names:
        try:
            int(name.split('_')[0]); int(name.split('_')[1])
        except ValueError:
            continue
        try:
            placements += wakfu.parse_gfx_chunk(area_jar.read(name))
        except Exception:
            continue
    if not placements:
        return None

    buckets = {}
    foam = 0
    minc = minr = 10**9
    maxc = maxr = -10**9
    for p in placements:
        e = elements.get(p['elem'])
        if e is None:
            continue
        col, row = p['col'], p['row']
        minc = min(minc, col); maxc = max(maxc, col)
        minr = min(minr, row); maxr = max(maxr, row)
        if e['afb'] is not None and e['cpK'] in (0xa0, 0xb0):
            foam += 1
        c = elem_avg_color(gfx_tex, tgam_names, e['cpE'], color_cache)
        if c is None:
            continue
        r, g, bl, _ = c
        wgt = max(1, e['cpC'] * e['cpD'])
        bk = color_bucket(r, g, bl)
        buckets[bk] = buckets.get(bk, 0) + wgt

    total = sum(buckets.values()) or 1
    frac = {k: v / total for k, v in buckets.items()}
    foam_frac = foam / len(placements)
    typ = classify(frac, foam_frac, len(placements))

    # env preset (best-effort)
    preset = None
    try:
        ez = zipfile.ZipFile(os.path.join(maps, 'env', f'{area}.jar'))
        ecn = [n for n in ez.namelist() if '_' in n and not n.startswith('META')]
        preset = env_preset(ez, ecn[:1])
    except Exception:
        pass

    return dict(
        area=area, type=typ,
        chunks=len(chunk_names), sprites=len(placements),
        cells=[maxc - minc + 1, maxr - minr + 1] if maxc >= minc else [0, 0],
        foam=round(foam_frac, 3),
        env=preset,
        palette={k: round(v, 3) for k, v in sorted(frac.items(), key=lambda kv: -kv[1])},
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--maps', default='/Applications/ankama/wakfu/contents/maps')
    ap.add_argument('--out', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'viewer', 'index.json'))
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--area', type=int, default=0)
    args = ap.parse_args()

    elements = wakfu.parse_elements(zipfile.ZipFile(os.path.join(args.maps, 'data.jar')).read('elements.lib'))
    gfx_tex = zipfile.ZipFile(os.path.join(args.maps, 'gfx.jar'))
    tgam_names = set(n for n in gfx_tex.namelist() if n.startswith('gfx/') and n.endswith('.tgam'))

    area_files = sorted(int(f[:-4]) for f in os.listdir(os.path.join(args.maps, 'gfx')) if f.endswith('.jar'))
    if args.area:
        area_files = [args.area]
    elif args.limit:
        area_files = area_files[:args.limit]

    color_cache = {}
    out = []
    for i, a in enumerate(area_files):
        rec = scan_area(a, args.maps, elements, gfx_tex, tgam_names, color_cache)
        if rec:
            out.append(rec)
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(area_files)} scanned...", file=sys.stderr)

    if args.area or args.limit:
        for rec in out:
            print(json.dumps(rec))
    else:
        with open(args.out, 'w') as f:
            json.dump(dict(count=len(out), areas=out), f, separators=(',', ':'))
        print(f"wrote {len(out)} areas -> {args.out}")
        from collections import Counter
        print(Counter(r['type'] for r in out))


if __name__ == '__main__':
    main()
