// The road network, laid out like a real town: roads run along the boundaries between neighbouring branches
// (a Voronoi diagram of the branch lots), so they pass between lots, never through them, and mostly meet in
// clean three-way junctions. Each branch reaches the nearest road by a short driveway that joins it square on,
// at a T. Trucks and cars follow shortest routes yard to yard.
import * as THREE from "three";

export type Site = { id: string; x: number; z: number; r: number };
export type Light = "g" | "y" | "r";
/** Actuated signal: one approach green at a time, moving on when another approach has traffic waiting. */
export type Signal = { green: number; state: Light; timer: number; demand: boolean[] };
export type RNode = { i: number; kind: "junction" | "yard"; p: THREE.Vector3; legs: REdge[]; branch?: string; rad: number; sig?: Signal;
  /** vehicles inside (or committed to) the junction box right now, and the movements they're making (kept by traffic) */
  busy: number; moves: Set<string>;
  /** a bend so tight that the two directions' corners touch: taken one way at a time */
  sharp: boolean };
export type DirEdge = {
  e: REdge; from: RNode; to: RNode; len: number;
  dir: THREE.Vector3; right: THREE.Vector3;
  /** which of `to`'s approaches this is, for its signal */
  leg: number;
};
export type REdge = { i: number; kind: "road" | "drive"; a: RNode; b: RNode; len: number; width: number; use: number; mst: boolean; fwd: DirEdge; back: DirEdge };

const MIN_GREEN = 3, MAX_GREEN = 10, AMBER = 1.1, ALL_RED = 0.6;
const NARROW = Math.PI / 4;      // roads leaving a junction closer together than this are too tight
const ROAD_W = 1.8;              // widest road, for sizing junction boxes
const QUEUE = 3.6;               // room a truck needs between two junction boxes
const T_GAP = 8.5;               // a driveway joins a road this far from the next junction, so a truck fits between
const FAR = 28;                  // Voronoi corners further than this from their branches are open country

/** Junction box radius: wide enough for the roads, and larger where two meet at a narrow angle so their lanes clear. */
function box(angles: number[]) {
  if (angles.length < 2) return ROAD_W / 2 + 0.3;
  const a = [...angles].sort((x, y) => x - y);
  let narrow = Math.PI;
  for (let k = 0; k < a.length; k++) narrow = Math.min(narrow, (k + 1 < a.length ? a[k + 1] : a[0] + Math.PI * 2) - a[k]);
  return Math.min(3.4, Math.max(ROAD_W / 2 + 0.3, (ROAD_W + 0.4) / (2 * Math.tan(Math.max(0.05, narrow) / 2))));
}

type Tri = { a: number; b: number; c: number; x: number; z: number; r2: number };

