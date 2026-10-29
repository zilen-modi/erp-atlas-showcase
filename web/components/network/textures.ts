// Procedural textures (drawn on canvases, no image files): terrain, asphalt, corrugated walls,
// ribbed roofs, roller shutters, parking bays and the company sign on each warehouse.
import * as THREE from "three";

function canvas(w: number, h: number, draw: (c: CanvasRenderingContext2D) => void, repeat = true) {
  const el = document.createElement("canvas");
  el.width = w; el.height = h;
  const c = el.getContext("2d")!;
  draw(c);
  const t = new THREE.CanvasTexture(el);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  if (repeat) { t.wrapS = THREE.RepeatWrapping; t.wrapT = THREE.RepeatWrapping; }
  return t;
}
function noise(c: CanvasRenderingContext2D, w: number, h: number, n: number, colors: string[], size: [number, number]) {
  for (let i = 0; i < n; i++) {
    c.fillStyle = colors[i % colors.length];
    const s = size[0] + Math.random() * (size[1] - size[0]);
    c.globalAlpha = 0.25 + Math.random() * 0.4;
    c.beginPath();
    c.arc(Math.random() * w, Math.random() * h, s, 0, Math.PI * 2);
    c.fill();
  }
  c.globalAlpha = 1;
}

let cache: Record<string, THREE.Texture> = {};
const once = (k: string, f: () => THREE.Texture) => (cache[k] ??= f());
export function resetTextures() { Object.values(cache).forEach((t) => t.dispose()); cache = {}; }

export const grass = () => once("grass", () => canvas(512, 512, (c) => {
  c.fillStyle = "#9fbf7f"; c.fillRect(0, 0, 512, 512);
  noise(c, 512, 512, 2600, ["#8fb26f", "#b0cc8e", "#86a866", "#a8c486", "#c2d6a0"], [2, 9]);
  noise(c, 512, 512, 140, ["#7d9f5e", "#c9d9a8"], [14, 30]);
}));
export const farmland = () => once("farmland", () => canvas(512, 512, (c) => {
  c.fillStyle = "#c9cfb5"; c.fillRect(0, 0, 512, 512);
  noise(c, 512, 512, 1600, ["#bfc6a7", "#d4d8c1", "#b6be9c"], [2, 8]);
}));

/** Asphalt lane: edge lines and a dashed centre line, repeating along v. */
export const asphalt = () => once("asphalt", () => canvas(128, 512, (c) => {
  c.fillStyle = "#4b5260"; c.fillRect(0, 0, 128, 512);
  noise(c, 128, 512, 900, ["#545b6a", "#434957", "#5c6372"], [0.5, 1.6]);
  c.fillStyle = "#f8fafc"; c.fillRect(8, 0, 5, 512); c.fillRect(115, 0, 5, 512);
  c.fillStyle = "#facc15";
  for (let y = 0; y < 512; y += 96) c.fillRect(61, y, 6, 56);
}));

export const lot = () => once("lot", () => canvas(512, 256, (c) => {
  c.fillStyle = "#5b6271"; c.fillRect(0, 0, 512, 256);
  noise(c, 512, 256, 1200, ["#636a79", "#535a68"], [0.5, 1.8]);
  c.strokeStyle = "#f1f5f9"; c.lineWidth = 3;
  for (let x = 20; x < 500; x += 44) { c.beginPath(); c.moveTo(x, 18); c.lineTo(x, 100); c.stroke(); c.beginPath(); c.moveTo(x, 156); c.lineTo(x, 238); c.stroke(); }
  c.beginPath(); c.moveTo(20, 128); c.lineTo(500, 128); c.stroke();
}, false));

export const concrete = () => once("concrete", () => canvas(256, 256, (c) => {
  c.fillStyle = "#d9dde3"; c.fillRect(0, 0, 256, 256);
  noise(c, 256, 256, 600, ["#cfd4db", "#e3e6eb"], [1, 3]);
  c.strokeStyle = "rgba(120,130,145,0.35)"; c.lineWidth = 1.5;
  for (let i = 0; i <= 256; i += 64) { c.beginPath(); c.moveTo(i, 0); c.lineTo(i, 256); c.stroke(); c.beginPath(); c.moveTo(0, i); c.lineTo(256, i); c.stroke(); }
}));

/** Corrugated cladding: vertical ribs with a coloured base band. */
export const cladding = (band: string) => once(`clad${band}`, () => canvas(256, 256, (c) => {
  const g = c.createLinearGradient(0, 0, 0, 256);
  g.addColorStop(0, "#f7f9fc"); g.addColorStop(1, "#e6eaf0");
  c.fillStyle = g; c.fillRect(0, 0, 256, 256);
  for (let x = 0; x < 256; x += 8) { c.fillStyle = "rgba(100,116,139,0.16)"; c.fillRect(x, 0, 2, 256); c.fillStyle = "rgba(255,255,255,0.7)"; c.fillRect(x + 2, 0, 1, 256); }
  c.fillStyle = band; c.fillRect(0, 214, 256, 42);
  c.fillStyle = "rgba(15,23,42,0.18)"; c.fillRect(0, 210, 256, 4);
  // clerestory windows
  c.fillStyle = "#334a66";
  for (let x = 10; x < 256; x += 64) c.fillRect(x, 40, 44, 14);
}));

