#!/usr/bin/env python3
"""Extract one Wakfu map area (or sub-region) into PNG frames + scene.json
for the web viewer.

Usage:
  python3 extract.py <area> [--radius N] [--maps DIR] [--out DIR]

  <area>     area id, e.g. 1000
  --radius   only include chunks with |X|<=N and |Y|<=N (default 2; -1 = all)
  --maps     wakfu maps dir (default /Applications/ankama/wakfu/contents/maps)
  --out      viewer data dir (default <repo>/viewer/data)
"""
import sys, os, json, zipfile, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wakfu

TILE_HW = 43.0     # half tile width  (iso X step)
TILE_QH = 21.5     # iso Y step per (col+row)
Z_STEP  = 10.0     # px per altitude unit


def extract_area(area, maps, elements, gfx_tex, tgam_names, out, tex_dir, radius=-1, light=False):
    """Extract one area into out/<area>/scene.json (+ shared tex pool).
    Returns a stats dict, or None if the area has no placements."""
    try:
        area_jar = zipfile.ZipFile(os.path.join(maps, 'gfx', f'{area}.jar'))
    except Exception:
        return None

    # ---- collect placements from selected chunks
    placements = []
    chunks = 0
    for name in area_jar.namelist():
        if name.startswith('META') or name in ('coord', 'groups.lib'):
            continue
        if '_' not in name:
            continue
        try:
            cx, cy = (int(t) for t in name.split('_'))
        except ValueError:
            continue
        if radius >= 0 and (abs(cx) > radius or abs(cy) > radius):
            continue
        try:
            placements += wakfu.parse_gfx_chunk(area_jar.read(name))
        except Exception:
            continue
        chunks += 1

    if not placements:
        return None

    # ---- which elements are used (and have a texture)
    used = sorted(set(p['elem'] for p in placements))
    out_area = os.path.abspath(os.path.join(out, str(area)))
    os.makedirs(out_area, exist_ok=True)

    elem_meta = {}
    skipped = set()
    for eid in used:
        e = elements.get(eid)
        if e is None or f"gfx/{e['cpE']}.tgam" not in tgam_names:
            skipped.add(eid)
            continue
        frames = []
        if e['afb'] is None:
            fn = f"{eid}_0.png"
            fp = os.path.join(tex_dir, fn)
            if not os.path.exists(fp):          # dedupe across areas
                w, h, pw, ph, tex = wakfu.decode_tgam(gfx_tex.read(f"gfx/{e['cpE']}.tgam"))
                wakfu.write_png(fp, w, h, wakfu.crop_rgba(tex, pw, 0, 0, w, h))
            frames.append(dict(f=fn, d=0))
        else:
            a = e['afb']
            fw, fh = a['fw'], a['fh']
            tex = None
            for i in range(a['n']):
                fn = f"{eid}_{i}.png"
                fp = os.path.join(tex_dir, fn)
                if not os.path.exists(fp):
                    if tex is None:
                        w, h, pw, ph, tex = wakfu.decode_tgam(gfx_tex.read(f"gfx/{e['cpE']}.tgam"))
                    fx, fy = a['coords'][2 * i], a['coords'][2 * i + 1]
                    wakfu.write_png(fp, fw, fh, wakfu.crop_rgba(tex, pw, fx, fy, fw, fh))
                frames.append(dict(f=fn, d=a['durs'][i]))
        elem_meta[eid] = dict(w=e['cpC'], h=e['cpD'], ox=e['cpy'], oy=e['cpz'],
                              frames=frames, period=(e['afb']['period'] if e['afb'] else 0),
                              cpK=e['cpK'])

    # ---- optional baked-light pass: per-cell multiply tint (neutral 0x808080).
    # Only confidently-placed chunks contribute (see decode_light.area_lightmap);
    # unlit cells stay 0xffffff (no change), so partial coverage is seamless.
    lightmap = {}
    if light:
        try:
            import decode_light
            occ = set((p['col'], p['row']) for p in placements)
            lightmap = decode_light.area_lightmap(area, occ)
        except Exception:
            lightmap = {}

    # ---- emit placements (precompute cell anchor in screen px, Y-down)
    # engine-true painter order: ascending (row, col, ccq), seq as stable tiebreak
    drawn = [p for p in placements if p['elem'] not in skipped]
    drawn.sort(key=lambda p: (p['row'], p['col'], p['ccq'], p['seq']))
    out_pl = []
    for p in drawn:
        ax = (p['col'] - p['row']) * TILE_HW
        ay = (p['col'] + p['row']) * TILE_QH - p['z'] * Z_STEP
        rec = [p['elem'], round(ax, 1), round(ay, 1),
               p['col'] + p['row'], p['z'], p['depth'], p['seq']]
        if lightmap:
            c = lightmap.get((p['col'], p['row']))
            # Game light is a multiply where 128 = neutral (1.0x). PixiJS tint uses
            # 255 = neutral, so rescale ch*255/128 (= ch*2) clamped. Pixi tint can
            # only darken (<=1.0), so highlights (>128) clamp to white = no overbright.
            if c:
                r = min(255, c[0] * 255 // 128); g = min(255, c[1] * 255 // 128)
                b = min(255, c[2] * 255 // 128)
                rec.append((r << 16) | (g << 8) | b)
            else:
                rec.append(0xffffff)
        out_pl.append(rec)

    scene = dict(area=area, chunks=chunks,
                 tile=dict(hw=TILE_HW, qh=TILE_QH, z=Z_STEP),
                 lit=bool(lightmap),
                 elements=elem_meta, placements=out_pl)
    with open(os.path.join(out_area, 'scene.json'), 'w') as f:
        json.dump(scene, f, separators=(',', ':'))

    return dict(area=area, chunks=chunks, placements=len(out_pl),
                elements=len(elem_meta), skipped=len(skipped))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('area', nargs='?', type=int)
    ap.add_argument('--all', action='store_true', help='extract every area jar')
    ap.add_argument('--radius', type=int, default=-1)
    ap.add_argument('--light', action='store_true', help='bake per-cell light tints into placements')
    ap.add_argument('--maps', default='/Applications/ankama/wakfu/contents/maps')
    ap.add_argument('--out', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'viewer', 'data'))
    args = ap.parse_args()

    maps = args.maps
    elements = wakfu.parse_elements(zipfile.ZipFile(os.path.join(maps, 'data.jar')).read('elements.lib'))
    gfx_tex = zipfile.ZipFile(os.path.join(maps, 'gfx.jar'))
    tgam_names = set(n for n in gfx_tex.namelist() if n.startswith('gfx/') and n.endswith('.tgam'))
    # SHARED texture pool: element id -> texture is global, so all areas share
    # one pool (out/tex). This avoids duplicating textures per-area on disk.
    tex_dir = os.path.abspath(os.path.join(args.out, 'tex'))
    os.makedirs(tex_dir, exist_ok=True)

    if args.all:
        area_ids = sorted(int(f[:-4]) for f in os.listdir(os.path.join(maps, 'gfx')) if f.endswith('.jar'))
    elif args.area is not None:
        area_ids = [args.area]
    else:
        ap.error('give an area id or --all')

    done = []
    for i, a in enumerate(area_ids):
        st = extract_area(a, maps, elements, gfx_tex, tgam_names, args.out, tex_dir, args.radius, args.light)
        if st:
            done.append(a)
            if not args.all:
                print(f"area {a}: {st['chunks']} chunks, {st['placements']} placements, "
                      f"{st['elements']} elements ({st['skipped']} skipped)")
        if args.all and (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(area_ids)} done, {len(done)} extracted...", flush=True)

    if args.all:
        with open(os.path.join(args.out, 'manifest.json'), 'w') as f:
            json.dump(dict(areas=done), f, separators=(',', ':'))
        print(f"extracted {len(done)} areas -> {args.out} (manifest.json written)")


if __name__ == '__main__':
    main()
