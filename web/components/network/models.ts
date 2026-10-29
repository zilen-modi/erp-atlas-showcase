// Procedural low-poly models for the network scene: warehouses, trucks, forklifts, pallets, trees, pins.
// Shared geometries and materials keep ~150 buildings and ~70 trucks cheap to draw.
import * as THREE from "three";
import { cladding, concrete, fuelSign, livery, lot, roofRibs, shutter, sign } from "./textures";

const box = new THREE.BoxGeometry(1, 1, 1);
const cyl = new THREE.CylinderGeometry(1, 1, 1, 10);
const sph = new THREE.SphereGeometry(1, 10, 8);
const cone = new THREE.ConeGeometry(1, 1, 10);

const M = (color: number, o: Partial<THREE.MeshStandardMaterialParameters> = {}) =>
  new THREE.MeshStandardMaterial({ color, roughness: 0.6, metalness: 0.05, ...o });
export const MAT = {
  wall: M(0xf3f6fb, { roughness: 0.8 }),
  wallSide: M(0xe2e8f0, { roughness: 0.85 }),
  slab: M(0xd7dde6, { roughness: 1 }),
  lot: M(0xe9edf3, { roughness: 1 }),
  door: M(0x334155),
  doorOpen: M(0x1e293b),
  frameBlue: M(0x2563eb),
  frameViolet: M(0x7c3aed),
  roofBlue: M(0x2f6bff, { roughness: 0.45, metalness: 0.15 }),
  roofViolet: M(0x7c3aed, { roughness: 0.45, metalness: 0.15 }),
  roofSlate: M(0xa8b3c4, { roughness: 0.55, metalness: 0.1 }),
  vent: M(0xcbd5e1, { metalness: 0.4 }),
  cardboard: M(0xd6a46b, { roughness: 0.9 }),
  cardboardDark: M(0xb98447, { roughness: 0.9 }),
  pallet: M(0xa0784f, { roughness: 1 }),
  wrapBlue: M(0x2563eb, { roughness: 0.4 }),
  tire: M(0x1f2937, { roughness: 0.9 }),
  rim: M(0x9ca3af, { metalness: 0.6 }),
  glass: M(0x1e3a5f, { roughness: 0.15, metalness: 0.5 }),
  trailer: M(0xfbfcfe, { roughness: 0.5 }),
  cabBlue: M(0x2f6bff, { roughness: 0.35, metalness: 0.2 }),
  cabRed: M(0xef4444, { roughness: 0.35, metalness: 0.2 }),
  cabGreen: M(0x10b981, { roughness: 0.35, metalness: 0.2 }),
  stripeBlue: M(0x1d4ed8),
  stripeRed: M(0xdc2626),
  forklift: M(0xf59e0b, { roughness: 0.45 }),
  mast: M(0x374151, { metalness: 0.5 }),
  skin: M(0xf1c27d),
  vest: M(0xf97316),
  trunk: M(0x8b5a2b, { roughness: 1 }),
  leaf: M(0x34d399, { roughness: 0.8 }),
  leafDark: M(0x10b981, { roughness: 0.8 }),
  paint: new THREE.MeshBasicMaterial({ color: 0xfacc15 }),
  paintWhite: new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide }),
  road: M(0xc9d1dc, { roughness: 1, side: THREE.DoubleSide }),
  pinRed: M(0xef4444, { roughness: 0.3, emissive: 0xef4444, emissiveIntensity: 0.15 }),
  pinBlue: M(0x2563eb, { roughness: 0.3 }),
};

function part(geo: THREE.BufferGeometry, mat: THREE.Material, sx: number, sy: number, sz: number, x: number, y: number, z: number,
  shadow = true): THREE.Mesh {
  const m = new THREE.Mesh(geo, mat);
  m.scale.set(sx, sy, sz);
  m.position.set(x, y, z);
  m.castShadow = shadow;
  m.receiveShadow = true;
  return m;
}

/** Sawtooth roof profile extruded along the building's depth. */
function sawRoof(w: number, d: number, teeth: number, rise: number) {
  const s = new THREE.Shape();
  const step = w / teeth;
  s.moveTo(-w / 2, 0);
  for (let i = 0; i < teeth; i++) {
    const x0 = -w / 2 + i * step;
    s.lineTo(x0 + step * 0.82, rise);
    s.lineTo(x0 + step, 0);
  }
  s.lineTo(-w / 2, 0);
  const g = new THREE.ExtrudeGeometry(s, { depth: d, bevelEnabled: false });
  g.translate(0, 0, -d / 2);
  return g;
}
const roofCache = new Map<string, THREE.BufferGeometry>();
function roofGeo(w: number, d: number, teeth: number, rise: number) {
  const k = `${w}|${d}|${teeth}|${rise}`;
  if (!roofCache.has(k)) roofCache.set(k, sawRoof(w, d, teeth, rise));
  return roofCache.get(k)!;
}

