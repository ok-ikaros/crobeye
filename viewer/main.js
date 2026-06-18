import {
  Application, Container, Sprite, Texture, Assets, Rectangle,
} from 'pixi.js';

const AREA = new URLSearchParams(location.search).get('area') || '1000';
const DATA = `./data/${AREA}`;
const hud = document.getElementById('hud');

// ---- recently-viewed + favorites (shared localStorage with the catalog) -----
const FAV_KEY = 'wakfu.favs', RECENT_KEY = 'wakfu.recents';
const areaId = Number(AREA);
const loadArr = (k) => { try { return JSON.parse(localStorage.getItem(k) || '[]'); } catch { return []; } };
// record this area as most-recently viewed (front, deduped, capped)
(() => {
  const r = loadArr(RECENT_KEY).filter((x) => x !== areaId);
  r.unshift(areaId);
  localStorage.setItem(RECENT_KEY, JSON.stringify(r.slice(0, 16)));
})();
const favBtn = document.getElementById('fav');
function isFav() { return loadArr(FAV_KEY).includes(areaId); }
function paintFav() {
  const on = isFav();
  favBtn.classList.toggle('on', on);
  favBtn.textContent = on ? '★ favorited' : '☆ favorite';
}
function toggleFav() {
  const f = loadArr(FAV_KEY).filter((x) => x !== areaId);
  if (!isFav()) f.push(areaId);
  localStorage.setItem(FAV_KEY, JSON.stringify(f));
  paintFav();
}
if (favBtn) { paintFav(); favBtn.addEventListener('click', toggleFav); }

const app = new Application();
await app.init({
  resizeTo: window,
  background: '#1b2330',
  antialias: false,
  preference: 'webgl',
  resolution: window.devicePixelRatio || 1,
  autoDensity: true,
});
document.getElementById('app').appendChild(app.canvas);

// world = pannable/zoomable container holding all sprites
const world = new Container();
world.sortableChildren = false; // we add in painter order already
app.stage.addChild(world);

const sceneResp = await fetch(`${DATA}/scene.json`, { cache: 'no-store' });
if (!sceneResp.ok) {
  hud.textContent = `area ${AREA} isn't extracted yet.`;
  hud.style.pointerEvents = 'auto';
  hud.innerHTML = `area <b>${AREA}</b> isn't rendered yet — `
    + `<a href="./index.html" style="color:#9fd0ff">back to catalog</a>`;
  throw new Error(`scene.json ${sceneResp.status} for area ${AREA}`);
}
const scene = await sceneResp.json();

// ---- load every frame texture once -----------------------------------------
const texFiles = new Set();
for (const e of Object.values(scene.elements))
  for (const fr of e.frames) texFiles.add(fr.f);

hud.textContent = `loading ${texFiles.size} textures…`;
const texById = {};
await Promise.all([...texFiles].map(async (f) => {
  texById[f] = await Assets.load({ src: `./data/tex/${f}`, data: { scaleMode: 'linear' } });
}));

// linear filtering matches the game's bilinear sampling on this smooth (2x) art
// and hides the tile-edge seams that nearest-neighbour leaves at fractional scale
for (const t of Object.values(texById)) t.source.scaleMode = 'linear';

// ---- build sprites in painter order -----------------------------------------
// animated elements: collect their sprites so we can swap textures per tick
const animGroups = []; // { period, cum:[ms...], frames:[Texture], sprites:[Sprite] }
const animByElem = {};

for (const [eid, e] of Object.entries(scene.elements)) {
  if (e.frames.length > 1) {
    let acc = 0; const cum = [];
    for (const fr of e.frames) { acc += fr.d; cum.push(acc); }
    const g = { period: e.period || acc, cum,
                frames: e.frames.map((fr) => texById[fr.f]), sprites: [] };
    animByElem[eid] = g; animGroups.push(g);
  }
}

let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

// edge-blend tile-sets (cpK 0x90/0xa0/0xb0): directional art baked into the
// texture, orientation fixed by element selection, no flag lever. Their "don't
// connect" look is the game's own data (see memory). Collect them so the 'b'
// key can tint them — a way to confirm a reported "wrong tile" is one of these
// faithful-by-design sets instead of re-investigating it each time.
const blendSprites = [];
const isBlend = (k) => k === 0x90 || k === 0xa0 || k === 0xb0;

