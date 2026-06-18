# Crobeye

*A crow's-eye view of every Wakfu map.*

Crobeye is a fast, browser-based **viewer** for the maps in the MMO
[Wakfu](https://www.wakfu.com/). It reads the game's own map files, rebuilds each
area the way the game draws it, and lets you browse all ~768 maps in a catalog,
open any one, zoom and pan around it, favorite the ones you like, and export them
as full-resolution PNGs.

It's a **viewer only** — it never edits the game or your save. It's built for
studying the art.

---

## Run it (one command)

From this folder, in a terminal:

```bash
./run.sh
```

That starts a small local web server and opens Crobeye in your browser at
**http://localhost:8777**. Press `Ctrl+C` in the terminal to stop it.

If port 8777 is busy, pick another: `./run.sh 9000`.

> No installation needed beyond **Python 3**, which macOS already has. Nothing is
> uploaded anywhere — it all runs on your own machine.

If `./run.sh` ever says "permission denied", run `chmod +x run.sh` once, then try again.

---

## What you can do

**In the catalog (the landing page):**
- **Browse** every map as a preview thumbnail.
- **Filter** by terrain type (island, town, cavern, desert, forest…) — these are
  *inferred* from each map's colors and structure, not official game names.
- **Sort** by size (small / medium / large / huge, based on how many sprites the
  map has), by area id, or by type.
- **Search** by area id.
- **★ Favorite** maps (click the star); the "★ favorites" chip filters to just those.
- **Recently viewed** maps show up in a row at the top.
- **⤓ Download** any map as a full-resolution PNG straight from its card.

**In a map (click any card):**
- **Scroll** to zoom, **drag** to pan, `R` to reset the view.
- `F` to favorite, `S` to save the map as a PNG.
- `B` toggles a blend-tile overlay, `L` toggles baked lighting.

Favorites and recents are saved in your browser, so they persist between visits.

---

## Where the maps come from

Crobeye doesn't ship the map art (it's the game's, and it's gigabytes). Instead, a
set of Python tools in `tools/` reads your **local Wakfu install** and generates
the data the viewer needs. The expected install path is:

```
/Applications/ankama/wakfu/contents/maps
```

The generated data lives under `viewer/data/` and is **not** stored in git (it's
large and regenerable). If you clone this repo fresh, regenerate it like so:

```bash
cd tools

# 1. Extract sprite placements + the shared texture pool for every map.
python3 extract.py --all

# 2. Render a preview thumbnail for every map (for the catalog cards).
python3 thumbs.py --all

# 3. Build the catalog index (terrain types, sizes, etc.).
python3 catalog.py
```

To export every map as a full-resolution PNG, sorted into folders by terrain type:

```bash
python3 tools/export_maps.py            # -> exports/<type>/area-<id>.png
python3 tools/export_maps.py --cap 2048 # smaller files
```

All the tools use only the Python standard library — no extra packages to install.

---

## Project layout

```
crobeye/
├── run.sh              ← start the viewer (the one command above)
├── viewer/             ← the web app (served by run.sh)
│   ├── index.html      ← the catalog / landing page
│   ├── view.html       ← the single-map viewer
│   ├── main.js         ← viewer rendering (PixiJS / WebGL)
│   ├── index.json      ← catalog metadata (small, tracked in git)
│   └── data/           ← generated map data (NOT in git — regenerate)
├── tools/              ← Python tools that read the game and build the data
│   ├── extract.py      ← decode maps -> sprite placements + textures
│   ├── thumbs.py       ← render catalog preview thumbnails
│   ├── catalog.py      ← classify maps + build index.json
│   ├── export_maps.py  ← batch full-res PNG export by terrain folder
│   └── wakfu.py        ← the binary format decoders (shared)
└── exports/            ← full-res PNGs (NOT in git — regenerate)
```

---

## Notes

- **Viewer only.** Crobeye renders the maps; it never modifies the game.
- **"Looks right," not pixel-exact.** A few tiles (some bridges and terrain edges)
  can sit at the wrong orientation — that comes from how the orientation is baked
  into the game data, and matching it exactly is a much larger project.
- Requires a local Wakfu install to (re)generate map data.