export type Role = "cd" | "hub" | "branch";

const plane = new THREE.PlaneGeometry(1, 1);
const CAR_COLORS = [0xffffff, 0x1f2937, 0x9ca3af, 0xb91c1c, 0x1d4ed8, 0xe5e7eb, 0x065f46, 0x78350f];
const carMats = CAR_COLORS.map((c) => M(c, { roughness: 0.3, metalness: 0.4 }));

function texMat(tex: THREE.Texture, rx: number, ry: number, o: Partial<THREE.MeshStandardMaterialParameters> = {}) {
  const t = tex.clone();
  t.needsUpdate = true;
  t.repeat.set(rx, ry);
  return M(0xffffff, { map: t, ...o });
}

export function car(color: number) {
  const g = new THREE.Group();
  const mat = carMats[color % carMats.length];
  g.add(part(box, mat, 0.9, 0.22, 0.42, 0, 0.2, 0));
  g.add(part(box, mat, 0.5, 0.18, 0.38, -0.05, 0.38, 0));
  g.add(part(box, MAT.glass, 0.51, 0.13, 0.39, -0.05, 0.39, 0, false));
  return g;
}

function lamp() {
  const g = new THREE.Group();
  g.add(part(cyl, MAT.mast, 0.035, 1.6, 0.035, 0, 0.8, 0));
  g.add(part(box, MAT.mast, 0.35, 0.05, 0.12, 0.15, 1.6, 0, false));
  g.add(part(box, new THREE.MeshBasicMaterial({ color: 0xfff7d6 }), 0.2, 0.02, 0.09, 0.22, 1.57, 0, false));
  return g;
}

/**
 * A distribution warehouse on its own lot: concrete yard, clad walls, ribbed sawtooth roof,
 * roller-shutter dock doors, an office with the company sign, and a car park.
 * Size grows with activity; CDs are large with violet trim, hubs blue, branches slate.
 */
