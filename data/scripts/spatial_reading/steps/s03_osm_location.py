# ==============================================================
# s03_osm_location.py - OSM: which named (admin) areas contain the site centre
# Part of auto_case (split from auto_case.py v0.25, 20 Nov 2026). Run through main.py.
# uses (from earlier steps): SITE_DIR, SLUG, lat, lon
# makes (used by later steps): admin, osm, osm_matches
# shared functions (to_crs, overpass, zonal, log ...) are in helpers.py
# ==============================================================
# --- 3. OSM: which named areas contain the site centre? (cached) ---
import time


osm_cache = os.path.join(SITE_DIR, "osm_is_in.json")
if os.path.exists(osm_cache):
    with open(osm_cache, encoding="utf-8") as fh:
        osm = json.load(fh)
    print("OSM areas read from cache")
else:
    osm = overpass(f"[out:json][timeout:25];is_in({lat},{lon})->.a;"
                   "(way(pivot.a);relation(pivot.a););out tags;")
    with open(osm_cache, "w", encoding="utf-8") as fh:
        json.dump(osm, fh, ensure_ascii=False)
    print("OSM areas downloaded")

admin = {}        # admin_level -> English name if available
osm_matches = []  # OSM objects named like the site
for el in osm["elements"]:
    t = el.get("tags", {})
    if t.get("boundary") == "administrative" and "admin_level" in t:
        admin[t["admin_level"]] = t.get("name:en", t.get("name"))
    if slugify(t.get("name", "")) == SLUG:
        osm_matches.append({"osm": f"{el['type']}/{el['id']}",
                            "wikidata": t.get("wikidata")})

print("Admin areas:", admin)
print("OSM objects with the site name:", osm_matches)