/** Delaunay triangulation (Bowyer-Watson); fine for a few hundred branches. */
function delaunay(pts: { x: number; z: number }[]): Tri[] {
  const n = pts.length;
  let x0 = Infinity, z0 = Infinity, x1 = -Infinity, z1 = -Infinity;
  for (const p of pts) { x0 = Math.min(x0, p.x); z0 = Math.min(z0, p.z); x1 = Math.max(x1, p.x); z1 = Math.max(z1, p.z); }
  const d = Math.max(x1 - x0, z1 - z0, 1) * 20, mx = (x0 + x1) / 2, mz = (z0 + z1) / 2;
  const P = [...pts, { x: mx - d, z: mz - d }, { x: mx, z: mz + d }, { x: mx + d, z: mz - d }];
  const tri = (a: number, b: number, c: number): Tri => {
    const A = P[a], B = P[b], C = P[c];
    const D = 2 * (A.x * (B.z - C.z) + B.x * (C.z - A.z) + C.x * (A.z - B.z)) || 1e-9;
    const a2 = A.x * A.x + A.z * A.z, b2 = B.x * B.x + B.z * B.z, c2 = C.x * C.x + C.z * C.z;
    const x = (a2 * (B.z - C.z) + b2 * (C.z - A.z) + c2 * (A.z - B.z)) / D;
    const z = (a2 * (C.x - B.x) + b2 * (A.x - C.x) + c2 * (B.x - A.x)) / D;
    return { a, b, c, x, z, r2: (A.x - x) ** 2 + (A.z - z) ** 2 };
  };
  let tris = [tri(n, n + 1, n + 2)];
  for (let i = 0; i < n; i++) {
    const p = P[i];
    const bad = tris.filter((t) => (p.x - t.x) ** 2 + (p.z - t.z) ** 2 < t.r2);
    const count = new Map<string, [number, number, number]>();
    for (const t of bad) for (const [u, v] of [[t.a, t.b], [t.b, t.c], [t.c, t.a]]) {
      const k = u < v ? `${u}|${v}` : `${v}|${u}`;
      const c = count.get(k);
      count.set(k, c ? [c[0], c[1], c[2] + 1] : [u, v, 1]);
    }
    tris = tris.filter((t) => !bad.includes(t));
    for (const [u, v, c] of count.values()) if (c === 1) tris.push(tri(u, v, i));
  }
  return tris.filter((t) => t.a < n && t.b < n && t.c < n);
}

export class Network {
  nodes: RNode[] = [];
  edges: REdge[] = [];
  yard = new Map<string, RNode>();
  private routes = new Map<string, DirEdge[] | null>();
  private sites: Site[] = [];

  /** Does the segment p-q pass over a branch lot (other than `skip`)? */
  private hitsLot(p: THREE.Vector3, q: THREE.Vector3, skip?: Site, margin = 0.95) {
    return this.sites.some((s) => {
      if (s === skip) return false;
      const dx = q.x - p.x, dz = q.z - p.z, L2 = dx * dx + dz * dz || 1;
      const t = Math.max(0, Math.min(1, ((s.x - p.x) * dx + (s.z - p.z) * dz) / L2));
      return Math.hypot(p.x + dx * t - s.x, p.z + dz * t - s.z) < s.r * margin;
    });
  }

  constructor(sites: Site[], onLand: (x: number, z: number) => boolean) {
    this.sites = sites;
    const wet = (p: THREE.Vector3, q: THREE.Vector3) => {
      const k = Math.max(2, Math.ceil(p.distanceTo(q) / 2));
      let off = 0;
      for (let i = 1; i < k; i++) if (!onLand(p.x + ((q.x - p.x) * i) / k, p.z + ((q.z - p.z) * i) / k)) off++;
      return off / k > 0.25;
    };
    // roads: the Voronoi edges between neighbouring branches (each joins the circumcentres of two triangles)
    const tris = delaunay(sites);
    const corner = new Map<Tri, RNode>();
    const cornerOf = (t: Tri) => {
      if (t.r2 > FAR * FAR) return null;
      let nd = corner.get(t);
      if (!nd) {
        // co-circular branches give the same corner twice: share it
        nd = [...corner.values()].find((o) => Math.hypot(o.p.x - t.x, o.p.z - t.z) < 0.5) ?? this.node("junction", new THREE.Vector3(t.x, 0.06, t.z));
        corner.set(t, nd);
      }
      return nd;
    };
    const byEdge = new Map<string, Tri[]>();
    for (const t of tris) for (const [u, v] of [[t.a, t.b], [t.b, t.c], [t.c, t.a]]) {
      const k = u < v ? `${u}|${v}` : `${v}|${u}`;
      byEdge.set(k, [...(byEdge.get(k) ?? []), t]);
    }
    const seen = new Set<string>();
    for (const ts of byEdge.values()) {
      if (ts.length !== 2) continue;
      const a = cornerOf(ts[0]), b = cornerOf(ts[1]);
      if (!a || !b || a === b) continue;
      const k = a.i < b.i ? `${a.i}|${b.i}` : `${b.i}|${a.i}`;
      if (seen.has(k) || wet(a.p, b.p)) continue;
      seen.add(k);
      this.edge("road", a, b, false);
    }
    this.markSpine();
    this.connect();
    this.splitCrossings();
    this.tidy();
    this.driveways(sites);
    this.splitCrossings();
    this.pruneDeadEnds();
    this.finish();
  }

