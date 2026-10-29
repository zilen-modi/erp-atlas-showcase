// Town dressing for the network scene: junctions (traffic lights, stop lines, zebra crossings),
// street lamps along the roads, and houses and small blocks around each branch's town.
// Everything is instanced, so a few thousand pieces still cost a handful of draw calls.
import * as THREE from "three";
import type { Light, Network, RNode } from "./roads";
import { facade } from "./textures";

export type RoadLine = { curve: THREE.Curve<THREE.Vector3>; len: number; width: number };

const right = (tan: THREE.Vector3) => new THREE.Vector3(-tan.z, 0, tan.x).normalize();

/** Free ground: circles already taken by lots, roads and buildings, in a coarse grid for quick lookups. */
export class Occupancy {
  private cells = new Map<string, [number, number, number][]>();
  private key = (i: number, k: number) => `${i}|${k}`;
  constructor(private size = 4) {}
  add(x: number, z: number, r: number) {
    const s = this.size;
    for (let i = Math.floor((x - r) / s); i <= Math.floor((x + r) / s); i++)
      for (let k = Math.floor((z - r) / s); k <= Math.floor((z + r) / s); k++) {
        const c = this.cells.get(this.key(i, k));
        if (c) c.push([x, z, r]); else this.cells.set(this.key(i, k), [[x, z, r]]);
      }
  }
  free(x: number, z: number, r: number) {
    const c = this.cells.get(this.key(Math.floor(x / this.size), Math.floor(z / this.size)));
    // circles are registered in every cell they touch, so one cell holds everything that can reach this point
    if (r > this.size / 2) return this.freeWide(x, z, r);
    return !c || c.every(([cx, cz, cr]) => Math.hypot(cx - x, cz - z) >= cr + r);
  }
  private freeWide(x: number, z: number, r: number) {
    const s = this.size;
    for (let i = Math.floor((x - r) / s); i <= Math.floor((x + r) / s); i++)
      for (let k = Math.floor((z - r) / s); k <= Math.floor((z + r) / s); k++)
        for (const [cx, cz, cr] of this.cells.get(this.key(i, k)) ?? []) if (Math.hypot(cx - x, cz - z) < cr + r) return false;
    return true;
  }
  addRoad(r: RoadLine, pad: number) {
    for (const p of r.curve.getSpacedPoints(Math.max(4, Math.ceil(r.len / 0.8)))) this.add(p.x, p.z, r.width / 2 + pad);
  }
}

const LAMP_ON: Record<Light, THREE.Color> = { r: new THREE.Color(0xff3b30), y: new THREE.Color(0xffc400), g: new THREE.Color(0x22e36b) };
const LAMP_OFF = [new THREE.Color(0x3a1414), new THREE.Color(0x3a3210), new THREE.Color(0x10331d)];
const ORDER: Light[] = ["r", "y", "g"];

const flat = { depthWrite: false, polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -4 };

/** Junction boxes, and at signalled junctions a light, stop line and zebra on every approach; `update` switches the lamps. */
export class Signals {
  group = new THREE.Group();
  private lamps: THREE.InstancedMesh;
  private heads: { node: RNode; leg: number; lamp0: number; last?: Light }[] = [];

