# ==============================================================
# s18_rules_layout_surface.py - rules: enclosure, site_layout, surface_substrate, infrastructure, reclaimed_area_m2
# Part of auto_case (split from auto_case.py v0.25, 20 Nov 2026). Run through main.py.
# uses (from earlier steps): CASE, CONN, CRS, DTM_FILE, OUT_DIR, R, SCRIPT_NOTE, YEAR_AFTER,
#                            YEAR_BEFORE, case_path, ndsm, parcel_shape, rc_get, site_geom,
#                            urban_network, veg2
# makes (used by later steps): -
# shared functions (to_crs, overpass, zonal, log ...) are in helpers.py
# ==============================================================
# --- 18. more rules (decided by Ece, 16 Nov 2026): enclosure, site_layout, surface_substrate,
#         infrastructure, reclaimed_area_m2 ---
log("\nstep 18: enclosure, site_layout, surface_substrate, infrastructure, reclaimed area")
from qgis.core import QgsWkbTypes
RULES3 = {}

# OSM inside the site: streets/paths, walls/fences, construction land, surface tags.
# 'before' uses the OSM database as it was on 1 June of the before year (Overpass 'attic' data);
# 'after' uses OSM today.
bb = to_crs(site_geom.buffer(10, 4), CRS, "EPSG:4326").boundingBox()
BBOX = f"{bb.yMinimum()},{bb.xMinimum()},{bb.yMaximum()},{bb.xMaximum()}"
SITE_Q = (f'(way["highway"]({BBOX});way["barrier"~"^(wall|fence|retaining_wall)$"]({BBOX});'
          f'nwr["landuse"~"^(construction|brownfield|greenfield)$"]({BBOX});'
          f'way["building"="construction"]({BBOX});way["surface"]({BBOX}););out geom;')
OSM_SITE = {}
for block, year in (("before", YEAR_BEFORE), ("after", YEAR_AFTER)):
    date = f'[date:"{year}-06-01T00:00:00Z"]' if block == "before" else ""
    try:
        OSM_SITE[block] = rc_get(f"site_inside_{block}", lambda: overpass(
            f"[out:json][timeout:90]{date};" + SITE_Q)["elements"])
    except Exception as e:
        log("OSM inside the site not available for", block, "-", e)
        OSM_SITE[block] = None
if OSM_SITE["before"] is None:                     # attic data refused: use today's OSM, noted below
    OSM_SITE["before"] = OSM_SITE["after"] or []
    attic_note = "OSM of today (historic OSM not available)"
else:
    attic_note = f"OSM as on 1 June {YEAR_BEFORE}"
OSM_SITE["after"] = OSM_SITE["after"] or []

def lines_of(els, test):
    gs = [osm_geom(el) for el in els if test(el.get("tags", {}))]
    return [g for g in gs if not g.isEmpty()]

PUBLIC_WAYS = ("primary", "secondary", "tertiary", "residential", "unclassified", "living_street",
               "pedestrian", "footway", "path", "cycleway", "steps")
def is_public_way(t):
    return t.get("highway") in PUBLIC_WAYS and t.get("access") not in ("private", "no")

# 18a. enclosure: share of the boundary closed by something >= 1.5 m high that is not vegetation
#      (2 m height rasters, 3 x 3 window around a point every 2 m), or by an OSM wall / fence within 3 m.
#      >= 80 % -> walled (fenced if OSM fences close more of it than heights + walls), 20-80 % -> partly_enclosed,
#      < 20 % -> open
gt = gdal.Open(DTM_FILE).GetGeoTransform()     # 'ref' is reused as a name in step 15
bnd = QgsGeometry(site_geom.constGet().boundary().clone())
perim = bnd.length()
pts = [bnd.interpolate(d).asPoint() for d in np.arange(0, perim, 2.0)]

def closed_by_height(year, x, y):
    col, row = int((x - gt[0]) / gt[1]), int((y - gt[3]) / gt[5])
    nd = ndsm[year][max(row - 1, 0):row + 2, max(col - 1, 0):col + 2]
    vg = veg2[year][max(row - 1, 0):row + 2, max(col - 1, 0):col + 2]
    hit = (nd >= 1.5) & (vg == 0)
    return bool(np.nansum(hit))