// baked-light tints: placement[7] is a render-ready PixiJS tint (0xffffff = unlit).
// Collect lit sprites so the 'L' key can toggle the baked lighting on/off.
const litSprites = []; // { s, tint }
let lightOn = !!scene.lit;

for (const p of scene.placements) {
  const [eid, ax, ay, fx] = p;
  const tint = p.length > 7 ? p[7] : 0xffffff;
  const e = scene.elements[eid];
  const tex0 = texById[e.frames[0].f];
  const s = new Sprite(tex0);
  const bx = ax - e.ox;       // display-box left edge
  s.x = bx;
  s.y = ay - e.oy;
  s.width = e.w;
  s.height = e.h;
  // animated foam crests (shore blend classes) read as bright water sparkle -> additive
  if (e.frames.length > 1 && (e.cpK === 0xa0 || e.cpK === 0xb0)) s.blendMode = 'add';
  if (isBlend(e.cpK)) blendSprites.push(s);
  if (tint !== 0xffffff) {
    litSprites.push({ s, tint });
    if (lightOn) s.tint = tint;
  }
  world.addChild(s);
  const g = animByElem[eid];
  if (g) g.sprites.push(s);

  if (bx < minX) minX = bx;
  if (s.y < minY) minY = s.y;
  if (bx + e.w > maxX) maxX = bx + e.w;
  if (s.y + e.h > maxY) maxY = s.y + e.h;
}

// ---- animation --------------------------------------------------------------
let elapsed = 0;
app.ticker.add((t) => {
  elapsed += t.deltaMS;
  for (const g of animGroups) {
    const tt = elapsed % g.period;
    let fi = 0;
    while (fi < g.cum.length - 1 && tt >= g.cum[fi]) fi++;
    const tex = g.frames[fi];
    for (const s of g.sprites) if (s.texture !== tex) s.texture = tex;
  }
});

// ---- camera: pan + zoom -----------------------------------------------------
function resetView() {
  const cw = maxX - minX, ch = maxY - minY;
  const scale = Math.min(app.screen.width / cw, app.screen.height / ch) * 0.9;
  world.scale.set(scale);
  world.x = app.screen.width / 2 - (minX + cw / 2) * scale;
  world.y = app.screen.height / 2 - (minY + ch / 2) * scale;
}
resetView();

const canvas = app.canvas;
canvas.addEventListener('wheel', (ev) => {
  ev.preventDefault();
  const factor = Math.exp(-ev.deltaY * 0.0015);
  const mx = ev.offsetX, my = ev.offsetY;
  const wx = (mx - world.x) / world.scale.x;
  const wy = (my - world.y) / world.scale.y;
  const ns = Math.max(0.05, Math.min(8, world.scale.x * factor));
  world.scale.set(ns);
  world.x = mx - wx * ns;
  world.y = my - wy * ns;
}, { passive: false });

let dragging = false, lastX = 0, lastY = 0;
canvas.addEventListener('pointerdown', (ev) => { dragging = true; lastX = ev.clientX; lastY = ev.clientY; });
window.addEventListener('pointerup', () => { dragging = false; });
window.addEventListener('pointermove', (ev) => {
  if (!dragging) return;
  world.x += ev.clientX - lastX;
  world.y += ev.clientY - lastY;
  lastX = ev.clientX; lastY = ev.clientY;
});
window.addEventListener('keydown', (ev) => { if (ev.key === 'r' || ev.key === 'R') resetView(); });

// 'b' = toggle edge-blend tile-set overlay (tint them magenta). If a tile that
// "looks mis-oriented" lights up here, it's a baked edge-blend set = faithful,
// not a bug. See tools/find_blend_tilesets.py for the offline list + coords.
let blendOn = false;
window.addEventListener('keydown', (ev) => {
  if (ev.key !== 'b' && ev.key !== 'B') return;
  blendOn = !blendOn;
  for (const s of blendSprites) s.tint = blendOn ? 0xff3df0 : 0xffffff;
  hud.textContent = blendOn
    ? `edge-blend overlay ON — ${blendSprites.length} tiles tinted (baked orientation, faithful)`
    : `area ${scene.area} · ${scene.chunks} chunks · ${scene.placements.length} sprites · `
      + `${Object.keys(scene.elements).length} elements · ${animGroups.length} animated`;
});

