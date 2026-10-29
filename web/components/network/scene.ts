// The branch network as a small 3D world: a warehouse per branch, roads per busy lane,
// a truck per transfer in transit, forklifts and pallets at busy docks, pins on late branches.
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { Sky } from "three/examples/jsm/objects/Sky.js";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import geo from "./geo.json";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { Occupancy, Signals, streetLamps, town, type RoadLine } from "./city";
import { car, forklift, fuelStation, MAT, pallet, pin, truck, warehouse, type Role } from "./models";
import { Network, type REdge } from "./roads";
import { asphalt, farmland, grass, setBrand } from "./textures";
import { Traffic, type Vehicle } from "./traffic";

export type Branch = {
  id: string; city: string; state: string; mother: string; cd: boolean; hub: boolean; children: number;
  out_open: number; in_open: number; out_transit: number; in_transit: number; overdue_in: number; overdue_out: number;
};
export type Lane = { from: string; to: string; open: number; transit: number; overdue: number; vias: string[] };
export type Transfer = { id: string; from: string; to: string; mode: string; ordered: string | null; required: string | null;
  shipped: string | null; via: string; overdue: boolean; age: number | null };
export type Pick = { kind: "branch"; id: string } | { kind: "transfer"; id: string } | { kind: "lane"; from: string; to: string } | null;

// Where each state's branches fall back to if their town isn't in the gazetteer.
const ANCHOR: Record<string, [number, number]> = {
  ME: [-69.9, 44.6], NH: [-71.5, 43.5], VT: [-72.9, 44.2], MA: [-71.3, 42.3], RI: [-71.45, 41.6],
  CT: [-72.8, 41.55], NY: [-75.7, 42.9], NJ: [-74.4, 40.3], PA: [-76.6, 40.6],
};
const LON0 = -72.4, LAT0 = 42.3, K = 46, COSLAT = Math.cos((42.3 * Math.PI) / 180);
const LAND = 0.5;            // land surface height above the sea

function project(lon: number, lat: number): [number, number] {
  return [(lon - LON0) * K * COSLAT, -(lat - LAT0) * K];
}
const towns = (geo as unknown as { towns: Record<string, [number, number]> }).towns;
const norm = (s: string) => s.toUpperCase().replace(/[^A-Z0-9 ]/g, "").replace(/\s+/g, " ").trim();
const radius = (b: Branch) => (b.cd ? 6.4 : b.hub ? 4.6 : 3.7);

/** Each branch at its real town; where lots would crowd (dense suburbs), nudge them apart, leaving room for a road. */
export function layout(branches: Branch[]): Map<string, [number, number]> {
  const pts = branches.map((b) => {
    const t = towns[`${b.state}|${norm(b.city)}`];
    const [lon, lat] = t ?? ANCHOR[b.state] ?? [-71.3, 42.3];
    const [x, z] = project(lon, lat);
    const j = t ? 0 : 1.5;                  // unknown town: near its state's centre
    return { b, x: x + (hash(b.id) % 100 / 50 - 1) * j, z: z + (hash(b.id + "z") % 100 / 50 - 1) * j, r: radius(b) };
  });
  for (let it = 0; it < 120; it++) {
    let moved = false;
    for (let i = 0; i < pts.length; i++) for (let k = i + 1; k < pts.length; k++) {
      const a = pts[i], c = pts[k];
      let dx = c.x - a.x, dz = c.z - a.z;
      let d = Math.hypot(dx, dz);
      // room for a road between neighbouring lots, its centre line clear of the bigger one
      const min = a.r + c.r + 2.6 + Math.abs(a.r - c.r);
      if (d >= min) continue;
      if (d < 1e-3) { dx = 0.5; dz = 0.3; d = 0.58; }
      const push = (min - d) / 2 + 0.01;
      const wa = a.b.cd ? 0.15 : c.b.cd ? 0.85 : 0.5;
      a.x -= (dx / d) * push * 2 * wa; a.z -= (dz / d) * push * 2 * wa;
      c.x += (dx / d) * push * 2 * (1 - wa); c.z += (dz / d) * push * 2 * (1 - wa);
      moved = true;
    }
    if (!moved) break;
  }
  return new Map(pts.map((p) => [p.b.id, [p.x, p.z] as [number, number]]));
}

function pointInRing(x: number, y: number, ring: [number, number][]) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function hash(s: string) { let h = 7; for (const c of s) h = (h * 31 + c.charCodeAt(0)) | 0; return Math.abs(h); }
function rand(seed: number) { return () => { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; }; }

type Site = { b: Branch; group: THREE.Group; top: number; docks: THREE.Vector3[]; base: THREE.Vector3 };
type Arc = { lane: Lane; mesh: THREE.Mesh };
type Street = { e: REdge; mesh: THREE.Mesh };
/** A truck (one transfer in transit) or a car (no transfer) on the road network. */
type Mover = Vehicle & { t: Transfer | null };