  /** The shortest roads that keep everything connected are never dropped. */
  private markSpine() {
    const uf = new Map<RNode, RNode>();
    const find = (x: RNode): RNode => { const p = uf.get(x) ?? x; if (p === x) return x; const r = find(p); uf.set(x, r); return r; };
    for (const e of [...this.edges].sort((x, y) => x.len - y.len)) {
      const a = find(e.a), b = find(e.b);
      e.mst = a !== b;
      if (a !== b) uf.set(a, b);
    }
  }

  /** Pieces of road the sea or open country cut off are joined to the rest by the shortest link. */
  private connect() {
    for (let guard = 0; guard < 200; guard++) {
      const comp = new Map<RNode, number>();
      let c = 0;
      for (const start of this.nodes) {
        if (comp.has(start)) continue;
        const stack = [start];
        comp.set(start, c);
        while (stack.length) {
          const nd = stack.pop()!;
          for (const e of this.edges) {
            const o = e.a === nd ? e.b : e.b === nd ? e.a : null;
            if (o && !comp.has(o)) { comp.set(o, c); stack.push(o); }
          }
        }
        c++;
      }
      if (c <= 1) return;
      // join the first piece to its nearest neighbour piece
      let best: [RNode, RNode, number] | null = null;
      for (const a of this.nodes) if (comp.get(a) === 0) for (const b of this.nodes) if (comp.get(b) !== 0) {
        const d = a.p.distanceTo(b.p);
        if (!best || d < best[2]) best = [a, b, d];
      }
      if (!best) return;
      this.edge("road", best[0], best[1], true);
    }
  }

  /** Each branch's driveway: from its yard to the nearest road, joining square on at a T (or at a junction close by). */
  private driveways(sites: Site[]) {
    for (const s of [...sites].sort((x, y) => y.r - x.r)) {
      const c = new THREE.Vector3(s.x, 0.06, s.z);
      let best: { e: REdge; t: number; p: THREE.Vector3; d: number } | null = null;
      for (const e of this.edges) {
        if (e.kind !== "road") continue;
        const ab = e.b.p.clone().sub(e.a.p), L = ab.length();
        if (L < 1e-6) continue;
        let t = Math.max(0, Math.min(1, c.clone().sub(e.a.p).dot(ab) / (L * L)));
        // keep the T clear of the junctions at either end; on a short road, use the nearer junction itself
        if (L < 2 * T_GAP) t = t < 0.5 ? 0 : 1;
        else t = Math.max(T_GAP / L, Math.min(1 - T_GAP / L, t));
        const p = e.a.p.clone().addScaledVector(ab, t);
        const d = p.distanceTo(c);
        if (best && d >= best.d) continue;
        if (this.hitsLot(c, p, s)) continue;
        best = { e, t, p, d };
      }
      if (!best) continue;
      let gate: RNode;
      if (best.t <= 0) gate = best.e.a;
      else if (best.t >= 1) gate = best.e.b;
      else {
        gate = this.node("junction", best.p.setY(0.06));
        const e = best.e;
        this.edges.splice(this.edges.indexOf(e), 1);
        this.edge("road", e.a, gate, e.mst);
        this.edge("road", gate, e.b, e.mst);
      }
      const u = gate.p.clone().sub(c).setY(0).normalize();
      const y = this.node("yard", new THREE.Vector3(s.x + u.x * s.r * 0.5, 0.06, s.z + u.z * s.r * 0.5));
      y.branch = s.id;
      this.yard.set(s.id, y);
      // far from any road: a short driveway to the lot's own gate, and a proper road on from there
      if (best.d > s.r + 8) {
        const own = this.node("junction", new THREE.Vector3(s.x + u.x * (s.r + 1.6), 0.06, s.z + u.z * (s.r + 1.6)));
        this.edge("road", own, gate, true);
        gate = own;
      }
      this.edge("drive", y, gate, true);
    }
  }

