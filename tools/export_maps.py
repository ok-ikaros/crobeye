#!/usr/bin/env python3
"""Render every Wakfu map area to a full-resolution PNG, sorted into folders by
the derived terrain type (island / forest / dungeon / ...), ready to drag into
Google Drive (or anywhere).

Reuses the thumbs.py compositor at a high resolution cap. Pure stdlib (no PIL).
Parallelised across CPU cores (multiprocessing) since each map takes ~10s.

Output layout:
  <out>/<type>/area-<id>.png        e.g. exports/island/area-150.png

Usage:
  python3 export_maps.py                 # all areas, 4096px cap -> ../exports
  python3 export_maps.py --cap 2048      # smaller files
  python3 export_maps.py --jobs 4        # limit parallel workers
  python3 export_maps.py --area 150      # just one area (testing)
  python3 export_maps.py --out /path     # choose output dir
"""
import sys, os, json, zipfile, argparse, time
import multiprocessing as mp
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wakfu
import thumbs

HERE = os.path.dirname(os.path.abspath(__file__))
_W = {}   # per-worker state (zipfiles can't be pickled, so open them per process)


def _init(maps):
    _W['maps'] = maps
    _W['elements'] = wakfu.parse_elements(zipfile.ZipFile(os.path.join(maps, 'data.jar')).read('elements.lib'))
    _W['gfx_tex'] = zipfile.ZipFile(os.path.join(maps, 'gfx.jar'))
    _W['tgam_names'] = set(n for n in _W['gfx_tex'].namelist()
                           if n.startswith('gfx/') and n.endswith('.tgam'))


def _render_one(job):
    a, out_png, cap = job
    try:
        res = thumbs.render_area(a, _W['maps'], _W['elements'], _W['gfx_tex'], _W['tgam_names'], target=cap)
    except Exception as ex:
        return (a, 'error', str(ex))
    if res is None:
        return (a, 'empty', None)
    buf, w, h = res
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    thumbs.write_rgb_png(out_png, w, h, buf)
    return (a, 'ok', (w, h))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cap', type=int, default=4096, help='max longest side in px')
    ap.add_argument('--area', type=int, default=0, help='render a single area (testing)')
    ap.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument('--maps', default='/Applications/ankama/wakfu/contents/maps')
    ap.add_argument('--index', default=os.path.join(HERE, '..', 'viewer', 'index.json'))
    ap.add_argument('--out', default=os.path.join(HERE, '..', 'exports'))
    ap.add_argument('--force', action='store_true', help='re-render existing PNGs')
    args = ap.parse_args()

    idx = json.load(open(args.index))
    type_of = {a['area']: a['type'] for a in idx['areas']}

    out_root = os.path.abspath(args.out)
    os.makedirs(out_root, exist_ok=True)
    areas = [args.area] if args.area else sorted(type_of)

    # build the job list (skip already-rendered unless --force)
    jobs = []
    skipped = 0
    for a in areas:
        out_png = os.path.join(out_root, type_of.get(a, 'mixed'), f'area-{a}.png')
        if os.path.exists(out_png) and not args.force:
            skipped += 1
            continue
        jobs.append((a, out_png, args.cap))

    print(f"{len(jobs)} maps to render ({skipped} already done), "
          f"{args.jobs} workers, cap {args.cap}px", flush=True)

    done = failed = empty = 0
    t0 = time.time()
    with mp.Pool(args.jobs, initializer=_init, initargs=(args.maps,)) as pool:
        for n, (a, status, info) in enumerate(pool.imap_unordered(_render_one, jobs), 1):
            if status == 'ok':
                done += 1
            elif status == 'empty':
                empty += 1
            else:
                failed += 1
                print(f"  area {a}: error {info}", flush=True)
            if n % 25 == 0 or n == len(jobs):
                el = time.time() - t0
                rate = n / el if el else 0
                eta = (len(jobs) - n) / rate if rate else 0
                print(f"  [{n}/{len(jobs)}] done={done} empty={empty} fail={failed} "
                      f"· {el:.0f}s elapsed · ETA {eta:.0f}s", flush=True)

    # per-folder counts
    summary = {}
    for a, t in type_of.items():
        if os.path.exists(os.path.join(out_root, t, f'area-{a}.png')):
            summary[t] = summary.get(t, 0) + 1
    with open(os.path.join(out_root, 'INDEX.txt'), 'w') as f:
        f.write(f"Wakfu map exports — {sum(summary.values())} PNGs, cap {args.cap}px\n\n")
        for t in sorted(summary, key=lambda k: -summary[k]):
            f.write(f"  {t:12s} {summary[t]:4d}\n")
    print(f"\nDONE: rendered={done} empty={empty} failed={failed} skipped={skipped} -> {out_root}")
    print("per-folder counts written to INDEX.txt")


if __name__ == '__main__':
    main()
