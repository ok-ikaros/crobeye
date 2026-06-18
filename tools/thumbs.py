#!/usr/bin/env python3
"""Render a small PNG preview thumbnail per Wakfu map area for the catalog.

Reuses the exact extract.py compositing path (parse gfx chunks -> painter order
-> decode_tgam -> alpha-composite), but rasterises at a tiny target size with a
pure-stdlib nearest-neighbour over-blend. No PIL/numpy.

Output: viewer/data/<area>/thumb.png

Usage:
  python3 thumbs.py <area>            # one area
  python3 thumbs.py --all             # every extracted area (skips existing)
  python3 thumbs.py --all --force     # re-render all
"""
import sys, os, json, zipfile, argparse, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wakfu

TILE_HW = 43.0
TILE_QH = 21.5
Z_STEP = 10.0
TARGET = 300          # max thumbnail dimension (px)
BG = (0x1b, 0x23, 0x30)   # viewer background, so thumbs match the canvas


def frame0_rgba(e, gfx_tex):
    """Decode the first animation frame of an element -> (rgba, fw, fh)."""
    w, h, pw, ph, tex = wakfu.decode_tgam(gfx_tex.read(f"gfx/{e['cpE']}.tgam"))
    if e['afb'] is None:
        return wakfu.crop_rgba(tex, pw, 0, 0, w, h), w, h
    a = e['afb']
    fw, fh = a['fw'], a['fh']
    fx, fy = a['coords'][0], a['coords'][1]
    return wakfu.crop_rgba(tex, pw, fx, fy, fw, fh), fw, fh


def render_area(area, maps, elements, gfx_tex, tgam_names, target=TARGET):
    """Composite an area into a `target`-bounded RGB buffer. Returns (buf, w, h)."""
    try:
        area_jar = zipfile.ZipFile(os.path.join(maps, 'gfx', f'{area}.jar'))
    except Exception:
        return None

    placements = []
    for name in area_jar.namelist():
        if name.startswith('META') or name in ('coord', 'groups.lib') or '_' not in name:
            continue
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

    # element render metadata + first-frame pixels (decoded once, cached)
    meta = {}          # eid -> (w,h,ox,oy)
    pix = {}           # eid -> (rgba, fw, fh)
    for eid in set(p['elem'] for p in placements):
        e = elements.get(eid)
        if e is None or f"gfx/{e['cpE']}.tgam" not in tgam_names:
            continue
        try:
            pix[eid] = frame0_rgba(e, gfx_tex)
        except Exception:
            continue
        meta[eid] = (e['cpC'], e['cpD'], e['cpy'], e['cpz'])

    drawn = [p for p in placements if p['elem'] in meta]
    if not drawn:
        return None
    drawn.sort(key=lambda p: (p['row'], p['col'], p['ccq'], p['seq']))

    # world (screen-px) bounds of all display boxes
    minX = minY = float('inf')
    maxX = maxY = float('-inf')
    for p in drawn:
        w, h, ox, oy = meta[p['elem']]
        ax = (p['col'] - p['row']) * TILE_HW
        ay = (p['col'] + p['row']) * TILE_QH - p['z'] * Z_STEP
        bx, by = ax - ox, ay - oy
        minX = min(minX, bx); minY = min(minY, by)
        maxX = max(maxX, bx + w); maxY = max(maxY, by + h)

    cw, ch = maxX - minX, maxY - minY
    if cw <= 0 or ch <= 0:
        return None
    scale = target / max(cw, ch)
    tw = max(1, min(target, math.ceil(cw * scale)))
    th = max(1, min(target, math.ceil(ch * scale)))

    # RGB buffer pre-filled with the viewer background
    buf = bytearray(BG * (tw * th))

    for p in drawn:
        w, h, ox, oy = meta[p['elem']]
        rgba, fw, fh = pix[p['elem']]
        ax = (p['col'] - p['row']) * TILE_HW
        ay = (p['col'] + p['row']) * TILE_QH - p['z'] * Z_STEP
        bx, by = ax - ox, ay - oy
        dx0 = (bx - minX) * scale
        dy0 = (by - minY) * scale
        dw = w * scale
        dh = h * scale
        x0 = max(0, int(dx0)); x1 = min(tw, math.ceil(dx0 + dw))
        y0 = max(0, int(dy0)); y1 = min(th, math.ceil(dy0 + dh))
        if x1 <= x0 or y1 <= y0 or dw <= 0 or dh <= 0:
            continue
        # precompute source column lookup for this sprite
        sx = [min(fw - 1, max(0, int((dx + 0.5 - dx0) / dw * fw))) for dx in range(x0, x1)]
        for dy in range(y0, y1):
            sy = min(fh - 1, max(0, int((dy + 0.5 - dy0) / dh * fh)))
            srow = sy * fw * 4
            drow = (dy * tw + x0) * 3
            for k, dx in enumerate(range(x0, x1)):
                si = srow + sx[k] * 4
                a = rgba[si + 3]
                if a == 0:
                    continue
                di = drow + k * 3
                if a == 255:
                    buf[di] = rgba[si]; buf[di + 1] = rgba[si + 1]; buf[di + 2] = rgba[si + 2]
                else:
                    ia = 255 - a
                    buf[di] = (rgba[si] * a + buf[di] * ia) // 255
                    buf[di + 1] = (rgba[si + 1] * a + buf[di + 1] * ia) // 255
                    buf[di + 2] = (rgba[si + 2] * a + buf[di + 2] * ia) // 255

    return buf, tw, th