  /** Road stubs that lead nowhere (no driveway, no onward road) are taken up. */
  private pruneDeadEnds() {
    for (let guard = 0; guard < 2000; guard++) {
      const deg = new Map<RNode, number>();
      for (const e of this.edges) for (const nd of [e.a, e.b]) deg.set(nd, (deg.get(nd) ?? 0) + 1);
      const stub = this.edges.find((e) => e.kind === "road" && ((deg.get(e.a) === 1 && e.a.kind === "junction") || (deg.get(e.b) === 1 && e.b.kind === "junction")));
      if (!stub) return;
      this.edges.splice(this.edges.indexOf(stub), 1);
    }
  }

  private node(kind: RNode["kind"], p: THREE.Vector3): RNode {
    const nd: RNode = { i: this.nodes.length, kind, p, legs: [], rad: 0, busy: 0, moves: new Set(), sharp: false };
    this.nodes.push(nd);
    return nd;
  }
  private edge(kind: REdge["kind"], a: RNode, b: RNode, mst: boolean): REdge {
    const e = { i: this.edges.length, kind, a, b, len: a.p.distanceTo(b.p), width: kind === "drive" ? 1.3 : 1.35, use: 0, mst } as REdge;
    this.edges.push(e);
    return e;
  }

  /** Where two roads cross, put a junction there and split both; a crossing hard by a junction drops a road instead. */
  private splitCrossings() {
    for (let guard = 0; guard < 2000; guard++) {
      const roads = this.edges.filter((e) => e.kind === "road");
      let hit: { e: REdge; f: REdge; p: THREE.Vector3 } | null = null;
      outer: for (let x = 0; x < roads.length; x++) for (let y = x + 1; y < roads.length; y++) {
        const e = roads[x], f = roads[y];
        if (e.a === f.a || e.a === f.b || e.b === f.a || e.b === f.b) continue;
        const rx = e.b.p.x - e.a.p.x, rz = e.b.p.z - e.a.p.z, sx = f.b.p.x - f.a.p.x, sz = f.b.p.z - f.a.p.z;
        const den = rx * sz - rz * sx;
        if (Math.abs(den) < 1e-9) continue;
        const qx = f.a.p.x - e.a.p.x, qz = f.a.p.z - e.a.p.z;
        const t = (qx * sz - qz * sx) / den, u = (qx * rz - qz * rx) / den;
        if (t <= 0 || t >= 1 || u <= 0 || u >= 1) continue;
        hit = { e, f, p: new THREE.Vector3(e.a.p.x + rx * t, 0.06, e.a.p.z + rz * t) };
        break outer;
      }
      if (!hit) return;
      const { e, f, p } = hit;
      const tight = [e.a, e.b, f.a, f.b].some((nd) => nd.p.distanceTo(p) < 3);
      if (tight && !(e.mst && f.mst)) {
        // drop the optional (or else the longer) one
        const drop = e.mst ? f : f.mst ? e : e.len > f.len ? e : f;
        this.edges.splice(this.edges.indexOf(drop), 1);
        continue;
      }
      const j = this.node("junction", p);
      this.edges.splice(this.edges.indexOf(e), 1);
      this.edges.splice(this.edges.indexOf(f), 1);
      for (const g of [e, f]) { this.edge("road", g.a, j, g.mst); this.edge("road", j, g.b, g.mst); }
    }
  }