const TRUCK_SCALE = 1.15, CAR_SCALE = 1.3;
const TRUCK_HALF = 1.2, CAR_HALF = 0.6;    // half a vehicle's length at that scale
const TRUCK_SPEED = 1.8, CAR_SPEED = 2.4;  // cruising speed, world units per second
const CAR_EVERY = 30;                      // one car per this much road
type Worker = { obj: THREE.Group; a: THREE.Vector3; b: THREE.Vector3; phase: number; speed: number };

export class NetworkScene {
  renderer: THREE.WebGLRenderer;
  labels: CSS2DRenderer;
  scene = new THREE.Scene();
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  private raycaster = new THREE.Raycaster();
  private pointer = new THREE.Vector2(-9, -9);
  private world = new THREE.Group();
  private sites = new Map<string, Site>();
  private streets: Street[] = [];
  private arcs: Arc[] = [];
  private net: Network | null = null;
  private traffic: Traffic | null = null;
  private laneEdges = new Map<string, Set<REdge>>();
  private movers: Mover[] = [];
  private signals: Signals | null = null;
  private workers: Worker[] = [];
  private bobs: THREE.Object3D[] = [];
  private pointerMoved = true;
  private frame = 0;
  private labelObjs = new Map<string, CSS2DObject>();
  private alwaysLabel = new Set<string>();
  private selRing: THREE.Mesh;
  private hovered: string | null = null;
  private selected: Pick = null;
  private flyTo: THREE.Vector3 | null = null;
  private raf = 0;
  private clock = new THREE.Clock();
  private idle = 0;
  private fitted = false;
  private home0 = new THREE.Vector3();
  private sun!: THREE.DirectionalLight;
  private land: { code: string; active: boolean; rings: [number, number][][] }[] = [];
  private homeCam = new THREE.Vector3(0, 90, 90);
  onPick: (p: Pick) => void = () => {};
  onHover: (id: string | null) => void = () => {};

  constructor(private host: HTMLElement) {
    const w = host.clientWidth, h = host.clientHeight;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
    this.renderer.setSize(w, h);
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    host.appendChild(this.renderer.domElement);
    this.labels = new CSS2DRenderer();
    this.labels.setSize(w, h);
    Object.assign(this.labels.domElement.style, { position: "absolute", inset: "0", pointerEvents: "none" });
    host.appendChild(this.labels.domElement);

    this.camera = new THREE.PerspectiveCamera(30, w / h, 0.5, 3000);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.maxPolarAngle = Math.PI * 0.42;
    this.controls.minPolarAngle = Math.PI * 0.12;
    this.controls.minDistance = 8;
    this.controls.maxDistance = 420;
    this.controls.screenSpacePanning = false;
    this.controls.addEventListener("start", () => { this.idle = 0; this.flyTo = null; });

    this.scene.add(new THREE.HemisphereLight(0xeaf2ff, 0x9fb38a, 0.9));
    const sun = new THREE.DirectionalLight(0xfff1dc, 2.4);
    sun.position.set(-160, 220, 140);
    sun.castShadow = true;
    sun.shadow.mapSize.set(4096, 4096);
    sun.shadow.bias = -0.0003;
    sun.shadow.normalBias = 0.02;
    Object.assign(sun.shadow.camera, { left: -260, right: 260, top: 260, bottom: -260, near: 1, far: 800 });
    this.scene.add(sun);
    this.sun = sun;

    // sky dome with the sun in it, and image-based light for metal and glass
    const sky = new Sky();
    sky.scale.setScalar(6000);
    const u = sky.material.uniforms;
    u.turbidity.value = 4; u.rayleigh.value = 1.2; u.mieCoefficient.value = 0.004; u.mieDirectionalG.value = 0.85;
    u.sunPosition.value.copy(new THREE.Vector3().setFromSphericalCoords(1, THREE.MathUtils.degToRad(58), THREE.MathUtils.degToRad(210)));
    this.scene.add(sky);
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    this.scene.environmentIntensity = 0.35;

    // the sea, and the land of every state on the map
    const sea = new THREE.Mesh(new THREE.PlaneGeometry(6000, 6000), new THREE.MeshStandardMaterial({ color: 0x7fb3db, roughness: 0.2, metalness: 0.15 }));
    sea.rotation.x = -Math.PI / 2;
    sea.receiveShadow = true;
    this.scene.add(sea);
    this.buildLand();
    this.world.position.y = LAND;
    this.scene.add(this.world);

    this.selRing = new THREE.Mesh(new THREE.RingGeometry(5.6, 6.1, 64), new THREE.MeshBasicMaterial({ color: 0x2563eb, transparent: true, opacity: 0.85 }));
    this.selRing.rotation.x = -Math.PI / 2;
    this.selRing.visible = false;
    this.scene.add(this.selRing);

    this.renderer.domElement.addEventListener("pointermove", this.onMove);
    this.renderer.domElement.addEventListener("click", this.onClick);
    this.loop();
  }