export const roofRibs = (base: string) => once(`roof${base}`, () => canvas(256, 256, (c) => {
  c.fillStyle = base; c.fillRect(0, 0, 256, 256);
  for (let y = 0; y < 256; y += 10) { c.fillStyle = "rgba(255,255,255,0.18)"; c.fillRect(0, y, 256, 2); c.fillStyle = "rgba(0,0,0,0.12)"; c.fillRect(0, y + 2, 256, 2); }
}));

export const shutter = () => once("shutter", () => canvas(64, 128, (c) => {
  c.fillStyle = "#94a3b8"; c.fillRect(0, 0, 64, 128);
  for (let y = 0; y < 128; y += 6) { c.fillStyle = "rgba(15,23,42,0.25)"; c.fillRect(0, y, 64, 1); c.fillStyle = "rgba(255,255,255,0.35)"; c.fillRect(0, y + 1, 64, 1); }
}, false));

// The organisation's name for signs and trailers (config/policy.yaml `organisation.name`); generic when unset.
let BRAND = "";
export function setBrand(name: string) {
  if (name !== BRAND) { BRAND = name; for (const k of Object.keys(cache)) if (k.startsWith("livery")) { cache[k].dispose(); delete cache[k]; } }
}
const brandText = () => (BRAND || "DISTRIBUTION").toUpperCase();

/** The sign over the office door: the organisation's name and the branch's town. */
export function sign(town: string, role: "cd" | "hub" | "branch") {
  return canvas(512, 160, (c) => {
    c.fillStyle = role === "cd" ? "#5b21b6" : "#1d4ed8";
    c.beginPath(); c.roundRect(4, 4, 504, 152, 18); c.fill();
    c.fillStyle = "#ffffff";
    c.font = "800 64px Inter, Arial, sans-serif";
    c.textAlign = "center"; c.textBaseline = "middle";
    c.font = `800 ${brandText().length > 12 ? 44 : 64}px Inter, Arial, sans-serif`;
    c.fillText(brandText().slice(0, 18), 256, 62);
    c.font = "600 34px Inter, Arial, sans-serif";
    c.fillStyle = "#dbeafe";
    c.fillText(town.toUpperCase().slice(0, 22), 256, 120);
  }, false);
}

/** Trailer side: white box with the organisation's name and a blue (or red, when late) swoosh. */
export const livery = (late: boolean) => once(`livery${late}`, () => canvas(512, 192, (c) => {
  c.fillStyle = "#fbfcfe"; c.fillRect(0, 0, 512, 192);
  c.fillStyle = late ? "#dc2626" : "#1d4ed8";
  c.beginPath(); c.moveTo(0, 150); c.quadraticCurveTo(260, 90, 512, 120); c.lineTo(512, 192); c.lineTo(0, 192); c.fill();
  c.fillStyle = late ? "#991b1b" : "#1e3a8a";
  c.font = "800 62px Inter, Arial, sans-serif"; c.textBaseline = "middle";
  if (brandText().length > 12) c.font = "800 44px Inter, Arial, sans-serif";
  c.fillText(brandText().slice(0, 18), 34, 70);
  c.fillStyle = "#64748b"; c.font = "600 22px Inter, Arial, sans-serif";
  c.fillText("Distribution · Logistics", 38, 116);
}, false));

/** Office block: rows of windows on light panels, a few lit. */
export const facade = () => once("facade", () => {
  const t = canvas(128, 256, (c) => {
    c.fillStyle = "#ffffff"; c.fillRect(0, 0, 128, 256);
    for (let y = 10; y < 250; y += 24) for (let x = 8; x < 124; x += 20) {
      c.fillStyle = Math.random() < 0.18 ? "#fde9a8" : Math.random() < 0.5 ? "#5d7491" : "#4a5f7a";
      c.fillRect(x, y, 13, 14);
    }
    c.fillStyle = "rgba(0,0,0,0.12)"; c.fillRect(0, 248, 128, 8);
  });
  t.repeat.set(1, 2);
  return t;
});

/** Fuel station totem: a lit panel with diesel and petrol prices. */
export const fuelSign = () => once("fuelSign", () => canvas(128, 256, (c) => {
  c.fillStyle = "#0f172a"; c.fillRect(0, 0, 128, 256);
  c.fillStyle = "#16a34a"; c.fillRect(0, 0, 128, 70);
  c.fillStyle = "#ffffff"; c.font = "800 38px Inter, Arial, sans-serif"; c.textAlign = "center"; c.textBaseline = "middle";
  c.fillText("FUEL", 64, 36);
  c.font = "700 20px Inter, Arial, sans-serif"; c.fillStyle = "#cbd5e1";
  c.fillText("DIESEL", 64, 100); c.fillText("PETROL", 64, 180);
  c.font = "800 32px 'Courier New', monospace"; c.fillStyle = "#fbbf24";
  c.fillText("3.89", 64, 136); c.fillText("3.29", 64, 216);
}, false));