  /**
   * Keep junctions compact: an optional road leaving at a narrow angle to another is dropped, and junctions
   * without room for a queue between their boxes merge (the busier one stays put). Repeats until nothing changes.
   */
  private tidy() {
    const ang = (nd: RNode, e: REdge) => { const o = e.a === nd ? e.b : e.a; return Math.atan2(o.p.z - nd.p.z, o.p.x - nd.p.x); };
    const legsOf = () => {
      const m = new Map<RNode, REdge[]>();
      for (const e of this.edges) for (const nd of [e.a, e.b]) { const l = m.get(nd); if (l) l.push(e); else m.set(nd, [e]); }
      return m;
    };
    const boxOf = (nd: RNode, legs: Map<RNode, REdge[]>) => box((legs.get(nd) ?? []).map((e) => ang(nd, e)));
    for (let pass = 0; pass < 600; pass++) {
      const legs = legsOf();
      let drop: REdge | null = null;
      for (const [nd, ls] of legs) {
        if (nd.kind !== "junction" || ls.length < 2) continue;
        const sorted = ls.map((e) => ({ e, a: ang(nd, e) })).sort((x, y) => x.a - y.a);
        for (let k = 0; k < sorted.length && !drop; k++) {
          const x = sorted[k], y = sorted[(k + 1) % sorted.length];
          const gap = y.a - x.a + (k + 1 >= sorted.length ? Math.PI * 2 : 0);
          if (gap >= NARROW) continue;
          const optional = [x.e, y.e].filter((e) => e.kind === "road" && !e.mst).sort((p, q) => q.len - p.len);
          if (optional.length) drop = optional[0];
        }
        if (drop) break;
      }
      if (drop) { this.edges.splice(this.edges.indexOf(drop), 1); continue; }
      const short = this.edges.find((e) => e.kind === "road" && e.a.p.distanceTo(e.b.p) < boxOf(e.a, legs) + boxOf(e.b, legs) + QUEUE);
      if (!short) break;
      const [keep, gone] = (legs.get(short.a)?.length ?? 0) >= (legs.get(short.b)?.length ?? 0) ? [short.a, short.b] : [short.b, short.a];
      // the merged junction goes wherever its roads cross the fewest lots: either end, or between them
      const ends = [...(legs.get(keep) ?? []), ...(legs.get(gone) ?? [])].filter((x) => x !== short)
        .map((x) => (x.a === keep || x.a === gone ? x.b : x.a)).filter((o) => o !== keep && o !== gone);
      const spots = [keep.p.clone(), gone.p.clone(), keep.p.clone().add(gone.p).multiplyScalar(0.5)];
      const cost = (p: THREE.Vector3) => ends.filter((o) => this.hitsLot(p, o.p, undefined, 0.8)).length;
      keep.p.copy(spots.reduce((b, p) => (cost(p) < cost(b) ? p : b)));
      for (const x of this.edges) { if (x.a === gone) x.a = keep; if (x.b === gone) x.b = keep; }
      this.dedupe();
    }
  }

  /** Drop loops and second copies of the same road. */
  private dedupe() {
    const seen = new Set<string>();
    this.edges = this.edges.filter((x) => {
      if (x.a === x.b) return false;
      const k = `${x.kind}|${Math.min(x.a.i, x.b.i)}|${Math.max(x.a.i, x.b.i)}`;
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    });
  }

  private finish() {
    this.edges.forEach((e, i) => { e.i = i; e.len = e.a.p.distanceTo(e.b.p); e.a.legs.push(e); e.b.legs.push(e); });
    this.nodes = this.nodes.filter((nd) => nd.legs.length);
    this.nodes.forEach((nd, i) => { nd.i = i; });
    const dirEdge = (e: REdge, from: RNode, to: RNode): DirEdge => {
      const dir = to.p.clone().sub(from.p).setY(0).normalize();
      return { e, from, to, len: e.len, dir, right: new THREE.Vector3(-dir.z, 0, dir.x), leg: to.legs.indexOf(e) };
    };
    for (const e of this.edges) { e.fwd = dirEdge(e, e.a, e.b); e.back = dirEdge(e, e.b, e.a); }
  }

