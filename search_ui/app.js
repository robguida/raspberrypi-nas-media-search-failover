const DS_ROOT = "/search";
const DB_NAME = "media_index";
const DB = `${DS_ROOT}/${DB_NAME}`;

const COUNTRIES_GEOJSON = "./data/countries.geojson";
const CITIES_GEOJSON = "./data/cities.geojson";

const PAGE_SIZE = 24;
let currentPage = 0;

let libraryCitySet = new Set();
let libraryCitiesByCountry = new Map();

let selectedCountry = null;
let selectedCity = null;

const p = row.path;       // unix path from API
const ext = row.ext?.toLowerCase();

const SMB_HOST = "raspberrypi";              // or raspberrypi.local (Windows usually prefers just hostname)
const SMB_SHARE = "CopyYourFilesHere";       // your SMB share name
const UNIX_PREFIX = "/srv/mergerfs/MergedDrives/CopyYourFilesHere/"; // adjust if different

function mediaUrl(path) {
  return `/preview?path=${encodeURIComponent(path)}`;
}

function isImage(ext) {
  return ["jpg","jpeg","png","webp","gif"].includes(ext);
}

function isVideo(ext) {
  return ["mp4","mov","m4v"].includes(ext);
}

function toUncPath(unixPath) {
  // strip prefix
  let rel = unixPath.startsWith(UNIX_PREFIX) ? unixPath.slice(UNIX_PREFIX.length) : unixPath;
  rel = rel.replaceAll("/", "\\");
  return `\\\\${SMB_HOST}\\${SMB_SHARE}\\${rel}`;
}

function qs(id){ return document.getElementById(id); }

async function fetchJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status} for ${url}`);
  return await r.json();
}

function fillDatalist(datalistEl, values) {// add near your routes
  import fs from "fs";
  import path from "path";

  app.get("/preview", (req, res) => {
    const p = req.query.path;
    if (!p || typeof p !== "string") return res.status(400).send("missing path");

    // SAFETY: only allow files under your mergerfs root
    const ROOT = "/srv/mergerfs/MergedDrives";
    const real = path.resolve(p);
    if (!real.startsWith(ROOT + path.sep)) return res.status(403).send("forbidden");

    // stream
    const stat = fs.statSync(real);
    res.setHeader("Content-Length", stat.size);

    // basic content type (good enough for browser preview)
    const ext = path.extname(real).toLowerCase();
    const ct =
        ext === ".jpg" || ext === ".jpeg" ? "image/jpeg" :
            ext === ".png" ? "image/png" :
                ext === ".webp" ? "image/webp" :
                    ext === ".gif" ? "image/gif" :
                        ext === ".mp4" ? "video/mp4" :
                            ext === ".mov" ? "video/quicktime" :
                                ext === ".m4v" ? "video/x-m4v" :
                                    "application/octet-stream";

    res.setHeader("Content-Type", ct);
    fs.createReadStream(real).pipe(res);
  });
  datalistEl.innerHTML = "";
  for (const v of values) {
    const opt = document.createElement("option");
    opt.value = v;
    datalistEl.appendChild(opt);
  }
}

function setCityDatalistForCountry(country) {
  qs("cityList").innerHTML = "";
  if (!country) return;
  const cities = libraryCitiesByCountry.get(country) || [];
  fillDatalist(qs("cityList"), cities);
}

function asISODateStart(d) { return d ? `${d}T00:00:00` : ""; }
function asISODateEnd(d)   { return d ? `${d}T23:59:59` : ""; }
function encodePath(p){ return encodeURIComponent(p); }

function buildSearchUrl(page) {
  const params = new URLSearchParams();
  params.set("_shape", "objects");
  params.set("_size", String(PAGE_SIZE));
  params.set("_offset", String(page * PAGE_SIZE));
  params.set("_sort_desc", "taken_utc");
const q = qs("q").value.trim();
  const country = (qs("countryInput").value || selectedCountry || "").trim();
  const city = (qs("cityInput").value || selectedCity || "").trim();
  const camera = (qs("cameraInput").value || "").trim();
  const mediaType = qs("mediaType").value;
  const dateFrom = qs("dateFrom").value;
  const dateTo = qs("dateTo").value;

  if (country) params.set("country__exact", country);
  if (city) params.set("city__exact", city);
  if (camera) params.set("camera__exact", camera);
  if (mediaType) params.set("media_type__exact", mediaType);
  if (dateFrom) params.set("taken_utc__gte", asISODateStart(dateFrom));
  if (dateTo) params.set("taken_utc__lte", asISODateEnd(dateTo));

  // Simple contains (upgrade to FTS later if desired)
  if (q) params.set("filename__contains", q);

  return `${DB}/v_search.json?${params.toString()}`;
}

function smbLinkForPath(localPath) {
  // Best-effort conversion: /srv/mergerfs/<ShareName>/sub/file.jpg -> smb://raspberrypi.local/<ShareName>/sub/file.jpg
  const prefix = "/srv/mergerfs/";
  if (!localPath.startsWith(prefix)) return null;
  const rel = localPath.slice(prefix.length);
  return `smb://raspberrypi.local/${rel.replaceAll(" ", "%20")}`;
}