  private onMove = (e: PointerEvent) => {
    const r = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    this.pointerMoved = true;
  };

  private hit(): THREE.Object3D | null {
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const targets: THREE.Object3D[] = [...[...this.sites.values()].map((s) => s.group), ...this.movers.filter((m) => m.t).map((m) => m.obj), ...this.streets.map((r) => r.mesh), ...this.arcs.map((r) => r.mesh)];
    const h = this.raycaster.intersectObjects(targets, true)[0]?.object ?? null;
    let o: THREE.Object3D | null = h;
    while (o && !o.userData.kind) o = o.parent;
    return o;
  }

  private onClick = () => {
    const o = this.hit();
    if (!o) { this.onPick(null); return; }
    const ud = o.userData as { kind: string; id?: string; from?: string; to?: string };
    if (ud.kind === "branch") this.onPick({ kind: "branch", id: ud.id! });
    else if (ud.kind === "transfer") this.onPick({ kind: "transfer", id: ud.id! });
    else if (ud.kind === "lane") this.onPick({ kind: "lane", from: ud.from!, to: ud.to! });
  };

  resize() {
    const w = this.host.clientWidth, h = this.host.clientHeight;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
    this.labels.setSize(w, h);
  }

  /** State outlines extruded as land (states with branches green, neighbours farmland), with border lines. */
  private buildLand() {
    const data = geo as unknown as { states: { code: string; active: boolean; rings: [number, number][][] }[]; borders: [number, number][][] };
    const grassMat = new THREE.MeshStandardMaterial({ map: grass(), roughness: 1 });
    grassMat.map!.repeat.set(1 / 14, 1 / 14);
    const farmMat = new THREE.MeshStandardMaterial({ map: farmland(), roughness: 1 });
    farmMat.map!.repeat.set(1 / 14, 1 / 14);
    const edge = new THREE.MeshStandardMaterial({ color: 0xd8cfb3, roughness: 1 });      // sandy coast
    for (const st of data.states) {
      const rings = st.rings.map((r) => r.map(([lon, lat]) => project(lon, lat)));
      this.land.push({ code: st.code, active: st.active, rings: rings.map((r) => r.map(([x, z]) => [x, -z] as [number, number])) });
      for (const r of rings) {
        const shape = new THREE.Shape(r.map(([x, z]) => new THREE.Vector2(x, -z)));
        const geom = new THREE.ExtrudeGeometry(shape, { depth: LAND, bevelEnabled: true, bevelThickness: 0.15, bevelSize: 0.4, bevelSegments: 1, curveSegments: 1 });
        const m = new THREE.Mesh(geom, [st.active ? grassMat : farmMat, edge]);
        m.rotation.x = -Math.PI / 2;
        m.position.y = -0.15;
        m.receiveShadow = true;
        this.scene.add(m);
      }
    }
    const borderMat = new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.75 });
    for (const line of data.borders) {
      const pts = line.map(([lon, lat]) => { const [x, z] = project(lon, lat); return new THREE.Vector3(x, LAND + 0.06, z); });
      this.scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), borderMat));
    }
  }

  private onLand(x: number, z: number) {
    for (const st of this.land) for (const r of st.rings) if (pointInRing(x, -z, r)) return true;
    return false;
  }

  private inActiveLand(x: number, z: number) {
    for (const st of this.land) if (st.active) for (const r of st.rings) if (pointInRing(x, -z, r)) return true;
    return false;
  }

  /** Woods across the land: instanced pines and broadleaf trees, kept off the branch lots and roads. */
  private buildForest(occ: Occupancy) {
    const N = 4200;
    const rnd = rand(4242);
    const box = new THREE.Box3();
    for (const st of this.land) if (st.active) for (const r of st.rings) for (const [x, nz] of r) box.expandByPoint(new THREE.Vector3(x, 0, -nz));
    const pineFol = new THREE.InstancedMesh(new THREE.ConeGeometry(0.42, 1.25, 7), new THREE.MeshStandardMaterial({ roughness: 0.85 }), N);
    const leafFol = new THREE.InstancedMesh(new THREE.IcosahedronGeometry(0.5, 0), new THREE.MeshStandardMaterial({ roughness: 0.9, flatShading: true }), N);
    const trunks = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.06, 0.08, 0.5, 5), MAT.trunk, N * 2);
    const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), sc = new THREE.Vector3(), p = new THREE.Vector3();
    const col = new THREE.Color();
    let np = 0, nl = 0, nt = 0;
    for (let tries = 0; tries < N * 8 && np + nl < N; tries++) {
      const x = box.min.x + rnd() * (box.max.x - box.min.x), z = box.min.z + rnd() * (box.max.z - box.min.z);
      if (!this.inActiveLand(x, z)) continue;
      if (!occ.free(x, z, 0.45)) continue;
      // clumps: woods are denser in the north
      const north = Math.min(1, Math.max(0, (-z + 20) / 160));
      if (rnd() > 0.35 + north * 0.6) continue;
      const s = 0.7 + rnd() * 0.9;
      const pine = rnd() < 0.35 + north * 0.5;
      q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), rnd() * Math.PI);
      if (pine && np < N) {
        m4.compose(p.set(x, 0.85 * s, z), q, sc.set(s, s, s)); pineFol.setMatrixAt(np, m4);
        pineFol.setColorAt(np, col.setHSL(0.36 + rnd() * 0.05, 0.42, 0.24 + rnd() * 0.1)); np++;
      } else if (nl < N) {
        m4.compose(p.set(x, 0.75 * s, z), q, sc.set(s, s * (0.85 + rnd() * 0.3), s)); leafFol.setMatrixAt(nl, m4);
        leafFol.setColorAt(nl, col.setHSL(0.24 + rnd() * 0.08, 0.45, 0.36 + rnd() * 0.12)); nl++;
      } else continue;
      m4.compose(p.set(x, 0.25 * s, z), q, sc.set(s, s, s)); trunks.setMatrixAt(nt++, m4);
    }
    pineFol.count = np; leafFol.count = nl; trunks.count = nt;
    for (const im of [pineFol, leafFol, trunks]) { im.castShadow = true; im.receiveShadow = true; im.instanceMatrix.needsUpdate = true; if (im.instanceColor) im.instanceColor.needsUpdate = true; this.world.add(im); }
  }

  build(branches: Branch[], lanes: Lane[], transit: Transfer[], opts: { maxLanes: number; showOpen: boolean; organisation?: string }) {
    setBrand(opts.organisation ?? "");
    this.world.clear();
    this.sites.clear(); this.streets = []; this.arcs = []; this.movers = []; this.net = null; this.traffic = null; this.signals = null; this.workers = []; this.bobs = [];
    for (const l of this.labelObjs.values()) l.element.remove();
    this.labelObjs.clear();
    const pos = layout(branches);
    const act = (b: Branch) => b.out_open + b.in_open + b.out_transit + b.in_transit;
    const topHubs = new Set(branches.filter((b) => b.hub).sort((a, b) => act(b) - act(a)).slice(0, 7).map((b) => b.id));
    // pins only where it matters most: the branches with the most late inbound transfers
    const latest = new Set([...branches].filter((b) => b.overdue_in > 0).sort((a, b) => b.overdue_in - a.overdue_in).slice(0, 15).map((b) => b.id));
    this.alwaysLabel = new Set([...topHubs, ...branches.filter((b) => b.cd).map((b) => b.id)]);

    // state names painted on the ground
    for (const [st, [lon, lat]] of Object.entries(ANCHOR)) {
      if (!branches.some((b) => b.state === st)) continue;
      const [x, z] = project(lon, lat);
      const el = document.createElement("div");
      el.className = "net-state";
      el.textContent = st;
      const o = new CSS2DObject(el);
      o.position.set(x, 0.1, z + 10);
      this.world.add(o);
    }

    const fuelAt: { group: THREE.Group; w: number; d: number; id: string }[] = [];
    for (const b of branches) {
      const p = pos.get(b.id);
      if (!p) continue;
      const role: Role = b.cd ? "cd" : b.hub ? "hub" : "branch";
      const doorsOpen = Math.min(role === "cd" ? 6 : role === "hub" ? 4 : 2, b.in_transit + b.out_transit + (b.out_open > 10 ? 1 : 0));
      const wh = warehouse(role, act(b), doorsOpen, b.city || `Branch ${b.id}`);
      const rnd = rand(hash(b.id) + 11);
      wh.group.position.set(p[0], 0, p[1]);
      wh.group.rotation.y = (Math.floor(rnd() * 4) - 1.5) * 0.08;
      wh.group.userData = { kind: "branch", id: b.id };
      // pallets waiting in the yard: outbound work
      const stacks = Math.min(5, Math.ceil(b.out_open / 8));
      for (let i = 0; i < stacks; i++) {
        const pl = pallet(1 + Math.floor(rnd() * 2), rnd() > 0.7);
        pl.position.set(-wh.width / 2 - 0.6 + (i % 3) * 0.85, 0.06, wh.depth / 2 + 2.2 + Math.floor(i / 3) * 0.85);
        wh.group.add(pl);
      }
      if (norm(b.city) === "LONDONDERRY") fuelAt.push({ group: wh.group, w: wh.width, d: wh.depth, id: b.id });
      // late inbound: a red pin over the roof
      if (latest.has(b.id)) {
        const pn = pin("red");
        pn.position.set(wh.width / 2 - 0.3, wh.height + 0.2, 0);
        pn.userData.y0 = pn.position.y;
        wh.group.add(pn);
        this.bobs.push(pn);
      }
      this.world.add(wh.group);
      const site: Site = { b, group: wh.group, top: wh.height, docks: wh.docks.map((d) => d.clone().applyEuler(wh.group.rotation).add(wh.group.position)), base: new THREE.Vector3(p[0], 0, p[1]) };
      this.sites.set(b.id, site);
      // forklifts working the docks of the CD and hubs
      const lifts = role === "cd" ? 3 : role === "hub" && act(b) > 20 ? 1 : 0;
      for (let i = 0; i < lifts; i++) {
        const f = forklift();
        const dock = site.docks[i % site.docks.length];
        const a = dock.clone().add(new THREE.Vector3(0, 0, -0.6));
        const bb = dock.clone().add(new THREE.Vector3((rnd() - 0.5) * 3, 0, 1.6 + rnd() * 1.2));
        this.world.add(f);
        this.workers.push({ obj: f, a, b: bb, phase: rnd(), speed: 0.12 + rnd() * 0.08 });
      }
      const el = document.createElement("div");
      el.className = `net-label ${b.cd ? "cd" : b.hub ? "hub" : ""}`;
      el.innerHTML = `<b>${b.city || "Branch"}</b><span>#${b.id}</span>`;
      const lab = new CSS2DObject(el);
      lab.position.set(p[0], wh.height + 1.6, p[1]);
      lab.visible = this.alwaysLabel.has(b.id);
      this.world.add(lab);
      this.labelObjs.set(b.id, lab);
    }

    // the road network between neighbouring branches; every lane's trucks drive along it
    const lots = [...this.sites.values()];
    const net = this.net = new Network(lots.map((st) => ({ id: st.b.id, x: st.base.x, z: st.base.z, r: radius(st.b) })), (x, z) => this.onLand(x, z));
    this.laneEdges.clear();
    for (const l of lanes) {
      const r = net.route(l.from, l.to);
      if (!r) continue;
      this.laneEdges.set(`${l.from}>${l.to}`, new Set(r.map((d) => d.e)));
      for (const d of r) d.e.use += l.open + l.transit;
    }
    net.settle();
    // a click on a road means the busiest lane that uses it
    const busiest = new Map<REdge, Lane>();
    for (const l of lanes) for (const e of this.laneEdges.get(`${l.from}>${l.to}`) ?? []) {
      const cur = busiest.get(e);
      if (!cur || cur.open + cur.transit < l.open + l.transit) busiest.set(e, l);
    }
    const verges: THREE.BufferGeometry[] = [];
    for (const e of net.edges) {
      const curve = new THREE.LineCurve3(e.a.p.clone().setY(0.06), e.b.p.clone().setY(0.06));
      const segs = Math.max(2, Math.round(e.len / 2));
      const mesh = new THREE.Mesh(ribbon(curve, e.width, segs), ROAD);
      mesh.receiveShadow = true;
      mesh.renderOrder = 2;
      const l = busiest.get(e);
      mesh.userData = l ? { kind: "lane", from: l.from, to: l.to } : {};
      this.world.add(mesh);
      this.streets.push({ e, mesh });
      verges.push(ribbon(curve, e.width + 0.5, segs));
    }
    // Londonderry fuels the fleet: a fuel station beside the building, on whichever side its driveway isn't
    for (const f of fuelAt) {
      const yard = net.yard.get(f.id), drive = yard?.legs[0];
      const gate = drive ? (drive.a === yard ? drive.b : drive.a) : null;
      const spots = [
        { at: new THREE.Vector3(f.w / 2 + 1.25, 0, -0.2), yaw: 0 },            // right-hand side
        { at: new THREE.Vector3(0.6, 0, -f.d / 2 - 1.3), yaw: Math.PI / 2 },  // behind
      ];
      const away = (sp: (typeof spots)[number]) => {
        if (!yard || !gate) return 0;
        const w = sp.at.clone().applyEuler(f.group.rotation).add(f.group.position);
        const a = yard.p, b = gate.p, ab = b.clone().sub(a), t = Math.max(0, Math.min(1, w.clone().sub(a).dot(ab) / ab.lengthSq()));
        return w.distanceTo(a.clone().addScaledVector(ab, t));
      };
      const best = spots.reduce((x, y) => (away(y) > away(x) ? y : x));
      const fs = fuelStation();
      fs.position.copy(best.at);
      fs.rotation.y = best.yaw;
      f.group.add(fs);
    }
    // gravel shoulders under the asphalt, as one mesh
    const verge = new THREE.Mesh(mergeGeometries(verges), SHOULDER);
    verge.receiveShadow = true;
    verge.renderOrder = 1;
    this.world.add(verge);
    this.signals = new Signals(net, JUNCTION, SHOULDER);
    this.world.add(this.signals.group);

    // faint arcs overhead for the open lanes with nothing on the road yet
    const arcLanes = opts.showOpen ? lanes.slice(0, opts.maxLanes).filter((l) => l.transit === 0) : [];
    const maxN = Math.max(1, ...lanes.slice(0, 50).map((l) => l.open + l.transit));
    for (const l of arcLanes) {
      const a = this.sites.get(l.from), b = this.sites.get(l.to);
      if (!a || !b) continue;
      const s = a.base.clone().setY(a.top + 0.3), e = b.base.clone().setY(b.top + 0.3);
      const mid = s.clone().add(e).multiplyScalar(0.5);
      mid.y = Math.max(s.y, e.y) + 3 + s.distanceTo(e) * 0.22;
      const curve = new THREE.QuadraticBezierCurve3(s, mid, e);
      const n = (l.open + l.transit) / maxN;
      const color = new THREE.Color(0x93c5fd).lerp(new THREE.Color(0xf59e0b), Math.min(1, (l.overdue / Math.max(1, l.open)) * 1.1));
      const arc = new THREE.Mesh(new THREE.TubeGeometry(curve, 40, 0.04 + 0.12 * Math.sqrt(n), 5, false),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.22 + 0.3 * Math.sqrt(n) }));
      arc.userData = { kind: "lane", from: l.from, to: l.to };
      this.world.add(arc);
      this.arcs.push({ lane: l, mesh: arc });
    }

    // the town around the roads: street lamps, houses, then woods on what's left
    const lines: RoadLine[] = net.edges.map((e) => ({ curve: new THREE.LineCurve3(e.a.p, e.b.p), len: e.len, width: e.width }));
    const offLots = (x: number, z: number, pad: number) => lots.every((st) => Math.hypot(st.base.x - x, st.base.z - z) > radius(st.b) + pad);
    const offJunctions = (x: number, z: number) => net.nodes.every((nd) => !nd.rad || Math.hypot(nd.p.x - x, nd.p.z - z) > nd.rad + 1.4);
    this.world.add(streetLamps(lines.filter((_, i) => net.edges[i].kind === "road"), (x, z) => offLots(x, z, 0.6) && offJunctions(x, z)));
    const occ = new Occupancy();
    for (const st of lots) occ.add(st.base.x, st.base.z, radius(st.b) + 0.6);
    for (const l of lines) occ.addRoad(l, 0.55);
    for (const nd of net.nodes) if (nd.rad) occ.add(nd.p.x, nd.p.z, nd.rad + 0.6);
    this.world.add(town(lots.map((st) => ({ x: st.base.x, z: st.base.z, r: radius(st.b), role: st.b.cd ? "cd" : st.b.hub ? "hub" : "branch",
      activity: act(st.b), seed: hash(st.b.id) + 77 })), occ, (x, z) => this.inActiveLand(x, z), rand));
    this.buildForest(occ);

    // traffic: a truck per transfer in transit, yard to yard, and cars between nearby branches
    const traffic = this.traffic = new Traffic(net);
    const rnd = rand(97);
    const put = (t: Transfer | null, route: NonNullable<ReturnType<Network["route"]>>) => {
      const obj = t ? truck(t.overdue) : car(Math.floor(rnd() * 8));
      obj.userData = t ? { kind: "transfer", id: t.id } : {};
      obj.visible = false;
      this.world.add(obj);
      const m: Mover = { t, obj, route, k: 0, s: 0, v: 0, vmax: (t ? TRUCK_SPEED : CAR_SPEED) * (0.9 + rnd() * 0.2), half: t ? TRUCK_HALF : CAR_HALF,
        scale: t ? TRUCK_SCALE : CAR_SCALE, waiting: true, snap: true, yaw: 0 };
      this.movers.push(m);
      traffic.add(m, rnd);
    };
    // late ones placed first, so they're the ones on the road if a yard is busy
    for (const t of [...transit].sort((a, b) => Number(b.overdue) - Number(a.overdue))) {
      const route = net.route(t.from, t.to);
      if (route) put(t, route);
    }
    const roadLen = net.edges.reduce((a, e) => a + (e.kind === "road" ? e.len : 0), 0);
    const nCars = Math.min(420, Math.round(roadLen / CAR_EVERY));
    for (let made = 0, tries = 0; made < nCars && tries < nCars * 4; tries++) {
      const a = lots[Math.floor(rnd() * lots.length)];
      const near = lots.filter((st) => st !== a && st.base.distanceTo(a.base) < 45);
      if (!near.length) continue;
      const b = near[Math.floor(rnd() * near.length)];
      const route = net.route(a.b.id, b.b.id);
      if (!route || route.length > 9) continue;
      put(null, route);
      made++;
    }
    this.applySelection();
    if (!this.fitted) { this.fit(); this.fitted = true; }
  }

  /** Frame every branch, leaving room for the side panels. */
  fit() {
    const pts = [...this.sites.values()].map((s) => s.base);
    if (!pts.length) return;
    const box = new THREE.Box3().setFromPoints(pts);
    const c = box.getCenter(new THREE.Vector3());
    const size = Math.max(box.max.x - box.min.x, (box.max.z - box.min.z) * 1.25);
    this.home0.set(c.x - size * 0.04, 0, c.z + size * 0.02);
    this.homeCam.set(this.home0.x - size * 0.08, size * 1.05, this.home0.z + size * 0.95);
    this.controls.target.copy(this.home0);
    this.camera.position.copy(this.homeCam);
    // fog only softens the far edge of the world, whatever its size
    const dist = this.homeCam.distanceTo(this.home0);
    this.scene.fog = new THREE.Fog(0xdfe8f3, dist * 1.4, dist * 4);
    this.controls.maxDistance = dist * 2;
  }

  select(p: Pick) {
    this.selected = p;
    this.applySelection();
    let focus: THREE.Vector3 | null = null;
    if (p?.kind === "branch") focus = this.sites.get(p.id)?.base.clone() ?? null;
    if (p?.kind === "lane") {
      const a = this.sites.get(p.from)?.base, b = this.sites.get(p.to)?.base;
      if (a && b) focus = a.clone().add(b).multiplyScalar(0.5);
    }
    if (p?.kind === "transfer") {
      const m = this.movers.find((x) => x.t?.id === p.id);
      if (m) focus = (m.waiting ? m.route[0].from.p : m.obj.position).clone();
    }
    if (focus) {
      this.flyTo = new THREE.Vector3(focus.x, 0, focus.z);
      // come in closer for a single branch or truck
      if (p?.kind !== "lane") {
        const off = this.camera.position.clone().sub(this.controls.target);
        if (off.length() > 70) this.camZoomTo = 60;
      }
    }
  }
  private camZoomTo: number | null = null;

  private applySelection() {
    const sel = this.selected;
    const related = new Set<string>();
    if (sel?.kind === "branch") related.add(sel.id);
    if (sel?.kind === "lane") { related.add(sel.from); related.add(sel.to); }
    if (sel?.kind === "transfer") {
      const t = this.movers.find((x) => x.t?.id === sel.id)?.t;
      if (t) { related.add(t.from); related.add(t.to); }
    }
    const any = related.size > 0;
    // the roads the picked lane or truck drives along
    let hot: Set<REdge> | null = null;
    if (sel?.kind === "lane") hot = this.laneEdges.get(`${sel.from}>${sel.to}`) ?? null;
    if (sel?.kind === "transfer") { const m = this.movers.find((x) => x.t?.id === sel.id); if (m) hot = new Set(m.route.map((d) => d.e)); }
    for (const st of this.streets) {
      const on = !!hot?.has(st.e);
      st.mesh.material = on ? HIGHLIGHT_ROAD : ROAD;
      st.mesh.renderOrder = on ? 2.5 : 2;
    }
    for (const r of this.arcs) {
      const strong = sel?.kind === "lane" && r.lane.from === sel.from && r.lane.to === sel.to;
      const touches = related.has(r.lane.from) || related.has(r.lane.to);
      const m = r.mesh.material as THREE.MeshBasicMaterial;
      m.visible = !any || touches;
      if (!r.mesh.userData.base) r.mesh.userData.base = m.opacity;
      m.opacity = strong ? 0.85 : any ? 0.14 : r.mesh.userData.base;
    }
    for (const m of this.movers) if (m.t) m.scale = sel?.kind === "transfer" && sel.id === m.t.id ? 2 : TRUCK_SCALE;
    for (const [id, lab] of this.labelObjs) lab.visible = related.has(id) || (!any && this.alwaysLabel.has(id)) || this.sites.get(id)?.b.cd === true;
    const ring = sel?.kind === "branch" ? this.sites.get(sel.id) : null;
    this.selRing.visible = !!ring;
    if (ring) this.selRing.position.set(ring.base.x, LAND + 0.14, ring.base.z);
  }

  private hoverCheck() {
    const o = this.hit();
    const id = o?.userData.kind === "branch" ? (o.userData.id as string) : null;
    if (id !== this.hovered) {
      const prev = this.hovered;
      this.hovered = id;
      if (prev) { const lab = this.labelObjs.get(prev); if (lab) lab.visible = this.alwaysLabel.has(prev) && !this.selected || this.isRelated(prev); }
      if (id) { const lab = this.labelObjs.get(id); if (lab) lab.visible = true; }
      this.onHover(id);
    }
    this.renderer.domElement.style.cursor = o ? "pointer" : "grab";
  }

  private isRelated(id: string) {
    const s = this.selected;
    return !!s && ((s.kind === "branch" && s.id === id) || (s.kind === "lane" && (s.from === id || s.to === id)));
  }

  private tmp = new THREE.Vector3();
  private loop = () => {
    this.raf = requestAnimationFrame(this.loop);
    const dt = Math.min(0.05, this.clock.getDelta());
    const t = this.clock.elapsedTime;
    if (this.traffic && this.net) {
      this.traffic.update(dt);
      this.net.update(dt);
      this.signals?.update();
      this.traffic.render(dt);
    }
    for (const w of this.workers) {
      const u = (Math.sin((t * w.speed + w.phase) * Math.PI * 2) + 1) / 2;
      this.tmp.lerpVectors(w.a, w.b, u);
      w.obj.position.set(this.tmp.x, 0.05, this.tmp.z);
      const dir = Math.cos((t * w.speed + w.phase) * Math.PI * 2) >= 0 ? 1 : -1;
      w.obj.rotation.y = Math.atan2(-(w.b.z - w.a.z) * dir, (w.b.x - w.a.x) * dir);
    }
    for (const o of this.bobs) o.position.y = o.userData.y0 + Math.sin(t * 2.2 + o.parent!.position.x) * 0.15;
    if (this.selRing.visible) (this.selRing.material as THREE.MeshBasicMaterial).opacity = 0.55 + 0.35 * Math.sin(t * 3);
    if (this.flyTo) {
      this.controls.target.lerp(this.flyTo, 0.07);
      if (this.camZoomTo) {
        const off = this.camera.position.clone().sub(this.controls.target);
        const len = off.length();
        if (len > this.camZoomTo + 1) this.camera.position.copy(this.controls.target).add(off.setLength(len + (this.camZoomTo - len) * 0.07));
        else this.camZoomTo = null;
      }
      if (this.controls.target.distanceTo(this.flyTo) < 0.05 && !this.camZoomTo) this.flyTo = null;
    }
    this.idle += dt;
    this.controls.autoRotate = this.idle > 15 && !this.selected;
    this.controls.autoRotateSpeed = 0.25;
    this.controls.update();
    // raycasting every object is the costliest thing per frame: do it when the pointer moves, else a few times a second
    if (this.pointerMoved || ++this.frame % 8 === 0) { this.pointerMoved = false; this.hoverCheck(); }
    this.renderer.render(this.scene, this.camera);
    this.labels.render(this.scene, this.camera);
  };

  zoom(f: number) { this.idle = 0; this.camera.position.sub(this.controls.target).multiplyScalar(f).add(this.controls.target); }
  home() { this.idle = 0; this.selected = null; this.camZoomTo = null; this.flyTo = this.home0.clone(); this.camera.position.copy(this.homeCam); this.applySelection(); }

  dispose() {
    cancelAnimationFrame(this.raf);
    this.renderer.domElement.removeEventListener("pointermove", this.onMove);
    this.renderer.domElement.removeEventListener("click", this.onClick);
    this.controls.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
    this.labels.domElement.remove();
  }
}

