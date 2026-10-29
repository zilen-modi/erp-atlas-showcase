// Vehicles on the road network. Each one follows its route yard to yard on the right-hand side, keeps a safe
// gap to whatever is ahead (on its road or just round the corner), stops at the line on red, and never pulls
// into a junction it can't get out of. At the far yard it disappears and starts again from the first yard
// once there's room, so nothing ever drives through anything.
import * as THREE from "three";
import type { DirEdge, Network, RNode } from "./roads";

export type Vehicle = {
  obj: THREE.Group; route: DirEdge[]; k: number; s: number; v: number; vmax: number; half: number;
  scale: number; waiting: boolean; snap: boolean; yaw: number;
  /** the junction this vehicle has claimed, from the moment it decides to cross the line until it's in */
  claim?: RNode;
};

/** A movement through a junction: which road in, which road out. */
const move = (from: DirEdge | undefined, to: DirEdge) => `${from?.e.i ?? -1}>${to.e.i}:${to.from.i}`;

const ACCEL = 1.1, BRAKE = 3.2, HEADWAY = 0.7, FADE = 1.4;

export class Traffic {
  vehicles: Vehicle[] = [];
  private occ = new Map<DirEdge, Vehicle[]>();
  private p = new THREE.Vector3();

  constructor(private net: Network) {}

  private on(e: DirEdge) { let l = this.occ.get(e); if (!l) this.occ.set(e, (l = [])); return l; }
  private clearAt(e: DirEdge, s: number, half: number) {
    return this.on(e).every((o) => Math.abs(o.s - s) >= o.half + half + HEADWAY + 0.3);
  }

  /** Put a vehicle somewhere free along its route, or have it wait at its first yard. */
  add(v: Vehicle, rnd: () => number) {
    this.vehicles.push(v);
    const total = v.route.reduce((a, e) => a + e.len, 0);
    for (let tries = 0; tries < 25; tries++) {
      let x = rnd() * total, k = 0;
      while (k < v.route.length - 1 && x > v.route[k].len) x -= v.route[k++].len;
      const e = v.route[k], s = Math.min(x, e.len);
      // not at or past a stop line
      if (e.to.rad && e.len - e.to.rad - 0.35 - s - v.half < 0.6) continue;
      if (!this.clearAt(e, s, v.half)) continue;
      v.k = k; v.s = s; v.waiting = false; v.snap = true;
      this.on(e).push(v);
      return;
    }
    v.waiting = true;
  }

  /** Distance from a vehicle's front bumper to the stop line at the end of its road. */
  private toLine(m: Vehicle, e: DirEdge) { return e.len - e.to.rad - 0.35 - m.s - m.half; }

  /**
   * At a stop line: may this vehicle go into the junction? Not on red (or amber it can stop for), not unless
   * there's room to get clear on the far side, and only while everyone in the box is making the same move
   * (any other path through it would cross or merge with ours). Registers its demand with the lights.
   */
  private mayEnter(m: Vehicle, e: DirEdge, next: DirEdge, dist: number) {
    const nd = e.to;
    if (dist < 12 && nd.sig) nd.sig.demand[e.leg] = true;
    const l = this.net.light(nd, e.leg);
    if (l === "r" || (l === "y" && dist > (m.v * m.v) / (2 * BRAKE) + 0.3)) return false;
    // (following round the corner keeps the box's width extra, so we need room for that, our length and the gap)
    if (this.on(next).some((o) => o.s - o.half < 2 * nd.rad + m.half * 2 + HEADWAY + 0.2)) return false;
    const mine = move(e, next);
    return [...nd.moves].every((x) => x === mine);
  }
  private claim(m: Vehicle, e: DirEdge, next: DirEdge) { m.claim = e.to; e.to.busy++; e.to.moves.add(move(e, next)); }
  private boxed(nd: RNode) { return nd.legs.length >= 3 || nd.sharp; }