export function warehouse(role: Role, activity: number, doorsOpen: number, town = "") {
  const g = new THREE.Group();
  const scale = role === "cd" ? 1.75 : role === "hub" ? 1.22 : 0.85 + Math.min(0.32, Math.log1p(activity) * 0.055);
  const w = 4.4 * scale, d = 2.9 * scale, h = (role === "cd" ? 1.5 : 1.05) * Math.sqrt(scale);
  const trim = role === "cd" ? "#6d28d9" : role === "hub" ? "#1d4ed8" : "#475569";
  const roofBase = role === "cd" ? "#7c3aed" : role === "hub" ? "#2f6bff" : "#b8c2d1";
  // yard and car park
  const yard = part(box, texMat(concrete(), (w + 4) / 3, (d + 5) / 3, { roughness: 0.95 }), w + 4, 0.08, d + 5, 0, 0.04, 0.6, false);
  g.add(yard);
  const parkW = Math.max(2.6, w * 0.55);
  const park = new THREE.Mesh(plane, M(0xffffff, { map: lot(), roughness: 0.95 }));
  park.rotation.x = -Math.PI / 2;
  park.scale.set(parkW, 2.2, 1);
  park.position.set(-w / 2 - parkW / 2 - 0.9, 0.085, -d / 2 + 1.1);
  park.receiveShadow = true;
  g.add(park);
  const rnd = (n: number) => Math.abs(Math.sin(n * 12.9898 + activity * 78.233)) % 1;
  const cars = 2 + Math.floor(rnd(1) * 5);
  for (let i = 0; i < cars; i++) {
    const c = car(Math.floor(rnd(i + 3) * 100));
    const col = i % 6, row = Math.floor(i / 6);
    c.position.set(park.position.x - parkW / 2 + 0.45 + col * (parkW / 6.2) * 1.0, 0.09, park.position.z - 0.55 + row * 1.1 + (i % 2) * 1.1);
    c.rotation.y = Math.PI / 2;
    g.add(c);
  }
  for (const x of [park.position.x - parkW / 2, park.position.x + parkW / 2]) { const l = lamp(); l.position.set(x, 0.08, park.position.z + 1.25); g.add(l); }
  // walls: clad sides, slightly darker gable ends
  const clad = texMat(cladding(trim), w / 2.2, 1, { roughness: 0.6 });
  const cladEnd = texMat(cladding(trim), d / 2.2, 1, { roughness: 0.65, color: 0xf1f3f7 });
  const walls = new THREE.Mesh(box, [cladEnd, cladEnd, MAT.wall, MAT.wall, clad, clad]);
  walls.scale.set(w, h, d);
  walls.position.set(0, 0.08 + h / 2, 0);
  walls.castShadow = true; walls.receiveShadow = true;
  g.add(walls);
  // roof
  const teeth = role === "branch" ? 2 : role === "hub" ? 3 : 5;
  const roofMat = texMat(roofRibs(roofBase), 0.25, 0.25, { roughness: 0.4, metalness: 0.35 });
  const roof = new THREE.Mesh(roofGeo(+(w + 0.15).toFixed(2), +(d + 0.15).toFixed(2), teeth, 0.42 * Math.sqrt(scale)), roofMat);
  roof.position.y = 0.08 + h;
  roof.castShadow = true; roof.receiveShadow = true;
  g.add(roof);
  for (let i = 0; i < teeth; i++) {
    g.add(part(box, MAT.vent, 0.25, 0.14, 0.25, -w / 2 + (i + 0.5) * (w / teeth) - 0.3, 0.08 + h + 0.12, -d / 4));
    g.add(part(cyl, MAT.vent, 0.08, 0.2, 0.08, -w / 2 + (i + 0.5) * (w / teeth) + 0.3, 0.08 + h + 0.14, d / 5));
  }
  // dock doors along the front (z+): shutters, bumpers, a dock light; open ones show stock inside
  const doors = role === "cd" ? 8 : role === "hub" ? 5 : 3;
  const docks: THREE.Vector3[] = [];
  const dockW = w * 0.78;
  const shutterMat = M(0xffffff, { map: shutter(), roughness: 0.5, metalness: 0.3 });
  for (let i = 0; i < doors; i++) {
    const x = -w / 2 + w * 0.2 + (i + 0.5) * (dockW / doors);
    const open = i < doorsOpen;
    const dw = Math.min(0.62, (dockW / doors) * 0.7), dh = Math.min(h * 0.7, 0.85);
    g.add(part(box, M(0x1e293b), dw + 0.1, dh + 0.08, 0.05, x, 0.08 + dh / 2 + 0.04, d / 2 + 0.01, false));
    const door = new THREE.Mesh(plane, open ? MAT.doorOpen : shutterMat);
    door.scale.set(dw, open ? dh : dh, 1);
    door.position.set(x, 0.08 + dh / 2 + 0.02, d / 2 + 0.04);
    g.add(door);
    if (open) {
      g.add(part(box, MAT.cardboard, dw * 0.45, dh * 0.42, 0.25, x - dw * 0.14, 0.08 + dh * 0.21, d / 2 - 0.1, false));
      g.add(part(box, MAT.cardboardDark, dw * 0.35, dh * 0.3, 0.25, x + dw * 0.2, 0.08 + dh * 0.15, d / 2 - 0.1, false));
    }
    g.add(part(box, MAT.tire, 0.06, 0.12, 0.08, x - dw / 2 - 0.02, 0.2, d / 2 + 0.06, false));
    g.add(part(box, MAT.tire, 0.06, 0.12, 0.08, x + dw / 2 + 0.02, 0.2, d / 2 + 0.06, false));
    g.add(part(box, new THREE.MeshBasicMaterial({ color: open ? 0x22c55e : 0xef4444 }), 0.05, 0.05, 0.03, x + dw / 2 + 0.06, 0.08 + dh + 0.1, d / 2 + 0.05, false));
    docks.push(new THREE.Vector3(x, 0, d / 2 + 1.6));
    g.add(part(box, MAT.paint, 0.03, 0.006, 1.7, x - dw / 2 - 0.12, 0.085, d / 2 + 1.0, false));
  }
  // office annex with glazing and the sign
  const offW = w * 0.2, offD = 0.9, offH = Math.min(h, 0.95);
  const office = part(box, MAT.wall, offW, offH, offD, -w / 2 + offW / 2, 0.08 + offH / 2, d / 2 + offD / 2 - 0.05);
  g.add(office);
  g.add(part(box, MAT.glass, offW * 0.85, offH * 0.45, 0.02, -w / 2 + offW / 2, 0.08 + offH * 0.55, d / 2 + offD - 0.04, false));
  const sg = new THREE.Mesh(plane, new THREE.MeshBasicMaterial({ map: sign(town, role), transparent: true }));
  const sw = Math.min(w * 0.42, 2.6);
  sg.scale.set(sw, sw * 0.31, 1);
  sg.position.set(-w / 2 + w * 0.32, 0.08 + h - sw * 0.2, d / 2 + 0.03);
  g.add(sg);
  return { group: g, docks, height: 0.08 + h + 0.42 * Math.sqrt(scale), width: w, depth: d };
}