ENCL = {}
for block, year in (("before", YEAR_BEFORE), ("after", YEAR_AFTER)):
    els = OSM_SITE[block]
    walls = lines_of(els, lambda t: t.get("barrier") in ("wall", "retaining_wall"))
    fences = lines_of(els, lambda t: t.get("barrier") == "fence")
    wall_zone = QgsGeometry.unaryUnion([g.buffer(3, 4) for g in walls]) if walls else QgsGeometry()
    fence_zone = QgsGeometry.unaryUnion([g.buffer(3, 4) for g in fences]) if fences else QgsGeometry()
    n_h = n_w = n_f = n_closed = 0
    for pt in pts:
        pg = QgsGeometry.fromPointXY(pt)
        h = closed_by_height(year, pt.x(), pt.y())
        w = not wall_zone.isEmpty() and wall_zone.contains(pg)
        f = not fence_zone.isEmpty() and fence_zone.contains(pg)
        n_h += h; n_w += w; n_f += f
        n_closed += (h or w or f)
    pct = round(n_closed / len(pts) * 100, 1)
    if pct >= 80:
        tag = "fenced" if n_f > max(n_h, n_w) else "walled"
    elif pct >= 20:
        tag = "partly_enclosed"
    else:
        tag = "open"
    ENCL[block] = pct
    RULES3[f"{block}.enclosure"] = (tag, f"{pct} % of the boundary closed ({len(pts)} points every 2 m: "
        f"height >= 1.5 m non-vegetation {YEAR_BEFORE if block == 'before' else YEAR_AFTER} {n_h}, OSM walls {n_w}, "
        f"OSM fences {n_f}; {attic_note if block == 'before' else 'OSM today'}); fences are seldom visible in heights")

# 18b. site_layout: regular / irregular from parcel_shape (shape_index <= 1.2);
#      fragmented if public streets / paths split the site so that the largest piece holds
#      < FRAG_LARGEST_MAX of the site (paths cut a site into many small pieces, so a 'pieces >= 10 %'
#      count does not work - tested on Can Batlló 16 Nov); else obstructed if buildings >= 5 %; else clear
FRAG_LARGEST_MAX = 0.75
for block, year in (("before", YEAR_BEFORE), ("after", YEAR_AFTER)):
    ways = lines_of(OSM_SITE[block], is_public_way)
    cut = QgsGeometry.unaryUnion([g.buffer(1, 4) for g in ways]) if ways else QgsGeometry()
    rest = site_geom if cut.isEmpty() else site_geom.difference(cut)
    parts = [p for p in rest.asGeometryCollection() if p.type() == QgsWkbTypes.PolygonGeometry]
    largest = max((p.area() for p in parts), default=0) / site_geom.area()
    shape = "regular" if parcel_shape == "regular" else "irregular"
    bld = R[year]["buildings"]
    if largest < FRAG_LARGEST_MAX:
        layout = f"{shape}_fragmented"
    elif bld >= 5:
        layout = f"{shape}_obstructed"
    else:
        layout = "clear"
    RULES3[f"{block}.site_layout"] = (layout, f"parcel_shape {parcel_shape}; public streets/paths in the area "
        f"{len(ways)} ({attic_note if block == 'before' else 'OSM today'}); after cutting them: {len(parts)} pieces, "
        f"largest {round(largest * 100, 1)} % of the site (fragmented if < {int(FRAG_LARGEST_MAX * 100)} %); "
        f"buildings {bld} %")

# 18c. surface_substrate: impervious >= 10 % -> asphalt_or_concrete; bare earth + grass >= 10 % -> soil_clay;
#      after: also OSM surface tags covering >= 5 % of the site; rubble, ballast, brick, cracked concrete
#      are left for the image step
SURF_MAP = {"sand": "sand", "dirt": "soil_clay", "earth": "soil_clay", "ground": "soil_clay",
            "grass": "soil_clay", "mud": "soil_clay", "asphalt": "asphalt_or_concrete",
            "concrete": "asphalt_or_concrete", "paving_stones": "asphalt_or_concrete",
            "concrete:plates": "asphalt_or_concrete", "sett": "asphalt_or_concrete",
            "paved": "asphalt_or_concrete", "bricks": "brick", "brick": "brick"}