  update(dt: number) {
    // who is inside a junction box: front past the stop line coming in, or tail not yet clear going out
    for (const nd of this.net.nodes) { nd.busy = 0; nd.moves.clear(); }
    for (const m of this.vehicles) {
      if (m.waiting) continue;
      const e = m.route[m.k], next = m.route[m.k + 1];
      // past the stop line: committed to the junction, and counted in it from that moment
      if (e.to.rad && next && (m.claim === e.to || this.toLine(m, e) < 0.02)) { e.to.busy++; e.to.moves.add(move(e, next)); }
      // a tail still in the box behind only holds it while moving; parked in its own exit lane it's in nobody's way,
      // and holding the box would let two short-road queues wait on each other for ever
      if (e.from.rad && m.s - m.half < e.from.rad && m.v > 0.05) { e.from.busy++; e.from.moves.add(move(m.route[m.k - 1], e)); }
    }
    for (const m of this.vehicles) {
      if (m.waiting) {
        const e = m.route[0], next = m.route[1];
        if (!this.on(e).every((o) => o.s - o.half >= m.half + HEADWAY + 0.3)) continue;
        // a driveway too short to stop on: setting off is going into the junction, so it waits for its turn
        m.s = 0; m.v = 0;
        const atLine = !!next && this.boxed(e.to) && this.toLine(m, e) < 0.6;
        if (atLine && !this.mayEnter(m, e, next, Math.max(0.02, this.toLine(m, e)))) continue;
        m.k = 0; m.v = atLine ? 0.4 : m.vmax * 0.5; m.waiting = false; m.snap = true;
        this.on(e).push(m);
        if (atLine) this.claim(m, e, next);
        continue;
      }
      const e = m.route[m.k], next = m.route[m.k + 1];
      let room = Infinity;
      for (const o of this.on(e)) if (o !== m && o.s > m.s) room = Math.min(room, o.s - m.s - o.half - m.half - HEADWAY);
      // round a corner the straight-line gap is shorter than the gap along the road: leave the box's width more
      if (next) for (const o of this.on(next)) room = Math.min(room, e.len - m.s + o.s - o.half - m.half - HEADWAY - e.to.rad);
      if (next && this.boxed(e.to) && m.claim !== e.to) {
        const dist = this.toLine(m, e);
        if (dist >= 0.02) {
          if (!this.mayEnter(m, e, next, dist)) room = Math.min(room, dist);
          // about to cross the line: claim the box now, so nobody else pulls in meanwhile
          else if (dist < m.v * dt + 0.6) this.claim(m, e, next);
        }
      }
      const want = Math.min(m.vmax, Math.sqrt(2 * BRAKE * Math.max(0, room - 0.05)));
      m.v = m.v < want ? Math.min(want, m.v + ACCEL * dt) : want;
    }
    for (const m of this.vehicles) {
      if (m.waiting) continue;
      m.s += m.v * dt;
      while (!m.waiting && m.s >= m.route[m.k].len) {
        const e = m.route[m.k], list = this.on(e);
        list.splice(list.indexOf(m), 1);
        m.claim = undefined;
        if (m.k + 1 < m.route.length) { m.s -= e.len; m.k++; this.on(m.route[m.k]).push(m); }
        else m.waiting = true;
      }
    }
  }

  /** Place the models: right-hand lane, turning smoothly through junctions, fading in and out at the yards. */
  render(dt: number) {
    const a = 1 - Math.exp(-dt / 0.12), ay = 1 - Math.exp(-dt / 0.16);
    for (const m of this.vehicles) {
      if (m.waiting) { m.obj.visible = false; continue; }
      m.obj.visible = true;
      const e = m.route[m.k];
      const side = Math.max(0.44, e.e.width / 4);
      this.p.copy(e.from.p).addScaledVector(e.dir, m.s).addScaledVector(e.right, side).setY(0.05);
      const yaw = Math.atan2(-e.dir.z, e.dir.x);
      if (m.snap) { m.obj.position.copy(this.p); m.yaw = yaw; m.snap = false; }
      else {
        m.obj.position.lerp(this.p, a);
        let d = yaw - m.yaw;
        d = Math.atan2(Math.sin(d), Math.cos(d));
        m.yaw += d * ay;
      }
      m.obj.rotation.y = m.yaw;
      const fromStart = m.k === 0 ? m.s : Infinity, toEnd = m.k === m.route.length - 1 ? e.len - m.s : Infinity;
      const f = Math.max(0, Math.min(1, fromStart / FADE, toEnd / FADE));
      m.obj.scale.setScalar(m.scale * f * f * (3 - 2 * f));
    }
  }
}
