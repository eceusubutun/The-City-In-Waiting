# ==============================================================
# s13_rules_site.py - rules: parcel_shape, location, urban_network, biodiversity
# Part of auto_case (split from auto_case.py v0.25, 20 Nov 2026). Run through main.py.
# uses (from earlier steps): CASE, CONN, CRS, CTX, OUT_DIR, R, SCRIPT_NOTE, SITE_DIR,
#                            YEAR_AFTER, YEAR_BEFORE, case_path, lat, lon, osm, shape_index,
#                            site_geom, water_m
# makes (used by later steps): muni_area_km2, parcel_shape, rc_get, urban_network
# shared functions (to_crs, overpass, zonal, log ...) are in helpers.py
# ==============================================================
# --- 13. rule-based fields (rules decided by Ece, 16 Nov 2026) ---
# parcel_shape, location, urban_network, after.biodiversity
from osgeo import ogr
log("\nstep 13: rule-based fields")

rules_cache = os.path.join(SITE_DIR, "osm_rules_context.json")
RC = {}
if os.path.exists(rules_cache):
    with open(rules_cache, encoding="utf-8") as fh:
        RC = json.load(fh)

def rc_get(key, fetch):
    # download one item only if it is not cached yet; save the cache after each item
    if key not in RC:
        log("downloading", key)
        RC[key] = fetch()
        with open(rules_cache, "w", encoding="utf-8") as fh:
            json.dump(RC, fh, ensure_ascii=False)
    else:
        log(key, "read from cache")
    return RC[key]

admin8_id = next((el["id"] for el in osm["elements"]
                  if el.get("tags", {}).get("admin_level") == "8"
                  and el.get("tags", {}).get("boundary") == "administrative"), None)
rc_get("municipality", lambda: nominatim_polygon(f"R{admin8_id}"))
rc_get("rail_yard", lambda: overpass(f'[out:json][timeout:60];'
                                     f'way["landuse"="railway"](around:100,{lat},{lon});out geom;')["elements"])

def area_polygon(el):
    # closed way -> polygon in metres (for areas)
    g = osm_polygon(el)
    return QgsGeometry() if g.isEmpty() else to_crs(g, "EPSG:4326", CRS)

RULES = {}

# 13a. parcel_shape: linear if long side >= 4 x short side (oriented bounding box);
#      else regular if shape_index <= 1.2, irregular above
obb = site_geom.orientedMinimumBoundingBox()          # (geometry, area, angle, width, height)
long_side, short_side = max(obb[3], obb[4]), min(obb[3], obb[4])
elong = long_side / short_side if short_side else None
if elong and elong >= 4:
    parcel_shape = "linear"
elif shape_index <= 1.2:
    parcel_shape = "regular"
else:
    parcel_shape = "irregular"
RULES["parcel_shape"] = (parcel_shape, f"shape_index {round(shape_index, 2)}, long/short side {round(elong, 2)}")

# 13b. location: distance to the centre relative to the city's size.
#      R = radius of a circle with the municipality's area; centre < 0.25 R,
#      inner_city 0.25-0.75 R, periphery > 0.75 R; peri_urban = periphery with
#      non-urban land (forest, farmland, scrub ...) within 500 m of the site
muni_wkt = ogr.CreateGeometryFromJson(json.dumps(RC["municipality"]["features"][0]["geometry"])).ExportToWkt()
muni = to_crs(QgsGeometry.fromWkt(muni_wkt), "EPSG:4326", CRS)
muni_area_km2 = muni.area() / 1e6
R_km = (muni_area_km2 / math.pi) ** 0.5
rel_d = CONN["distance_to_centre_km"] / R_km
non_urban_500 = None                       # only needed (and downloaded) beyond 0.75 R
if rel_d < 0.25:
    location = "centre"
elif rel_d <= 0.75:
    location = "inner_city"