  constructor(private net: Network, asphalt: THREE.Material, gravel: THREE.Material) {
    const juncs = net.nodes.filter((nd) => nd.kind === "junction");
    const disc = new THREE.CircleGeometry(1, 28).rotateX(-Math.PI / 2);
    const box = new THREE.InstancedMesh(disc, asphalt, juncs.length);
    const verge = new THREE.InstancedMesh(disc, gravel, juncs.length);
    const o = new THREE.Object3D();
    juncs.forEach((nd, i) => {
      // paved just wide enough for the roads; where they meet at a narrow angle the traffic box (and stop
      // lines) sit further out, but a big disc would look like a car park
      const r = Math.min(nd.rad, Math.max(...nd.legs.map((e) => e.width)) / 2 + 0.35);
      o.position.set(nd.p.x, 0.06, nd.p.z); o.rotation.set(0, 0, 0);
      o.scale.setScalar(r); o.updateMatrix(); box.setMatrixAt(i, o.matrix);
      o.scale.setScalar(r + 0.25); o.updateMatrix(); verge.setMatrixAt(i, o.matrix);
    });
    box.renderOrder = 3; verge.renderOrder = 1;
    box.receiveShadow = verge.receiveShadow = true;

    const sig = juncs.filter((nd) => nd.sig);
    const n = sig.reduce((a, nd) => a + nd.legs.length, 0);
    const poleMat = new THREE.MeshStandardMaterial({ color: 0x3b4252, roughness: 0.6, metalness: 0.4 });
    const poles = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.035, 0.045, 1, 6), poleMat, Math.max(1, n));
    const heads = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshStandardMaterial({ color: 0x1f2430, roughness: 0.5 }), Math.max(1, n));
    this.lamps = new THREE.InstancedMesh(new THREE.SphereGeometry(1, 8, 6), new THREE.MeshBasicMaterial({ color: 0xffffff }), Math.max(1, n * 3));
    const paint = new THREE.MeshBasicMaterial({ color: 0xf8fafc, side: THREE.DoubleSide, ...flat });
    const bars = new THREE.InstancedMesh(new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2), paint, Math.max(1, n * 12));
    let np = 0, nh = 0, nl = 0, nb = 0;
    const bar = (p: THREE.Vector3, yaw: number, along: number, across: number) => {
      if (nb >= bars.count) return;
      o.position.set(p.x, 0.065, p.z); o.rotation.set(0, yaw, 0); o.scale.set(along, 1, across); o.updateMatrix();
      bars.setMatrixAt(nb++, o.matrix);
    };
    for (const nd of sig) nd.legs.forEach((e, leg) => {
      const de = net.into(e, nd), w = e.width;
      if (de.len < nd.rad + 2) return;
      const tan = de.dir, rt = de.right, yaw = Math.atan2(-tan.z, tan.x);
      const stop = nd.p.clone().addScaledVector(tan, -(nd.rad + 0.35));
      // stop line across our half, zebra across the whole road just before the box
      bar(stop.clone().addScaledVector(rt, w / 4), yaw, 0.12, w / 2 - 0.08);
      const stripes = Math.max(3, Math.floor(w / 0.26));
      for (let i = 0; i < stripes; i++) bar(stop.clone().addScaledVector(tan, -0.45).addScaledVector(rt, -w / 2 + (i + 0.5) * (w / stripes)), yaw, 0.5, 0.12);
      // the pole on the kerb, its head facing the traffic that has to stop
      const base = stop.clone().addScaledVector(rt, w / 2 + 0.3);
      o.position.set(base.x, 0.85, base.z); o.rotation.set(0, 0, 0); o.scale.set(1, 1.7, 1); o.updateMatrix();
      poles.setMatrixAt(np++, o.matrix);
      o.position.set(base.x, 1.72, base.z); o.rotation.set(0, yaw, 0); o.scale.set(0.16, 0.5, 0.2); o.updateMatrix();
      heads.setMatrixAt(nh++, o.matrix);
      const face = base.clone().addScaledVector(tan, -0.085);
      this.heads.push({ node: nd, leg, lamp0: nl });
      for (let k = 0; k < 3; k++) {
        o.position.set(face.x, 1.88 - k * 0.15, face.z); o.rotation.set(0, 0, 0); o.scale.setScalar(0.055); o.updateMatrix();
        this.lamps.setMatrixAt(nl, o.matrix);
        this.lamps.setColorAt(nl++, LAMP_OFF[k]);
      }
    });
    poles.count = np; heads.count = nh; this.lamps.count = nl; bars.count = nb;
    poles.castShadow = true; heads.castShadow = true;
    bars.renderOrder = 4;
    for (const m of [box, verge, poles, heads, this.lamps, bars]) { m.instanceMatrix.needsUpdate = true; this.group.add(m); }
    this.update();
  }

  update() {
    let dirty = false;
    for (const h of this.heads) {
      const s = this.net.light(h.node, h.leg);
      if (s === h.last) continue;
      h.last = s; dirty = true;
      ORDER.forEach((k, i) => this.lamps.setColorAt(h.lamp0 + i, k === s ? LAMP_ON[k] : LAMP_OFF[i]));
    }
    if (dirty && this.lamps.instanceColor) this.lamps.instanceColor.needsUpdate = true;
  }
}

