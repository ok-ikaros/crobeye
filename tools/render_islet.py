#!/usr/bin/env python3
"""Render ONE islet region of area 1000 to PNGs under several per-tile
content transforms, so we can judge shore-gradient facing crisply offline
(no browser). Each mode keeps tile POSITIONS identical and only transforms
the tile's pixels in place: normal / hflip / vflip / rot180.

Usage: python3 render_islet.py
Outputs /tmp/islet/<mode>.png
"""
import os, sys, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wakfu

TILE_HW, TILE_QH, Z_STEP = 43.0, 21.5, 10.0
MAPS = '/Applications/ankama/wakfu/contents/maps'

# world bbox of islet A (from viewer focusRect), generous margin
BX0, BY0, BX1, BY1 = -2120, -620, -1580, -250


def load_placements():
    elements = wakfu.parse_elements(zipfile.ZipFile(os.path.join(MAPS, 'data.jar')).read('elements.lib'))
    area = zipfile.ZipFile(os.path.join(MAPS, 'gfx', '1000.jar'))
    pls = []
    for name in area.namelist():
        if name.startswith('META') or name in ('coord', 'groups.lib') or '_' not in name:
            continue
        try:
            cx, cy = (int(t) for t in name.split('_'))
        except ValueError:
            continue
        if abs(cx) > 2 or abs(cy) > 2:
            continue
        pls += wakfu.parse_gfx_chunk(area.read(name))
    return elements, pls


def frame0_rgba(gfx, e):
    """Return (content_w, content_h, rgba) for frame 0 of an element."""
    w, h, pw, ph, tex = wakfu.decode_tgam(gfx.read('gfx/%d.tgam' % e['cpE']))
    if e['afb'] is None:
        return w, h, wakfu.crop_rgba(tex, pw, 0, 0, w, h)
    a = e['afb']
    fw, fh = a['fw'], a['fh']
    fx, fy = a['coords'][0], a['coords'][1]
    return fw, fh, wakfu.crop_rgba(tex, pw, fx, fy, fw, fh)


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


def transform(rgba, w, h, mode):
    if mode == 'normal':
        return rgba
    out = bytearray(w * h * 4)
    for y in range(h):
        for x in range(w):
            if mode == 'hflip':
                sx, sy = w - 1 - x, y
            elif mode == 'vflip':
                sx, sy = x, h - 1 - y
            elif mode == 'rot180':
                sx, sy = w - 1 - x, h - 1 - y
            si = (sy * w + sx) * 4
            di = (y * w + x) * 4
            out[di:di + 4] = rgba[si:si + 4]
    return bytes(out)


def main():
    elements, pls = load_placements()
    gfx = zipfile.ZipFile(os.path.join(MAPS, 'gfx.jar'))

    # build draw list with screen boxes, restricted to islet bbox
    drawn = []
    for p in pls:
        e = elements.get(p['elem'])
        if e is None or 'gfx/%d.tgam' % e['cpE'] not in set():  # placeholder
            pass
        if e is None:
            continue
        if ('gfx/%d.tgam' % e['cpE']) not in gfx.namelist():
            continue
        ax = (p['col'] - p['row']) * TILE_HW
        ay = (p['col'] + p['row']) * TILE_QH - p['z'] * Z_STEP
        bx = ax - e['cpy']
        by = ay - e['cpz']
        w, h = e['cpC'], e['cpD']
        if bx + w < BX0 or bx > BX1 or by + h < BY0 or by > BY1:
            continue
        drawn.append((p, e, bx, by, w, h))
    drawn.sort(key=lambda t: (t[0]['row'], t[0]['col'], t[0]['ccq'], t[0]['seq']))
    print('islet tiles:', len(drawn))

    CW, CH = int(BX1 - BX0), int(BY1 - BY0)
    os.makedirs('/tmp/islet', exist_ok=True)

    # cache frame0 per element
    cache = {}
    for mode in ('normal', 'hflip', 'vflip', 'rot180'):
        # canvas RGBA, opaque dark-navy background like the viewer (#1b2330)
        canvas = bytearray()
        for _ in range(CW * CH):
            canvas += bytes((27, 35, 48, 255))
        for (p, e, bx, by, w, h) in drawn:
            key = e['cpx']
            if key not in cache:
                cw_, ch_, raw = frame0_rgba(gfx, e)
                cache[key] = (cw_, ch_, raw)
            cw_, ch_, raw = cache[key]
            disp = scale_nn(raw, cw_, ch_, w, h)
            disp = transform(disp, w, h, mode)
            # alpha-over composite at (bx-BX0, by-BY0)
            ox0 = int(round(bx - BX0)); oy0 = int(round(by - BY0))
            for ty in range(h):
                cy = oy0 + ty
                if cy < 0 or cy >= CH:
                    continue
                for tx in range(w):
                    cx = ox0 + tx
                    if cx < 0 or cx >= CW:
                        continue
                    si = (ty * w + tx) * 4
                    sa = disp[si + 3]
                    if sa == 0:
                        continue
                    di = (cy * CW + cx) * 4
                    ia = 255 - sa
                    canvas[di] = (disp[si] * sa + canvas[di] * ia) // 255
                    canvas[di + 1] = (disp[si + 1] * sa + canvas[di + 1] * ia) // 255
                    canvas[di + 2] = (disp[si + 2] * sa + canvas[di + 2] * ia) // 255
                    canvas[di + 3] = 255
        wakfu.write_png('/tmp/islet/%s.png' % mode, CW, CH, bytes(canvas))
        print('wrote', mode)


if __name__ == '__main__':
    main()