for block, year in (("before", YEAR_BEFORE), ("after", YEAR_AFTER)):
    r = R[year]
    subs, why = [], []
    if r["impervious_surface"] >= 10:
        subs.append("asphalt_or_concrete")
    soil = (r.get("bare_earth") or 0) + r["grass_herbaceous"]
    if soil >= 10:
        subs.append("soil_clay")
    why.append(f"impervious {r['impervious_surface']} %, bare earth + grass {round(soil, 1)} %")
    if block == "after":
        areas = {}
        for el in OSM_SITE["after"]:
            t = el.get("tags", {})
            sub = SURF_MAP.get(t.get("surface", ""))
            if not sub or el["type"] != "way":
                continue
            g = osm_polygon(el)
            if g.isEmpty():
                continue
            a = to_crs(g, "EPSG:4326", CRS).makeValid().intersection(site_geom).area()
            areas[sub] = areas.get(sub, 0) + a
        for sub, a in sorted(areas.items()):
            pct = a / site_geom.area() * 100
            why.append(f"OSM surface {sub} {round(pct, 1)} %")
            if pct >= 5 and sub not in subs:
                subs.append(sub)
    RULES3[f"{block}.surface_substrate"] = (subs, "; ".join(why) + "; finer classes need the image step")

# 18d. infrastructure: well_developed if urban_network = embedded and a main road <= 100 m;
#      none if no main road within 500 m; else partial (same rule before and after)
road = CONN["nearest_main_road_m"]
if road is None or road > 500:
    infra = "none"
elif urban_network == "embedded" and road <= 100:
    infra = "well_developed"
else:
    infra = "partial"
for block in ("before", "after"):
    RULES3[f"{block}.infrastructure"] = (infra, f"urban_network {urban_network}, nearest main road {road} m")

# 18e. after.reclaimed_area_m2: site area minus what OSM still tags today as construction,
#      brownfield, greenfield or building under construction inside the site
idle = []
for el in OSM_SITE["after"]:
    t = el.get("tags", {})
    if t.get("landuse") in ("construction", "brownfield", "greenfield") or t.get("building") == "construction":
        g = osm_polygon(el)
        if not g.isEmpty():
            idle.append(to_crs(g, "EPSG:4326", CRS).makeValid())
idle_area = QgsGeometry.unaryUnion(idle).intersection(site_geom).area() if idle else 0
reclaimed = round(site_geom.area() - idle_area)
RULES3["after.reclaimed_area_m2"] = (reclaimed, f"site {round(site_geom.area())} m2 minus {round(idle_area)} m2 "
    f"still construction / brownfield / greenfield in OSM today ({len(idle)} polygons)")

for key, (value, why) in RULES3.items():
    block, field = key.split(".")
    CASE[block][field] = value
    CASE["provenance"][block]["field_notes"][field] = f"rule: {why}; " + SCRIPT_NOTE
with open(case_path, "w", encoding="utf-8") as fh:
    json.dump(CASE, fh, ensure_ascii=False, indent=2)

MANUAL_RULES3 = {"before.enclosure": "walled", "after.enclosure": "partly_enclosed",
                 "before.site_layout": "regular_fragmented", "after.site_layout": "regular_fragmented",
                 "before.surface_substrate": ["asphalt_or_concrete"],
                 "after.surface_substrate": ["asphalt_or_concrete", "soil_clay", "sand"],
                 "before.infrastructure": "well_developed", "after.infrastructure": "well_developed",
                 "after.reclaimed_area_m2": 50277}
log("\nfield | manual | script | why")
with open(os.path.join(OUT_DIR, "comparison.csv"), "a", newline="", encoding="utf-8") as fh:
    wr = csv.writer(fh)
    for key, (value, why) in RULES3.items():
        m = MANUAL_RULES3.get(key)
        same = (sorted(m) == sorted(value)) if isinstance(m, list) else (m == value)
        log(key, "|", m, "|", value, "|", why)
        wr.writerow(["", key, json.dumps(m, ensure_ascii=False), json.dumps(value, ensure_ascii=False),
                     "same" if same else "different"])

for block in ("case", "site", "before", "after"):
    vals = list(leaves({k: v for k, v in CASE[block].items() if k != "sources"}))
    filled = sum(1 for v in vals if v not in ("", None, []))
    log(f"FINAL {block}: {filled} of {len(vals)} fields filled by the script")
log("Saved:", case_path)