/** A box truck: cab + trailer, oriented along +x. Colour by state (blue on time, red late). */
export function truck(late: boolean, highlight = false) {
  const g = new THREE.Group();
  const cab = late ? MAT.cabRed : highlight ? MAT.cabGreen : MAT.cabBlue;
  const stripe = late ? MAT.stripeRed : MAT.stripeBlue;
  g.add(part(box, MAT.mast, 2.3, 0.12, 0.62, 0.05, 0.3, 0));                 // chassis
  const side = M(0xffffff, { map: livery(late), roughness: 0.45 });
  const trailer = new THREE.Mesh(box, [MAT.trailer, MAT.trailer, MAT.trailer, MAT.trailer, side, side]);
  trailer.scale.set(1.55, 0.78, 0.7);
  trailer.position.set(-0.3, 0.76, 0);
  trailer.castShadow = true;
  g.add(trailer);                                                               // box trailer with livery
  g.add(part(box, stripe, 1.56, 0.04, 0.71, -0.3, 0.38, 0, false));            // skirt
  g.add(part(box, cab, 0.62, 0.62, 0.66, 0.84, 0.66, 0));                      // cab
  g.add(part(box, cab, 0.3, 0.3, 0.64, 1.18, 0.5, 0));                         // nose
  g.add(part(box, MAT.glass, 0.04, 0.26, 0.56, 1.155, 0.82, 0, false));        // windscreen
  for (const x of [-0.8, -0.45, 0.95]) for (const z of [-0.33, 0.33]) {
    const wh = part(cyl, MAT.tire, 0.17, 0.12, 0.17, x, 0.18, z);
    wh.rotation.x = Math.PI / 2;
    g.add(wh);
  }
  g.scale.setScalar(0.9);
  return g;
}

/**
 * A fleet fuel station for a yard: forecourt, canopy on four pillars with lights underneath, two pump islands,
 * a price totem, and a car filling up. Long side along z, about 2.4 x 3.4.
 */
export function fuelStation() {
  const g = new THREE.Group();
  const W = 2.2, D = 3.2, H = 1.25;
  g.add(part(box, M(0x52596a, { roughness: 0.9 }), W + 0.2, 0.06, D + 0.2, 0, 0.06, 0, false));            // forecourt
  for (const x of [-W / 2 + 0.15, W / 2 - 0.15]) for (const z of [-D / 2 + 0.25, D / 2 - 0.25]) {
    g.add(part(box, MAT.wall, 0.1, H, 0.1, x, H / 2 + 0.06, z));                                             // pillars
  }
  g.add(part(box, MAT.wall, W, 0.16, D, 0, H + 0.14, 0));                                                     // canopy
  g.add(part(box, M(0x16a34a, { roughness: 0.4 }), W + 0.04, 0.1, D + 0.04, 0, H + 0.12, 0));                // green fascia band
  g.add(part(box, new THREE.MeshBasicMaterial({ color: 0xfff7d6 }), W * 0.8, 0.01, D * 0.8, 0, H + 0.055, 0, false)); // lights
  for (const x of [-0.45, 0.45]) {
    g.add(part(box, M(0xcbd5e1, { roughness: 0.8 }), 0.28, 0.08, 1.5, x, 0.1, 0, false));                   // island kerb
    for (const z of [-0.4, 0.4]) {
      g.add(part(box, MAT.wall, 0.18, 0.5, 0.26, x, 0.39, z));                                                // pump body
      g.add(part(box, M(0x16a34a, { roughness: 0.4 }), 0.19, 0.1, 0.27, x, 0.6, z, false));                  // pump head
      g.add(part(box, MAT.glass, 0.19, 0.1, 0.12, x, 0.47, z, false));                                        // display
    }
  }
  const pole = part(cyl, MAT.mast, 0.05, 1.6, 0.05, W / 2 + 0.3, 0.86, D / 2 - 0.2);
  const panel = new THREE.Mesh(box, [MAT.mast, MAT.mast, MAT.mast, MAT.mast,
    new THREE.MeshBasicMaterial({ map: fuelSign() }), new THREE.MeshBasicMaterial({ map: fuelSign() })]);
  panel.scale.set(0.42, 0.84, 0.08);
  panel.position.set(W / 2 + 0.3, 1.6, D / 2 - 0.2);
  panel.castShadow = true;
  g.add(pole, panel);
  const c = car(4);
  c.scale.setScalar(1.3);
  c.rotation.y = Math.PI / 2;
  c.position.set(-0.85, 0.09, 0.1);
  g.add(c);
  return g;
}