  /** Widths from traffic, junction sizes, and signals where three or more roads meet. */
  settle() {
    const top = Math.max(1, ...this.edges.map((e) => e.use));
    for (const e of this.edges) if (e.kind === "road") e.width = 1.35 + 0.45 * Math.sqrt(e.use / top);
    for (const nd of this.nodes) {
      if (nd.kind === "yard") continue;
      const angs = nd.legs.map((e) => { const o = e.a === nd ? e.b : e.a; return Math.atan2(o.p.z - nd.p.z, o.p.x - nd.p.x); });
      nd.rad = box(angs);
      if (angs.length === 2) { const d = Math.abs(angs[0] - angs[1]); nd.sharp = Math.min(d, Math.PI * 2 - d) < (5 * Math.PI) / 6; }
      // lights wherever three or more ways meet, depot entrances included, so every approach gets its turn
      if (nd.legs.length >= 3) nd.sig = { green: 0, state: "g", timer: Math.random() * MIN_GREEN, demand: nd.legs.map(() => false) };
    }
  }

  /** The way into `to` along edge `e`, as a directed edge. */
  into(e: REdge, to: RNode) { return e.b === to ? e.fwd : e.back; }

  /** Shortest route yard to yard (never cutting through another branch's yard). */
  route(from: string, to: string): DirEdge[] | null {
    const key = `${from}>${to}`;
    if (this.routes.has(key)) return this.routes.get(key)!;
    const src = this.yard.get(from), dst = this.yard.get(to);
    let out: DirEdge[] | null = null;
    if (src && dst && src !== dst) {
      const dist = new Map<RNode, number>([[src, 0]]), prev = new Map<RNode, DirEdge>();
      const open = new Set<RNode>([src]);
      while (open.size) {
        let cur: RNode | null = null;
        for (const nd of open) if (!cur || dist.get(nd)! < dist.get(cur)!) cur = nd;
        open.delete(cur!);
        if (cur === dst) break;
        if (cur!.kind === "yard" && cur !== src) continue;
        for (const e of cur!.legs) {
          const de = e.a === cur ? e.fwd : e.back;
          const d = dist.get(cur!)! + e.len;
          if (d < (dist.get(de.to) ?? Infinity)) { dist.set(de.to, d); prev.set(de.to, de); open.add(de.to); }
        }
      }
      if (prev.has(dst)) {
        out = [];
        for (let nd = dst; nd !== src; nd = prev.get(nd)!.from) out.unshift(prev.get(nd)!);
      }
    }
    this.routes.set(key, out);
    return out;
  }

  /** Advance every signal; `demand` was set by traffic queuing at each approach this frame. */
  update(dt: number) {
    for (const nd of this.nodes) {
      const s = nd.sig;
      if (!s) continue;
      s.timer += dt;
      // stay green while our own queue is still moving off (up to a limit), then serve whoever is waiting
      const others = s.demand.some((d, i) => d && i !== s.green);
      const done = !s.demand[s.green] || s.timer >= MAX_GREEN;
      if (s.state === "g" && s.timer >= MIN_GREEN && others && done) { s.state = "y"; s.timer = 0; }
      else if (s.state === "y" && s.timer >= AMBER) { s.state = "r"; s.timer = 0; }
      // the next approach gets green only once the box is clear
      else if (s.state === "r" && s.timer >= ALL_RED && nd.busy === 0) {
        const k = s.demand.length;
        let next = (s.green + 1) % k;
        for (let i = 1; i <= k; i++) if (s.demand[(s.green + i) % k]) { next = (s.green + i) % k; break; }
        s.green = next; s.state = "g"; s.timer = 0;
      }
      s.demand.fill(false);
    }
  }

  light(nd: RNode, leg: number): Light {
    const s = nd.sig;
    if (!s) return "g";
    return leg === s.green ? s.state : "r";
  }
}
