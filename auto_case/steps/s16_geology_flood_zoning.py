# ==============================================================
# s16_geology_flood_zoning.py - geology, flood zones, zoning (point queries to public services)
# Part of auto_case (split from auto_case.py v0.25, 20 Nov 2026). Run through main.py.
# uses (from earlier steps): CASE, CRS, OUT_DIR, QgsPointXY, SCRIPT_NOTE, SITE_DIR, area,
#                            cad_text, case_path, site_geom
# makes (used by later steps): soil
# shared functions (to_crs, overpass, zonal, log ...) are in helpers.py
# ==============================================================
# --- 16. geology, flood zones, zoning (point queries to public services) ---
import re
log("\nstep 16: geology, flood zones, zoning")

svc_cache_path = os.path.join(SITE_DIR, "services_cache.json")
SVC = {}
if os.path.exists(svc_cache_path):
    with open(svc_cache_path, encoding="utf-8") as fh:
        SVC = json.load(fh)
def svc_save():
    with open(svc_cache_path, "w", encoding="utf-8") as fh:
        json.dump(SVC, fh, ensure_ascii=False)

PTS = sample_points(site_geom)
log("sample points inside the site:", len(PTS))

# 16a. geology: ICGC 1:50,000 geological units at the sample points
GEO_WMS = "https://geoserveis.icgc.cat/servei/catalunya/geologia-territorial/wms"
if "geology" not in SVC:
    SVC["geology"] = []
    for p in PTS:
        js = json.loads(wms_feature_info(GEO_WMS, "unitats-geologiques-50000", p.x(), p.y(),
                                         "application/geo+json"))
        props = js["features"][0]["properties"] if js.get("features") else {}
        SVC["geology"].append({"code": props.get("Codi"), "description": props.get("Descripcio")})
    svc_save()
units = {}
for u in SVC["geology"]:
    if u["code"]:
        units.setdefault(u["code"], {"n": 0, "description": u["description"]})["n"] += 1
main_code = max(units, key=lambda k: units[k]["n"]) if units else None
main_desc = (units[main_code]["description"] or "") if main_code else ""

# soil_type: first lithology word in the unit description (Catalan); permeability from soil_type
LITHO = [("made_ground", ("reblert", "antròpic", "antropic")),
         ("gravel", ("grava", "graves", "còdol", "codol", "conglomerat")),
         ("sand", ("sorra", "sorres", "arena", "arenes")),
         ("silt", ("llim", "llims", "lim", "loess")),
         ("clay", ("argila", "argiles", "lutita", "lutites", "marga", "margues")),
         ("rock", ("calcàri", "calcari", "granit", "pissarr", "gres", "dolomi", "esquist", "basalt"))]
low = main_desc.lower()
first = None
for soil, words in LITHO:
    for w in words:
        k = low.find(w)
        if k >= 0 and (first is None or k < first[1]):
            first = (soil, k)
soil_type = first[0] if first else "unknown"
# decision Ece (16 Nov 2026): clay together with silt / loess in the same unit -> silt (mixed fine soil)
has_clay = any(w in low for w in dict(LITHO)["clay"])
has_silt = any(w in low for w in dict(LITHO)["silt"])
if has_clay and has_silt:
    soil_type = "silt"
PERM = {"gravel": "permeable", "sand": "permeable", "silt": "semi_permeable",
        "clay": "impermeable", "rock": "unknown", "made_ground": "unknown", "unknown": "unknown"}
permeability = PERM[soil_type]
CASE["site"]["geology"] = {"soil_type": soil_type, "permeability": permeability}
CASE["provenance"]["site"]["field_notes"]["geology"] = (
    f"ICGC geological map 1:50,000 (unitats-geologiques-50000), {len(PTS)} points inside the site; "
    f"units {', '.join(f'{k} x{v['n']}' for k, v in units.items())}; main unit {main_code}: "
    f"'{main_desc[:160]}'; soil_type = first lithology named in the description, but clay + silt/loess "
    "together -> silt (decision Ece); permeability from "
    "soil_type (gravel/sand permeable, silt semi_permeable, clay impermeable); " + SCRIPT_NOTE)