async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    alert("Copied to clipboard");
  } catch {
    prompt("Copy this path:", text);
  }
}

function renderResults(rows) {
  const container = qs("results");
  container.innerHTML = "";

  for (const r of rows) {
    const card = document.createElement("div");
    card.className = "resultCard";

    const previewUrl = `/preview?path=${encodePath(r.path)}`;
    const downloadUrl = `/download?path=${encodePath(r.path)}`;
    const smb = smbLinkForPath(r.path);

    let media = "";
    if (isImage(r.ext)) {
      media = `<img class="preview" loading="lazy" src="${mediaUrl(r.path)}" alt="">`;
    } else if (isVideo(r.ext)) {
      media = `<video class="preview" controls preload="metadata" src="${mediaUrl(r.path)}"></video>`;
    }

    const title = `<a class="resultTitle" href="${downloadUrl}" title="Download">${r.filename}</a>`;
    const smbLine = smb ? `<a class="muted" href="${smb}">Open via SMB</a>` : `<span class="muted">SMB link not derivable</span>`;

    card.innerHTML = `
      ${media}
      <div class="resultBody">
        ${title}
        <div class="muted">${[r.country, r.city].filter(Boolean).join(" · ")}</div>
        <div class="muted">${r.camera || ""}</div>
        <div class="muted">${r.taken_utc || ""}</div>
        <div class="muted hideme"><code>${r.path}</code></div>
        <div class="resultActions">
          ${smbLine}
          <button class="mini secondary" data-copy="${r.path}">Copy path</button>
        </div>
      </div>
    `;
    container.appendChild(card);
  }

  container.querySelectorAll("button[data-copy]").forEach(btn => {
    btn.addEventListener("click", () => copyToClipboard(btn.getAttribute("data-copy")));
  });

  qs("count").textContent = String(rows.length);
}

async function runSearch(page=0) {
  currentPage = page;
  qs("pageInfo").textContent = `Page ${currentPage + 1}`;
  const url = buildSearchUrl(currentPage);
  const data = await fetchJson(url);
  renderResults(data.rows || []);
}

// ---- Map helpers ----
function haversineKm(lat1, lon1, lat2, lon2) {
  const R = 6371;
  const toRad = (x) => x * Math.PI / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat/2)**2 +
    Math.cos(toRad(lat1))*Math.cos(toRad(lat2))*Math.sin(dLon/2)**2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