else:
    try:
        nu = rc_get("non_urban", lambda: overpass(
            f'[out:json][timeout:60];('
            f'way["landuse"~"^(forest|farmland|meadow|orchard|vineyard|farmyard)$"](around:1000,{lat},{lon});'
            f'way["natural"~"^(wood|scrub|heath|grassland)$"](around:1000,{lat},{lon}););out geom;')["elements"])
        non_urban_500 = [el for el in nu if osm_geom(el).distance(site_geom) <= 500]
        location = "peri_urban" if non_urban_500 else "periphery"
    except Exception as e:
        log("non-urban land not available:", e)
        location = "periphery"             # peri_urban check could not be made (noted below)
RULES["location"] = (location, f"{CONN['distance_to_centre_km']} km / R {round(R_km, 2)} km "
                               f"(municipality {round(muni_area_km2, 1)} km2) = {round(rel_d, 2)}; "
                               f"non-urban land within 500 m: {'not needed' if non_urban_500 is None else len(non_urban_500)}")

# 13c. urban_network: waterfront if water <= 100 m; transport_hub if a rail yard (>= 1 ha)
#      or an above-ground train station <= 100 m; isolated if built-up share of the ring < 20 %;
#      else embedded
def is_train_station_above_ground(el):
    t = el.get("tags", {})
    if t.get("station") in ("subway", "light_rail") or t.get("railway") != "station":
        return False
    underground = t.get("location") == "underground" or str(t.get("level", "0")).startswith("-")
    return t.get("train") == "yes" and not underground

near_station = [el for el in CTX.get("rail_metro", [])
                if is_train_station_above_ground(el) and osm_geom(el).distance(site_geom) <= 100]
near_yard = [el for el in RC["rail_yard"]
             if area_polygon(el).area() >= 10000 and area_polygon(el).distance(site_geom) <= 100]
built_up_before = R[YEAR_BEFORE]["surrounding_built_up_pct"]
if water_m is not None and water_m <= 100:
    urban_network = "waterfront"
elif near_station or near_yard:
    urban_network = "transport_hub"
elif built_up_before < 20:
    urban_network = "isolated"
else:
    urban_network = "embedded"
RULES["urban_network"] = (urban_network, f"water {water_m} m; above-ground train stations <= 100 m: "
                                         f"{len(near_station)}; rail yards <= 100 m: {len(near_yard)}; "
                                         f"built-up ring {YEAR_BEFORE}: {built_up_before} %")

# 13d. after.biodiversity: change in vegetated share of the site (+/- 5 points)
dv = R[YEAR_AFTER]["vegetated_pct"] - R[YEAR_BEFORE]["vegetated_pct"]
biodiversity = "increased" if dv >= 5 else "decreased" if dv <= -5 else "unchanged"
RULES["biodiversity"] = (biodiversity, f"vegetated share {R[YEAR_BEFORE]['vegetated_pct']} -> "
                                       f"{R[YEAR_AFTER]['vegetated_pct']} % ({round(dv, 1)} pts); "
                                       "'replaced' not detectable; WMS NDVI not fully comparable across years")

CASE["site"]["parcel_shape"] = parcel_shape
CASE["site"]["location"] = location
CASE["site"]["urban_network"] = urban_network
CASE["after"]["biodiversity"] = biodiversity
for field, (value, why) in RULES.items():
    block = "after" if field == "biodiversity" else "site"
    CASE["provenance"][block]["field_notes"][field] = f"rule: {why}; " + SCRIPT_NOTE

with open(case_path, "w", encoding="utf-8") as fh:
    json.dump(CASE, fh, ensure_ascii=False, indent=2)

MANUAL_RULES = {"parcel_shape": "regular", "location": "inner_city",
                "urban_network": "embedded", "biodiversity": "increased"}
log("\nfield | manual | script | why")
with open(os.path.join(OUT_DIR, "comparison.csv"), "a", newline="", encoding="utf-8") as fh:
    wr = csv.writer(fh)
    for field, (value, why) in RULES.items():
        log(field, "|", MANUAL_RULES[field], "|", value, "|", why)
        wr.writerow(["", field, MANUAL_RULES[field], value, "same" if value == MANUAL_RULES[field] else "different"])

for block in ("case", "site", "before", "after"):
    vals = list(leaves({k: v for k, v in CASE[block].items() if k != "sources"}))
    filled = sum(1 for v in vals if v not in ("", None, []))
    log(f"FINAL {block}: {filled} of {len(vals)} fields filled by the script")