log("geology | manual: silt / semi_permeable | script:", soil_type, "/", permeability)
log("   units:", {k: v["n"] for k, v in units.items()}, "| main:", main_code, "|", main_desc[:200])

# 16b. flood zones (SNCZI via IDEE INSPIRE WMS): raster value at sample points, the site edge
#      (25 m outside) and a test point in the Llobregat river bed (to read what 'flooded' looks like)
FLOOD_WMS = "https://servicios.idee.es/wms-inspire/riesgos-naturales/inundaciones"
FLOOD_LAYERS = {"T10": "NZ.Flood.FluvialT10", "T100": "NZ.Flood.FluvialT100",
                "T500": "NZ.Flood.FluvialT500", "marine_T100": "NZ.Flood.MarinaT100"}
def flood_value(layer, x, y):
    txt = wms_feature_info(FLOOD_WMS, layer, x, y, "text/plain")
    m = re.search(r"GRAY_INDEX\s*=\s*([-0-9.Ee+]+)", txt)
    return float(m.group(1)) if m else None
import re
edge_pts = [QgsPointXY(v.x(), v.y()) for v in site_geom.buffer(25, 4).vertices()][::max(1, len(list(site_geom.buffer(25, 4).vertices())) // 8)]
test_pt = to_crs(QgsGeometry.fromPointXY(QgsPointXY(2.0533, 41.3466)), "EPSG:4326", CRS).asPoint()
if "flood" not in SVC:
    SVC["flood"] = {}
    for key, layer in FLOOD_LAYERS.items():
        SVC["flood"][key] = {
            "site": [flood_value(layer, p.x(), p.y()) for p in PTS],
            "edge": [flood_value(layer, p.x(), p.y()) for p in edge_pts],
            "test_llobregat": flood_value(layer, test_pt.x(), test_pt.y())}
    svc_save()
for key, v in SVC["flood"].items():
    log(f"flood {key} | site values: {sorted(set(v['site']))} | edge: {sorted(set(v['edge']))} "
        f"| Llobregat test: {v['test_llobregat']}")

# 16c. zoning: MUC qualifications (Diputació de Barcelona ArcGIS service, Jan 2023) intersecting the site
MUC = "https://gissrv.diba.cat/arcgis/rest/services/CARTOBASE/MUC/MapServer"
if "zoning" not in SVC:
    mg = QgsGeometry(site_geom)
    mg.convertToMultiType()
    rings = [[[pt.x(), pt.y()] for pt in ring] for poly in mg.asMultiPolygon() for ring in poly]
    body = urllib.parse.urlencode({
        "geometry": json.dumps({"rings": rings, "spatialReference": {"wkid": 25831}}),
        "geometryType": "esriGeometryPolygon", "inSR": 25831, "outSR": 25831,
        "spatialRel": "esriSpatialRelIntersects", "outFields": "*", "returnGeometry": "true",
        "f": "json"}).encode()
    SVC["zoning"] = json.loads(http_get(MUC + "/1/query", data=body, timeout=120))
    svc_save()
zone_area = {}
zone_desc = {}
def esri_polygon(rings):
    # Esri JSON rings: clockwise = outer ring, counter-clockwise = hole
    outer, holes = [], []
    for r in rings:
        signed = sum(r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1] for i in range(len(r) - 1))
        poly = QgsGeometry.fromPolygonXY([[QgsPointXY(x, y) for x, y in r]])
        (outer if signed < 0 else holes).append(poly)
    g = QgsGeometry.unaryUnion(outer) if outer else QgsGeometry()
    for h in holes:
        g = g.difference(h)
    return g

for f in SVC["zoning"].get("features", []):
    g = esri_polygon(f["geometry"]["rings"])
    a = g.intersection(site_geom).area()
    if a <= 0:
        continue
    code = f["attributes"].get("C_QUAL_MUC")
    zone_area[code] = zone_area.get(code, 0) + a
    zone_desc[code] = f["attributes"].get("D_QUAL_AJT")
zoning_text = "MUC (Jan 2023): " + "; ".join(
    f"{c} {zone_desc[c]} {round(a / area * 100)} %"
    for c, a in sorted(zone_area.items(), key=lambda kv: -kv[1]) if a / area >= 0.01)
if SVC["zoning"].get("features"):
    log("MUC fields:", list(SVC["zoning"]["features"][0]["attributes"].keys()),
        "| features:", len(SVC["zoning"]["features"]))
log("after.zoning | manual: MPGM Can Batlló–Magòria 2017, qualifications 5, 6b, 6b/p, 6b/18, 7b, 18, 18/HS"
    " | script:", zoning_text)
CASE["after"]["zoning"] = zoning_text
CASE["provenance"]["after"]["field_notes"]["zoning"] = (
    "Mapa Urbanístic de Catalunya, qualification layer (Diputació de Barcelona ArcGIS service, "
    "updated Jan 2023); share of site area per MUC code (>= 1 %); municipal plan codes not included; "
    "before.zoning (plan in force at vacancy) stays manual; " + SCRIPT_NOTE)
CASE["case"]["sources"] += [
    {"id": "S8", "title": "Mapa geològic de Catalunya 1:50.000 (WMS Geologia territorial)",
     "author_or_publisher": "ICGC", "date": "2026", "type": "dataset", "url": GEO_WMS},
    {"id": "S9", "title": "Mapa Urbanístic de Catalunya (MUC), qualificació",
     "author_or_publisher": "Generalitat de Catalunya / Diputació de Barcelona", "date": "2023-01",
     "type": "plan", "url": MUC}]
with open(case_path, "w", encoding="utf-8") as fh:
    json.dump(CASE, fh, ensure_ascii=False, indent=2)

# 16b (rule). flood_risk from SNCZI depth rasters (read on 16 Nov 2026 with a Llobregat test point:
# flooded cells carry a water depth in m, e.g. 0.36 at T100; 999 and very negative values = not flooded)
def flooded(v):
    return v is not None and 0 <= v < 900
fl = SVC["flood"]["T100"]
site_in = any(flooded(v) for v in fl["site"]) or any(flooded(v) for v in SVC["flood"]["marine_T100"]["site"])
edge_in = any(flooded(v) for v in fl["edge"]) or any(flooded(v) for v in SVC["flood"]["marine_T100"]["edge"])
flood_risk = "inside_flood_zone" if site_in else "edge_of_flood_zone" if edge_in else "outside"
CASE["site"]["flood_risk"] = flood_risk
CASE["site"]["flood_return_period"] = "T100"
CASE["provenance"]["site"]["field_notes"]["flood_risk"] = (
    f"SNCZI flood zones via IDEE INSPIRE WMS (fluvial and marine T100), {len(PTS)} points inside the site "
    f"and {len(edge_pts)} points 25 m outside; flooded = water depth value 0-900 (999 / no-data = not "
    "flooded); covers mapped river and coastal reaches only, not urban runoff; " + SCRIPT_NOTE)
CASE["case"]["sources"].append(
    {"id": "S10", "title": "SNCZI flood zones (IDEE INSPIRE WMS riesgos-naturales/inundaciones)",
     "author_or_publisher": "MITECO / IGN", "date": datetime.now().strftime("%Y-%m-%d"),
     "type": "dataset", "url": FLOOD_WMS})
with open(case_path, "w", encoding="utf-8") as fh:
    json.dump(CASE, fh, ensure_ascii=False, indent=2)
log("flood_risk | manual: unknown (viewer did not load) | script:", flood_risk, "(T100)")

with open(os.path.join(OUT_DIR, "comparison.csv"), "a", newline="", encoding="utf-8") as fh:
    wr = csv.writer(fh)
    wr.writerow(["", "cadastral_ref", "79021 (parcels 61-64, 73-77, 87)", cad_text, ""])
    wr.writerow(["", "geology", "silt / semi_permeable", f"{soil_type} / {permeability}", ""])
    wr.writerow(["", "flood_risk", "unknown", flood_risk, ""])
    wr.writerow(["", "after.zoning", "MPGM 2017: 5, 6b, 6b/p, 6b/18, 7b, 18, 18/HS", zoning_text, ""])

for block in ("case", "site", "before", "after"):
    vals = list(leaves({k: v for k, v in CASE[block].items() if k != "sources"}))
    filled = sum(1 for v in vals if v not in ("", None, []))
    log(f"FINAL {block}: {filled} of {len(vals)} fields filled by the script")
log("Saved:", case_path)
