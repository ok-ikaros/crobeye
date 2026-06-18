#!/usr/bin/env python3
"""Decisive offline test: does honouring the per-tile fx/fy flip flag make
edge/border tiles connect? Renders an area (or a crop) TWO ways:
  asis     - ignore flags (current viewer behaviour)
  flagflip - hflip the tile when fx=1, vflip when fy=1 (in place)
Outputs /tmp/flags/<area>_<mode>.png

Usage: python3 render_flags.py <area> [bx0 by0 bx1 by1]
"""
import os, sys, zipfile
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


def frame0_rgba(gfx, e):
    w, h, pw, ph, tex = wakfu.decode_tgam(gfx.read('gfx/%d.tgam' % e['cpE']))
    if e['afb'] is None:
        return w, h, wakfu.crop_rgba(tex, pw, 0, 0, w, h)
    a = e['afb']
    return a['fw'], a['fh'], wakfu.crop_rgba(tex, pw, a['coords'][0], a['coords'][1], a['fw'], a['fh'])


def scale_nn(rgba, sw, sh, dw, dh):
    out = bytearray(dw * dh * 4)
    for y in range(dh):
        sy = min(sh - 1, y * sh // dh)
        for x in range(dw):
            sx = min(sw - 1, x * sw // dw)
            si = (sy * sw + sx) * 4
            di = (y * dw + x) * 4
            out[di:di + 4] = rgba[si:si + 4]
    return bytes(out)


def flip(rgba, w, h, fx, fy):
    if not fx and not fy:
        return rgba
    out = bytearray(w * h * 4)
    for y in range(h):
        sy = (h - 1 - y) if fy else y
        for x in range(w):
            sx = (w - 1 - x) if fx else x
            si = (sy * w + sx) * 4
            di = (y * w + x) * 4
            out[di:di + 4] = rgba[si:si + 4]
    return bytes(out)


def main():
    area = int(sys.argv[1])
    elements, pls = load(area)
    gfx = zipfile.ZipFile(os.path.join(MAPS, 'gfx.jar'))

    drawn = []
    for p in pls:
        e = elements.get(p['elem'])
        if e is None or ('gfx/%d.tgam' % e['cpE']) not in gfx.namelist():
            continue
        ax = (p['col'] - p['row']) * TILE_HW
        ay = (p['col'] + p['row']) * TILE_QH - p['z'] * Z_STEP
        bx = ax - e['cpy']; by = ay - e['cpz']
        drawn.append((p, e, bx, by, e['cpC'], e['cpD']))
    drawn.sort(key=lambda t: (t[0]['row'], t[0]['col'], t[0]['ccq'], t[0]['seq']))

    if len(sys.argv) >= 6:
        BX0, BY0, BX1, BY1 = (float(v) for v in sys.argv[2:6])
    else:
        BX0 = min(t[2] for t in drawn); BY0 = min(t[3] for t in drawn)
        BX1 = max(t[2] + t[4] for t in drawn); BY1 = max(t[3] + t[5] for t in drawn)
    drawn = [t for t in drawn if not (t[2] + t[4] < BX0 or t[2] > BX1 or t[3] + t[5] < BY0 or t[3] > BY1)]
    print('tiles in view:', len(drawn), 'bbox', (BX0, BY0, BX1, BY1))

    CW, CH = int(BX1 - BX0), int(BY1 - BY0)
    scale = 1.0
    if CW * CH > 4_000_000:           # cap canvas work
        scale = (4_000_000 / (CW * CH)) ** 0.5
        CW, CH = int(CW * scale), int(CH * scale)
    print('canvas', CW, CH, 'scale', round(scale, 3))
    os.makedirs('/tmp/flags', exist_ok=True)
    cache = {}

    for mode in ('asis', 'flagflip'):
        canvas = bytearray(b'\x1b\x23\x30\xff' * (CW * CH))
        for (p, e, bx, by, w, h) in drawn:
            key = e['cpx']
            if key not in cache:
                cache[key] = frame0_rgba(gfx, e)
            cw_, ch_, raw = cache[key]
            dw, dh = max(1, int(w * scale)), max(1, int(h * scale))
            disp = scale_nn(raw, cw_, ch_, dw, dh)
            if mode == 'flagflip':
                disp = flip(disp, dw, dh, p['fx'], p['fy'])
            ox0 = int(round((bx - BX0) * scale)); oy0 = int(round((by - BY0) * scale))
            for ty in range(dh):
                cy = oy0 + ty
                if cy < 0 or cy >= CH:
                    continue
                base = cy * CW
                row = ty * dw
                for tx in range(dw):
                    cx = ox0 + tx
                    if cx < 0 or cx >= CW:
                        continue
                    si = (row + tx) * 4
                    sa = disp[si + 3]
                    if sa == 0:
                        continue
                    di = (base + cx) * 4
                    ia = 255 - sa
                    canvas[di] = (disp[si] * sa + canvas[di] * ia) // 255
                    canvas[di + 1] = (disp[si + 1] * sa + canvas[di + 1] * ia) // 255
                    canvas[di + 2] = (disp[si + 2] * sa + canvas[di + 2] * ia) // 255
                    canvas[di + 3] = 255
        wakfu.write_png('/tmp/flags/%d_%s.png' % (area, mode), CW, CH, bytes(canvas))
        print('wrote', mode)


if __name__ == '__main__':
    main()