let ROAD_TEX: THREE.Texture | null = null;
const roadTex = () => (ROAD_TEX ??= asphalt());
// Roads lie flat on the ground and cross each other. They test depth (trucks and trees still hide them) but don't
// write it, and draw in order (shoulders, then asphalt), so where they cross or meet at a dock nothing flickers.
const flat = { side: THREE.DoubleSide, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 };
const ROAD = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.92, ...flat });
const SHOULDER = new THREE.MeshStandardMaterial({ color: 0xb9b2a0, roughness: 1, ...flat });
const JUNCTION = new THREE.MeshStandardMaterial({ color: 0x4b5260, roughness: 0.92, ...flat });
const HIGHLIGHT_ROAD = new THREE.MeshStandardMaterial({ color: 0xbcd0ff, roughness: 0.9, emissive: 0x2563eb, emissiveIntensity: 0.35, ...flat });

/** A flat strip of `width` following the curve on the ground, UV-mapped for the asphalt texture. */
function ribbon(curve: THREE.Curve<THREE.Vector3>, width: number, segments: number) {
  if (!ROAD.map) { ROAD.map = roadTex(); HIGHLIGHT_ROAD.map = ROAD.map; }
  const pos: number[] = [], uv: number[] = [], idx: number[] = [];
  const pts = curve.getSpacedPoints(segments);
  let along = 0;
  for (let i = 0; i < pts.length; i++) {
    const p = pts[i];
    if (i > 0) along += p.distanceTo(pts[i - 1]);
    const n = pts[Math.min(i + 1, pts.length - 1)].clone().sub(pts[Math.max(i - 1, 0)]).normalize();
    const side = new THREE.Vector3(-n.z, 0, n.x).multiplyScalar(width / 2);
    pos.push(p.x + side.x, p.y, p.z + side.z, p.x - side.x, p.y, p.z - side.z);
    uv.push(0, along / (width * 2.2), 1, along / (width * 2.2));
    if (i < pts.length - 1) { const a = i * 2; idx.push(a, a + 2, a + 1, a + 1, a + 2, a + 3); }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}