def write_rgb_png(path, w, h, rgb):
    """PNG writer for an RGB (3-channel) buffer (stdlib zlib)."""
    import struct, zlib
    def chunk(typ, dat):
        c = typ + dat
        return struct.pack('>I', len(dat)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    raw = bytearray()
    stride = w * 3
    for y in range(h):
        raw.append(0)
        raw += rgb[y * stride:(y + 1) * stride]
    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(bytes(raw), 6))
    png += chunk(b'IEND', b'')
    with open(path, 'wb') as f:
        f.write(png)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('area', nargs='?', type=int)
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--maps', default='/Applications/ankama/wakfu/contents/maps')
    ap.add_argument('--out', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'viewer', 'data'))
    args = ap.parse_args()

    elements = wakfu.parse_elements(zipfile.ZipFile(os.path.join(args.maps, 'data.jar')).read('elements.lib'))
    gfx_tex = zipfile.ZipFile(os.path.join(args.maps, 'gfx.jar'))
    tgam_names = set(n for n in gfx_tex.namelist() if n.startswith('gfx/') and n.endswith('.tgam'))

    if args.all:
        areas = sorted(int(d) for d in os.listdir(args.out)
                       if d.isdigit() and os.path.isdir(os.path.join(args.out, d)))
    elif args.area is not None:
        areas = [args.area]
    else:
        ap.error('give an area id or --all')

    done = skipped = failed = 0
    for i, a in enumerate(areas):
        out_png = os.path.join(args.out, str(a), 'thumb.png')
        if os.path.exists(out_png) and not args.force:
            skipped += 1
            continue
        try:
            res = render_area(a, args.maps, elements, gfx_tex, tgam_names)
        except Exception as ex:
            res = None
            if not args.all:
                print(f"area {a}: error {ex}")
        if res is None:
            failed += 1
            continue
        buf, w, h = res
        os.makedirs(os.path.dirname(out_png), exist_ok=True)
        write_rgb_png(out_png, w, h, buf)
        done += 1
        if not args.all:
            print(f"area {a}: thumb {w}x{h} -> {out_png}")
        elif (i + 1) % 25 == 0:
            print(f"  {i+1}/{len(areas)}  done={done} skipped={skipped} failed={failed}", flush=True)

    if args.all:
        print(f"thumbnails: done={done} skipped={skipped} failed={failed}")


if __name__ == '__main__':
    main()