/** Street lamps along both kerbs, staggered, kept off junctions and branch lots. */
export function streetLamps(roads: RoadLine[], clear: (x: number, z: number) => boolean) {
  const spots: { p: THREE.Vector3; yaw: number }[] = [];
  for (const r of roads) {
    let side = 1;
    for (let s = 4; s < r.len - 4; s += 9, side = -side) {
      const u = s / r.len, p = r.curve.getPointAt(u), tan = r.curve.getTangentAt(u), rt = right(tan).multiplyScalar(side);
      const base = p.addScaledVector(rt, r.width / 2 + 0.35);
      if (!clear(base.x, base.z)) continue;
      // the arm reaches back over the road
      spots.push({ p: base, yaw: Math.atan2(rt.z, -rt.x) });
    }
  }
  const g = new THREE.Group();
  const n = spots.length;
  const metal = new THREE.MeshStandardMaterial({ color: 0x6b7280, roughness: 0.5, metalness: 0.5 });
  const pole = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.025, 0.035, 1, 5), metal, n);
  const arm = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), metal, n);
  const bulb = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshBasicMaterial({ color: 0xfff4c2 }), n);
  const o = new THREE.Object3D(), fwd = new THREE.Vector3();
  spots.forEach(({ p, yaw }, i) => {
    o.rotation.set(0, 0, 0); o.position.set(p.x, 0.8, p.z); o.scale.set(1, 1.6, 1); o.updateMatrix(); pole.setMatrixAt(i, o.matrix);
    fwd.set(Math.cos(yaw), 0, -Math.sin(yaw));
    o.rotation.set(0, yaw, 0);
    o.position.set(p.x + fwd.x * 0.2, 1.6, p.z + fwd.z * 0.2); o.scale.set(0.42, 0.04, 0.06); o.updateMatrix(); arm.setMatrixAt(i, o.matrix);
    o.position.set(p.x + fwd.x * 0.38, 1.57, p.z + fwd.z * 0.38); o.scale.set(0.18, 0.04, 0.1); o.updateMatrix(); bulb.setMatrixAt(i, o.matrix);
  });
  pole.castShadow = true;
  for (const m of [pole, arm, bulb]) { m.instanceMatrix.needsUpdate = true; g.add(m); }
  return g;
}

export type TownSite = { x: number; z: number; r: number; role: "cd" | "hub" | "branch"; activity: number; seed: number };

const WALLS = [0xf5f0e6, 0xe9e4d8, 0xdfe6ee, 0xf2e3cf, 0xd9e2d0, 0xece7f2, 0xfaf7f0, 0xd6d3cc];
const ROOFS = [0x5b4a42, 0x7a3b2e, 0x4b5563, 0x6b4f3a, 0x374151, 0x8a4b3a];
const BLOCKS = [0xcbd5e1, 0xd6d3d1, 0xe2e8f0, 0xbfc8d6, 0xd9cfc1];

