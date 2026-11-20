# ==============================================================
# s11_connectivity_water.py - connectivity (bus, metro, main road, services, centre) + water proximity
# Part of auto_case (split from auto_case.py v0.25, 20 Nov 2026). Run through main.py.
# uses (from earlier steps): CASE, CITY_CENTRE, CRS, OUT_DIR, QgsPointXY, SCRIPT_NOTE, SITE_DIR,
#                            case_path, lat, lon, site_geom
# makes (used by later steps): CONN, CTX, parts, sv, water_m
# shared functions (to_crs, overpass, zonal, log ...) are in helpers.py
# ==============================================================
# --- 11. connectivity + water proximity (OSM, straight-line from the site edge) ---
CONTEXT_QUERIES = {
    # name: (Overpass filter, radius in m around the site centre)
    "bus_stop":   ('node["highway"="bus_stop"]', 1000),
    "rail_metro": ('nwr["railway"="station"]', 3000),
    "main_road":  ('way["highway"~"^(motorway|trunk|primary)$"]', 1500),
    "services":   ('nwr["shop"~"^(supermarket|convenience|bakery|greengrocer|butcher)$"];'
                   'nwr["amenity"~"^(pharmacy|school|kindergarten|doctors|clinic|marketplace|library|post_office)$"]', 1000),
    "water":      ('way["natural"="coastline"];nwr["natural"="water"];'
                   'way["waterway"~"^(river|canal)$"]', 10000),
    "city_centre": ('node["place"="city"]', 30000),
}

ctx_cache = os.path.join(SITE_DIR, "osm_context.json")
if os.path.exists(ctx_cache):
    with open(ctx_cache, encoding="utf-8") as fh:
        CTX = json.load(fh)
    log("OSM context read from cache")
else:
    CTX = {}
    for key, (flt, radius) in CONTEXT_QUERIES.items():
        parts = "".join(f"{p}(around:{radius},{lat},{lon});" for p in flt.split(";") if p)
        CTX[key] = overpass(f"[out:json][timeout:90];({parts});out geom;")["elements"]
        log("OSM", key, "objects:", len(CTX[key]))
        time.sleep(2)                                  # be gentle with the server
    with open(ctx_cache, "w", encoding="utf-8") as fh:
        json.dump(CTX, fh, ensure_ascii=False)

def nearest(key, skip=None):
    # returns (distance in m, OSM element) of the closest object
    best = (None, None)
    for el in CTX.get(key, []):
        if skip and skip(el):
            continue
        g = osm_geom(el)
        if g.isEmpty():
            continue
        d = g.distance(site_geom)
        if best[0] is None or d < best[0]:
            best = (d, el)
    return best

def not_surface_water(el):
    # keep: sea (coastline), rivers / canals, lakes and reservoirs
    # skip: fountains, ornamental ponds, culverted (buried) streams
    t = el.get("tags", {})
    if t.get("amenity") == "fountain" or t.get("tunnel") in ("culvert", "yes"):
        return True
    if t.get("waterway") == "canal":
        return True                                   # not in the definition (river, stream, sea, lake)
    if t.get("natural") == "water":
        return t.get("water") not in ("river", "lake", "reservoir", "lagoon")
    return False

def not_supermarket(el):
    # local services = supermarket (decision Ece, 16 Nov 2026); inside the site = not "nearby"
    t = el.get("tags", {})
    return t.get("shop") != "supermarket" or osm_geom(el).within(site_geom)

def not_metro(el):
    # rail_metro = metro stations only (decision Ece, 16 Nov 2026): station=subway, not FGC
    t = el.get("tags", {})
    operator = (t.get("operator", "") + " " + t.get("network", "")).upper()
    return t.get("station") != "subway" or "FGC" in operator or "FERROCARRILS" in operator

CONN = {}
for key, field, skip in (("bus_stop", "nearest_bus_stop_m", None),
                         ("rail_metro", "nearest_rail_metro_m", not_metro),
                         ("main_road", "nearest_main_road_m", None),
                         ("services", "nearest_local_services_m", not_supermarket)):
    d, el = nearest(key, skip)
    CONN[field] = None if d is None else round(d)
    log(field, CONN[field], "-", label(el))

centre_pt = to_crs(QgsGeometry.fromPointXY(QgsPointXY(CITY_CENTRE[2], CITY_CENTRE[1])),
                   "EPSG:4326", CRS)
CONN["distance_to_centre_km"] = round(centre_pt.distance(site_geom) / 1000, 2)
log("distance_to_centre_km", CONN["distance_to_centre_km"], "-", CITY_CENTRE[0])

d, el = nearest("water", not_surface_water)
water_m = None if d is None else round(d)
log("water_proximity_m", water_m, "-", label(el))

CASE["site"]["connectivity"] = CONN
CASE["site"]["water_proximity_m"] = water_m
CASE["provenance"]["site"]["field_notes"]["connectivity"] = (
    "OSM, straight line from site edge: bus = highway=bus_stop; rail/metro = metro stations "
    "(railway=station, station=subway, FGC excluded); main road = motorway/trunk/primary, "
    "measured to the road centre line; local services = nearest supermarket outside the site; "
    "centre = " + CITY_CENTRE[0] + "; " + SCRIPT_NOTE)
CASE["provenance"]["site"]["field_notes"]["water_proximity_m"] = (
    "OSM coastline (sea), rivers, lakes, reservoirs; canals, fountains, ponds and culverted streams excluded; " + SCRIPT_NOTE)

with open(case_path, "w", encoding="utf-8") as fh:
    json.dump(CASE, fh, ensure_ascii=False, indent=2)

MANUAL_CONN = {"nearest_bus_stop_m": 14, "nearest_rail_metro_m": 755, "nearest_main_road_m": 0,
               "distance_to_centre_km": 3.34, "nearest_local_services_m": 73}
log("\nfield | manual (Google Maps) | script (OSM)")
for k, m in MANUAL_CONN.items():
    log(k, "|", m, "|", CONN[k])
log("water_proximity_m |", 3000, "|", water_m)
filled = sum(1 for v in leaves(CASE["site"]) if v not in ("", None, []))
log("site:", filled, "of", len(list(leaves(CASE["site"]))), "fields filled by the script")

# add the connectivity rows to comparison.csv
with open(os.path.join(OUT_DIR, "comparison.csv"), "a", newline="", encoding="utf-8") as fh:
    wr = csv.writer(fh)
    for k, m in list(MANUAL_CONN.items()) + [("water_proximity_m", 3000)]:
        sv = water_m if k == "water_proximity_m" else CONN[k]
        wr.writerow(["", k, m, sv, None if sv is None else round(sv - m, 3)])