function pointInRing(lon, lat, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0], yi = ring[i][1];
    const xj = ring[j][0], yj = ring[j][1];
    const intersect = ((yi > lat) !== (yj > lat)) &&
      (lon < (xj - xi) * (lat - yi) / (yj - yi + 0.0) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

function pointInGeoJSON(lon, lat, feature) {
  const g = feature.geometry;
  if (g.type === "Polygon") return pointInRing(lon, lat, g.coordinates[0]);
  if (g.type === "MultiPolygon") {
    for (const poly of g.coordinates) if (pointInRing(lon, lat, poly[0])) return true;
  }
  return false;
}

function findCountryForPoint(lat, lon, countriesGeo) {
  for (const f of countriesGeo.features) {
    if (pointInGeoJSON(lon, lat, f)) {
      return f.properties?.ADMIN || f.properties?.NAME || null;
    }
  }
  return null;
}

function filterNaturalEarthCitiesToLibrary(neCitiesGeo) {
  const kept = [];
  for (const f of neCitiesGeo.features) {
    const props = f.properties || {};
    const city = props.NAME || props.name;
    const country = props.ADM0NAME || props.SOV0NAME || props.COUNTRY;
    if (!city || !country) continue;
    const key = `${country}|${city}`;
    if (libraryCitySet.has(key)) kept.push(f);
  }
  return { type: "FeatureCollection", features: kept };
}

async function initMap() {
  const countriesGeo = await fetchJson(COUNTRIES_GEOJSON);
  const neCitiesGeo = await fetchJson(CITIES_GEOJSON);
  const citiesGeo = filterNaturalEarthCitiesToLibrary(neCitiesGeo);

  const map = L.map("map", { worldCopyJump: true }).setView([20, 0], 2);

  L.geoJSON(countriesGeo, {
    style: () => ({ weight: 1, fillOpacity: 0.06 })
  }).addTo(map);

  const cityLayer = L.geoJSON(citiesGeo, {
    pointToLayer: (f, latlng) => L.circleMarker(latlng, { radius: 3, fillOpacity: 0.7, weight: 0 })
  }).addTo(map);

  let marker = null;

  qs("clearMap").addEventListener("click", () => {
    selectedCountry = null;
    selectedCity = null;
    qs("selCountry").textContent = "—";
    qs("selCity").textContent = "—";
    qs("countryInput").value = "";
    qs("cityInput").value = "";
    setCityDatalistForCountry("");
    if (marker) { map.removeLayer(marker); marker = null; }
    runSearch(0);
  });

  map.on("click", (e) => {
    const lat = e.latlng.lat, lon = e.latlng.lng;
    const country = findCountryForPoint(lat, lon, countriesGeo);
    if (!country) return;

    selectedCountry = country;
    qs("selCountry").textContent = country;
    qs("countryInput").value = country;
    setCityDatalistForCountry(country);

    // Nearest library city (use filtered NE points)
    const features = cityLayer.toGeoJSON().features;
    let best = null, bestKm = Infinity;
    for (const f of features) {
      const props = f.properties || {};
      const cityName = props.NAME || props.name;
      const ctry = props.ADM0NAME || props.SOV0NAME || props.COUNTRY;
      if (ctry !== country) continue;
      const [clon, clat] = f.geometry.coordinates;
      const d = haversineKm(lat, lon, clat, clon);
      if (d < bestKm) { bestKm = d; best = { cityName, clat, clon, d }; }
    }

    if (best) {
      selectedCity = best.cityName;
      qs("selCity").textContent = `${best.cityName} (~${best.d.toFixed(0)} km)`;
      qs("cityInput").value = best.cityName;
      if (marker) map.removeLayer(marker);
      marker = L.marker([best.clat, best.clon]).addTo(map);
    } else {
      selectedCity = null;
      qs("selCity").textContent = "—";
      qs("cityInput").value = "";
      if (marker) { map.removeLayer(marker); marker = null; }
    }

    runSearch(0);
  });
}

// ---- Load facet data from Datasette ----
async function loadLibraryFacets() {
  const c = await fetchJson(`${DB}/v_countries.json?_shape=objects`);
  fillDatalist(qs("countryList"), c.rows.map(r => r.country).filter(Boolean));

  const ci = await fetchJson(`${DB}/v_cities.json?_shape=objects`);
  libraryCitySet = new Set();
  libraryCitiesByCountry = new Map();
  for (const r of ci.rows) {
    const country = r.country;
    const city = r.city;
    if (!country || !city) continue;
    libraryCitySet.add(`${country}|${city}`);
    if (!libraryCitiesByCountry.has(country)) libraryCitiesByCountry.set(country, []);
    libraryCitiesByCountry.get(country).push(city);
  }
  for (const [k, arr] of libraryCitiesByCountry) arr.sort((a,b)=>a.localeCompare(b));

  const cams = await fetchJson(`${DB}/v_cameras.json?_shape=objects`);
  fillDatalist(qs("cameraList"), cams.rows.map(r => r.camera).filter(Boolean));
}

async function main() {
  await loadLibraryFacets();
  await initMap();

  qs("countryInput").addEventListener("input", () => {
    setCityDatalistForCountry(qs("countryInput").value.trim());
  });

  qs("runSearch").addEventListener("click", () => runSearch(0));

  qs("reset").addEventListener("click", () => {
    qs("q").value = "";
    qs("countryInput").value = "";
    qs("cityInput").value = "";
    qs("cameraInput").value = "";
    qs("mediaType").value = "";
    qs("dateFrom").value = "";
    qs("dateTo").value = "";
    selectedCountry = null;
    selectedCity = null;
    qs("selCountry").textContent = "—";
    qs("selCity").textContent = "—";
    runSearch(0);
  });

  qs("prev").addEventListener("click", () => { if (currentPage > 0) runSearch(currentPage - 1); });
  qs("next").addEventListener("click", () => runSearch(currentPage + 1));

  runSearch(0);
}

main().catch(err => {
  console.error(err);
  alert("UI error: " + err.message);
});