export function forklift() {
  const g = new THREE.Group();
  g.add(part(box, MAT.forklift, 0.55, 0.32, 0.4, 0, 0.26, 0));
  g.add(part(box, MAT.mast, 0.06, 0.75, 0.32, 0.3, 0.48, 0));
  g.add(part(box, MAT.mast, 0.42, 0.03, 0.06, 0.52, 0.12, -0.1, false));
  g.add(part(box, MAT.mast, 0.42, 0.03, 0.06, 0.52, 0.12, 0.1, false));
  g.add(part(box, MAT.mast, 0.03, 0.4, 0.03, -0.15, 0.62, 0.15, false));
  g.add(part(box, MAT.mast, 0.03, 0.4, 0.03, -0.15, 0.62, -0.15, false));
  g.add(part(box, MAT.forklift, 0.36, 0.03, 0.36, -0.05, 0.83, 0, false));     // roof guard
  g.add(part(sph, MAT.skin, 0.09, 0.09, 0.09, -0.05, 0.58, 0));                // driver
  g.add(part(box, MAT.vest, 0.16, 0.16, 0.18, -0.05, 0.44, 0, false));
  for (const x of [-0.18, 0.18]) for (const z of [-0.2, 0.2]) {
    const wh = part(cyl, MAT.tire, 0.09, 0.06, 0.09, x, 0.09, z);
    wh.rotation.x = Math.PI / 2;
    g.add(wh);
  }
  // a load on the forks
  g.add(part(box, MAT.pallet, 0.38, 0.05, 0.36, 0.55, 0.16, 0));
  g.add(part(box, MAT.cardboard, 0.32, 0.26, 0.3, 0.55, 0.32, 0));
  return g;
}

/** A pallet with a stack of cartons (or a blue-wrapped load). */
export function pallet(layers: number, wrapped = false) {
  const g = new THREE.Group();
  g.add(part(box, MAT.pallet, 0.7, 0.08, 0.7, 0, 0.05, 0));
  for (let l = 0; l < layers; l++) for (const [x, z] of [[-0.17, -0.17], [0.17, -0.17], [-0.17, 0.17], [0.17, 0.17]]) {
    g.add(part(box, wrapped ? MAT.wrapBlue : (l + x + z) % 2 ? MAT.cardboard : MAT.cardboardDark, 0.32, 0.26, 0.32, x, 0.22 + l * 0.27, z));
  }
  return g;
}

export function tree(size = 1) {
  const g = new THREE.Group();
  g.add(part(cyl, MAT.trunk, 0.07 * size, 0.5 * size, 0.07 * size, 0, 0.25 * size, 0));
  g.add(part(sph, Math.random() > 0.5 ? MAT.leaf : MAT.leafDark, 0.38 * size, 0.48 * size, 0.38 * size, 0, 0.78 * size, 0));
  return g;
}

/** A map pin hovering over a branch (late inbound). */
export function pin(color: "red" | "blue") {
  const g = new THREE.Group();
  const mat = color === "red" ? MAT.pinRed : MAT.pinBlue;
  g.add(part(sph, mat, 0.32, 0.32, 0.32, 0, 0.9, 0));
  const c = part(cone, mat, 0.3, 0.6, 0.3, 0, 0.5, 0);
  c.rotation.x = Math.PI;
  g.add(c);
  g.add(part(sph, MAT.paintWhite, 0.12, 0.12, 0.12, 0, 0.93, 0.25, false));
  return g;
}

export const ROAD_MAT = MAT.road;
