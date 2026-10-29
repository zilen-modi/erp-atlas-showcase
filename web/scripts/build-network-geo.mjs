// Builds components/network/geo.json: outlines of the states the network operates in (plus neighbours
// for context) and the coordinates of every town in them, so branches sit at their real towns.
// Sources: us-atlas (US Census boundaries, TopoJSON) and cities.json (GeoNames). Run: node scripts/build-network-geo.mjs
import { createRequire } from "node:module";
import { writeFileSync } from "node:fs";
import { feature, mesh } from "topojson-client";

const require = createRequire(import.meta.url);
const topo = require("us-atlas/states-10m.json");
const cities = require("cities.json/cities.json");

const ACTIVE = { 23: "ME", 33: "NH", 50: "VT", 25: "MA", 44: "RI", "09": "CT", 36: "NY", 34: "NJ", 42: "PA" };
const CONTEXT = { 10: "DE", 24: "MD", 54: "WV", 39: "OH" };
const BOX = { minLon: -81.5, maxLon: -66.5, minLat: 38.5, maxLat: 47.6 };
const r = (v) => Math.round(v * 1000) / 1000;

const states = [];
for (const f of feature(topo, topo.objects.states).features) {
  const code = ACTIVE[f.id] ?? CONTEXT[f.id];
  if (!code) continue;
  const polys = f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates;
  const rings = [];
  for (const poly of polys) {
    const outer = poly[0];
    if (outer.length < 8) continue;                       // drop tiny islands
    const pts = outer.filter((_, i) => i % 2 === 0).map(([lon, lat]) => [r(lon), r(lat)]);
    rings.push(pts);
  }
  states.push({ code, active: Boolean(ACTIVE[f.id]), rings });
}
// borders between states (inner arcs only) for crisp border lines
const borders = mesh(topo, topo.objects.states, (a, b) => a !== b).coordinates
  .map((line) => line.filter(([lon, lat]) => lon > BOX.minLon && lon < BOX.maxLon && lat > BOX.minLat && lat < BOX.maxLat))
  .filter((l) => l.length > 1).map((l) => l.map(([lon, lat]) => [r(lon), r(lat)]));

const codes = new Set(Object.values(ACTIVE));
const towns = {};
for (const c of cities) {
  if (c.country !== "US" || !codes.has(c.admin1)) continue;
  const key = `${c.admin1}|${c.name.toUpperCase().replace(/[^A-Z0-9 ]/g, "").replace(/\s+/g, " ").trim()}`;
  if (!towns[key]) towns[key] = [r(+c.lng), r(+c.lat)];
}
// towns the GeoNames list names differently from BRANCH (townships, boroughs)
const ALIASES = {
  "ME|WEST BATH": [-69.86, 43.9], "ME|WINDHAM": [-70.42, 43.8], "NJ|EGG HARBOR TOWNSHIP": [-74.6, 39.38],
  "NJ|VERNON": [-74.48, 41.2], "NY|BRONX": [-73.87, 40.84], "PA|ASTON": [-75.43, 39.87], "NY|NEW YORK": [-74.01, 40.71],
};
Object.assign(towns, ALIASES);
writeFileSync(new URL("../components/network/geo.json", import.meta.url), JSON.stringify({ states, borders, towns }));
console.log(`states ${states.length}, borders ${borders.length}, towns ${Object.keys(towns).length}`);