/** Houses with hipped roofs around every branch, and a few mid-rise blocks downtown near hubs and the CD. */
export function town(sites: TownSite[], occ: Occupancy, onLand: (x: number, z: number) => boolean, rand: (seed: number) => () => number) {
  const houses: THREE.Matrix4[] = [], roofs: THREE.Matrix4[] = [], wallCol: THREE.Color[] = [], roofCol: THREE.Color[] = [];
  const blocks: THREE.Matrix4[] = [], blockCol: THREE.Color[] = [];
  const o = new THREE.Object3D();
  for (const s of sites) {
    const rnd = rand(s.seed);
    const nHouse = 6 + Math.min(16, Math.round(s.activity / 4)) + (s.role === "cd" ? 10 : s.role === "hub" ? 5 : 0);
    const nBlock = s.role === "cd" ? 9 : s.role === "hub" ? 3 : 0;
    const grid = rnd() * Math.PI;   // each town's streets have their own heading
    const place = (count: number, near: number, far: number, size: number, make: (x: number, z: number, yaw: number) => void) => {
      for (let tries = 0, made = 0; made < count && tries < count * 10; tries++) {
        const ang = rnd() * Math.PI * 2, d = s.r + near + rnd() * far;
        const x = s.x + Math.cos(ang) * d, z = s.z + Math.sin(ang) * d;
        if (!onLand(x, z) || !occ.free(x, z, size)) continue;
        occ.add(x, z, size);
        make(x, z, grid + Math.floor(rnd() * 4) * (Math.PI / 2) + (rnd() - 0.5) * 0.15);
        made++;
      }
    };
    place(nBlock, 0.8, 4.5, 1.25, (x, z, yaw) => {
      const w = 1.3 + rnd() * 0.8, d = 1.1 + rnd() * 0.6, h = (s.role === "cd" ? 2.2 : 1.6) + rnd() * (s.role === "cd" ? 2.6 : 1.4);
      o.position.set(x, h / 2, z); o.rotation.set(0, yaw, 0); o.scale.set(w, h, d); o.updateMatrix();
      blocks.push(o.matrix.clone()); blockCol.push(new THREE.Color(BLOCKS[Math.floor(rnd() * BLOCKS.length)]));
    });
    place(nHouse, 1.2, 8, 0.75, (x, z, yaw) => {
      const w = 0.75 + rnd() * 0.35, d = 0.6 + rnd() * 0.25, h = 0.42 + rnd() * 0.18, rh = 0.28 + rnd() * 0.12;
      o.position.set(x, h / 2, z); o.rotation.set(0, yaw, 0); o.scale.set(w, h, d); o.updateMatrix();
      houses.push(o.matrix.clone()); wallCol.push(new THREE.Color(WALLS[Math.floor(rnd() * WALLS.length)]));
      o.position.set(x, h + rh / 2, z); o.scale.set(w * 0.78, rh, d * 0.78); o.updateMatrix();
      roofs.push(o.matrix.clone()); roofCol.push(new THREE.Color(ROOFS[Math.floor(rnd() * ROOFS.length)]));
    });
  }
  const g = new THREE.Group();
  const inst = (geo: THREE.BufferGeometry, mat: THREE.Material, ms: THREE.Matrix4[], cs: THREE.Color[]) => {
    const m = new THREE.InstancedMesh(geo, mat, Math.max(1, ms.length));
    ms.forEach((x, i) => { m.setMatrixAt(i, x); m.setColorAt(i, cs[i]); });
    m.count = ms.length;
    m.castShadow = true; m.receiveShadow = true;
    m.instanceMatrix.needsUpdate = true;
    g.add(m);
  };
  inst(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshStandardMaterial({ roughness: 0.85 }), houses, wallCol);
  // a square pyramid turned to sit square on the walls: a hipped roof
  inst(new THREE.ConeGeometry(Math.SQRT1_2 * 1.0, 1, 4).rotateY(Math.PI / 4).scale(Math.SQRT2, 1, Math.SQRT2), new THREE.MeshStandardMaterial({ roughness: 0.8, flatShading: true }), roofs, roofCol);
  const fac = facade();
  inst(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshStandardMaterial({ map: fac, roughness: 0.6, metalness: 0.1 }), blocks, blockCol);
  return g;
}
