"""Wakfu map data decoder (little-endian throughout).

Recovered from the obfuscated wakfu-client.jar. See memory/wakfu-map-format.md.
Pure stdlib (no PIL/numpy) so it runs anywhere.
"""
import struct, zlib, os, zipfile

# ---------------------------------------------------------------- elements.lib

def parse_elements(elements_lib_bytes):
    """Return dict: elementId -> element def.

    Each element:
      cpE  : tgam texture id  (gfx/<cpE>.tgam)
      cpC,cpD : on-screen display width,height
      cpA,cpB : content width,height inside the (pow2) tgam
      cpy,cpz : screen origin offset (display units)
      afb  : None (static) or dict(n, period, fw, fh, durs[n], coords[2n])
    """
    eb = elements_lib_bytes
    p = 0
    def rd(fmt):
        nonlocal p
        sz = struct.calcsize('<' + fmt)
        v = struct.unpack_from('<' + fmt, eb, p)
        p += sz
        return v
    (count,) = rd('i')
    out = {}
    for _ in range(count):
        (cpx,) = rd('i')
        cpy, cpz, cpC, cpD, cpA, cpB = rd('6h')
        (cpE,) = rd('i')
        cpK, cpF, cpG, cpH, cpI = rd('5b')   # cpK = blend class (shore/foam/etc.)
        cnt = eb[p]; p += 1
        afb = None
        if cnt:
            (period,) = rd('i')
            fw, fh, aw, ah = rd('4h')   # frameW, frameH, atlasW, atlasH
            durs = list(rd('%dh' % cnt))
            coords = list(rd('%dh' % (cnt * 2)))
            afb = dict(n=cnt, period=period, fw=fw, fh=fh, durs=durs, coords=coords)
        p += 1                         # cpL
        out[cpx] = dict(cpx=cpx, cpy=cpy, cpz=cpz, cpC=cpC, cpD=cpD,
                        cpA=cpA, cpB=cpB, cpE=cpE, cpK=cpK & 0xff, afb=afb)
    return out

# ---------------------------------------------------------------- gfx chunk

class _LE:
    __slots__ = ('d', 'p')
    def __init__(self, d): self.d = d; self.p = 0
    def i(self):  v = struct.unpack_from('<i', self.d, self.p)[0]; self.p += 4; return v
    def h(self):  v = struct.unpack_from('<h', self.d, self.p)[0]; self.p += 2; return v
    def H(self):  return self.h() & 0xFFFF
    def b(self):  v = self.d[self.p]; self.p += 1; return v
    def sb(self): v = struct.unpack_from('<b', self.d, self.p)[0]; self.p += 1; return v

def _color_size(b):
    s = (3 if b & 1 else 0) + (1 if b & 2 else 0)
    return s * 2 if b & 4 else s

def parse_gfx_chunk(data):
    """Return list of placements for one gfx chunk entry (X_Y).

    Placement: dict(col, row, elem, z, ccq, depth, seq, fx, fy, tr, grad)
      col,row : cell coordinates (global)
      z       : altitude (ccK - aYI), for screen Y only -- NOT a sort key
      ccq     : intra-cell paint order (engine sorts row, col, ccq ascending)
      depth   : palette a8 / bYO (NOT used in painter sort; kept for ref)
      seq     : read order (stable tiebreak when ccq ties)
      fx,fy   : texture flip X / flip Y (asT bit0 / bit1)
      tr      : bWy flag (diagonal/transpose orientation)
      grad    : gradient element flag (asT bit2)

    Engine painter order (aba.j -> Comparator.comparingLong(e->ccS), where
    ccS = agg.a(col,row,ccq,0)): sort by row, then col, then ccq. Altitude
    and the depth palette are NOT in the draw sort.

    The per-sprite orientation byte is read MSB-first as 4 packed bits
    (engine reader bGK): bit7=bWy, bit6=asT&1 (fx), bit5=asT&2 (fy),
    bit4=asT&4 (gradient).
    """
    r = _LE(data)
    r.i(); r.i(); r.h(); r.i(); r.i(); r.h()        # header
    n5 = r.H()
    a8 = []
    for _ in range(n5):
        r.i(); r.sb(); a8.append(r.i())
    ncol = r.H()
    for _ in range(ncol):
        b = r.b()
        r.p += _color_size(b)
    baseX = r.i(); baseY = r.i()
    nblk = r.H()
    out = []
    seq = 0
    for _ in range(nblk):
        xs = baseX + r.b(); xe = baseX + r.b()
        ys = baseY + r.b(); ye = baseY + r.b()
        for col in range(xs, xe):
            for row in range(ys, ye):
                sc = r.b()
                for _ in range(sc):
                    ccK = r.h(); aYI = r.sb(); ccq = r.sb()
                    flags = r.b()
                    elem = r.i(); pal = r.H(); r.H()
                    out.append(dict(col=col, row=row, elem=elem,
                                    z=ccK - aYI, ccq=ccq,
                                    depth=a8[pal] if pal < len(a8) else 0,
                                    seq=seq,
                                    tr=(flags >> 7) & 1,
                                    fx=(flags >> 6) & 1,
                                    fy=(flags >> 5) & 1,
                                    grad=(flags >> 4) & 1))
                    seq += 1
    assert r.p == len(data), (r.p, len(data))
    return out

# ---------------------------------------------------------------- .tgam

def _npow2(n):
    p = 1
    while p < n: p <<= 1
    return p

def decode_tgam(data):
    """Return (content_w, content_h, pow2_w, pow2_h, rgba_bytes) for a .tgam."""
    assert data[:4] == b'mAGT', data[:4]
    w, h = struct.unpack_from('<HH', data, 4)
    dsz, esz = struct.unpack_from('<II', data, 8)
    pw, ph = _npow2(w), _npow2(h)
    tex = data[17:17 + dsz]
    if len(tex) != pw * ph * 4:
        raise ValueError('unexpected tgam payload %d != %d' % (len(tex), pw * ph * 4))
    return w, h, pw, ph, tex

def crop_rgba(tex, pw, x, y, w, h):
    """Crop a w*h RGBA block from a pow2 RGBA buffer at (x,y)."""
    out = bytearray(w * h * 4)
    for ry in range(h):
        src = ((y + ry) * pw + x) * 4
        out[ry * w * 4:(ry + 1) * w * 4] = tex[src:src + w * 4]
    return bytes(out)

# ---------------------------------------------------------------- PNG writer

def write_png(path, w, h, rgba):
    def chunk(typ, dat):
        c = typ + dat
        return struct.pack('>I', len(dat)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    raw = bytearray()
    stride = w * 4
    for y in range(h):
        raw.append(0)
        raw += rgba[y * stride:(y + 1) * stride]
    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(bytes(raw), 6))
    png += chunk(b'IEND', b'')
    with open(path, 'wb') as f:
        f.write(png)