// 'l' = toggle baked lighting (the per-cell multiply tints decoded from the
// light/<area>.jar chunks). Subtle in most dungeons (near-neutral), but lets the
// user compare lit vs flat. See tools/decode_light.py for the decode + alignment.
window.addEventListener('keydown', (ev) => {
  if (ev.key !== 'l' && ev.key !== 'L') return;
  if (!litSprites.length) return;
  lightOn = !lightOn;
  for (const { s, tint } of litSprites) s.tint = lightOn ? tint : 0xffffff;
  hud.textContent = lightOn
    ? `baked lighting ON — ${litSprites.length} tiles tinted`
    : `baked lighting OFF (${litSprites.length} lit tiles available)`;
});

// ---- export the whole map as a PNG ------------------------------------------
// Renders the full world bounds (not just the current viewport) to an offscreen
// canvas at a resolution capped to a sane pixel budget, then downloads it.
const EXPORT_MAX = 4096; // cap longest side so huge maps don't blow up memory
let exporting = false;
async function savePng() {
  if (exporting) return;
  exporting = true;
  const prev = hud.textContent;
  hud.textContent = 'rendering PNG…';
  // let the HUD repaint before the (synchronous) extract (setTimeout, not rAF:
  // rAF can stall in a backgrounded tab and hang the export)
  await new Promise((r) => setTimeout(r, 30));
  const sx = world.scale.x, sy = world.scale.y, px = world.x, py = world.y;
  try {
    const cw = maxX - minX, ch = maxY - minY;
    const scale = Math.min(1, EXPORT_MAX / Math.max(cw, ch));
    // place the map's top-left at the container origin so extract captures it all
    world.scale.set(scale);
    world.x = -minX * scale;
    world.y = -minY * scale;
    const canvas = app.renderer.extract.canvas({
      target: world,
      frame: new Rectangle(0, 0, Math.ceil(cw * scale), Math.ceil(ch * scale)),
      resolution: 1,
      clearColor: '#1b2330',
    });
    await new Promise((resolve) => {
      const done = (blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = `crobeye-area-${AREA}.png`;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        resolve();
      };
      if (canvas.toBlob) canvas.toBlob(done, 'image/png');
      else fetch(canvas.toDataURL('image/png')).then((r) => r.blob()).then(done);
    });
    hud.textContent = `saved crobeye-area-${AREA}.png (${Math.ceil(cw * scale)}×${Math.ceil(ch * scale)})`;
  } catch (err) {
    hud.textContent = `PNG export failed: ${err.message}`;
  } finally {
    world.scale.set(sx, sy); world.x = px; world.y = py;
    exporting = false;
    setTimeout(() => { if (!exporting) hud.textContent = prev; }, 2500);
  }
}
const saveBtn = document.getElementById('save');
if (saveBtn) saveBtn.addEventListener('click', savePng);

// auto-export mode: opened in a background tab by the catalog's per-card ⤓ button.
// Render the full map, download it, then close the tab (it was script-opened).
if (new URLSearchParams(location.search).get('dl')) {
  savePng().then(() => setTimeout(() => { try { window.close(); } catch (_) {} }, 1500));
}

window.addEventListener('keydown', (ev) => {
  if (ev.key === 's' || ev.key === 'S') savePng();
  else if (ev.key === 'f' || ev.key === 'F') toggleFav();
});

// debug camera hook: jump to a world point at a chosen scale (dev navigation aid)
window.__cam = { app, world, minX, minY, maxX, maxY,
  go(wy, scale = 1.2, wx = (minX + maxX) / 2) {
    world.scale.set(scale);
    world.x = app.screen.width / 2 - wx * scale;
    world.y = app.screen.height / 2 - wy * scale;
  } };

hud.textContent =
  `area ${scene.area} · ${scene.chunks} chunks · ${scene.placements.length} sprites · ` +
  `${Object.keys(scene.elements).length} elements · ${animGroups.length} animated`;
