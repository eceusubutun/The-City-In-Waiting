# ==============================================================
# s04_case_json.py - fill the case JSON from the category template + save + compare with the manual JSON
# Part of auto_case (split from auto_case.py v0.25, 20 Nov 2026). Run through main.py.
# uses (from earlier steps): BOUNDARY_FILE, CASE_ID, MANUAL_JSON, OUT_DIR, SITE_NAME, SLUG,
#                            TEMPLATE_JSON, admin, area, lat, lon, osm_matches, shape_index
# makes (used by later steps): CASE, case_path
# shared functions (to_crs, overpass, zonal, log ...) are in helpers.py
# ==============================================================
# --- 4. fill the case JSON from the category template ---
with open(TEMPLATE_JSON, encoding="utf-8") as fh:
    CASE = copy.deepcopy(json.load(fh)["case_template"])

CASE["case"]["id"] = CASE_ID
CASE["case"]["name"] = SITE_NAME
CASE["case"]["city"] = admin.get("8", "")
CASE["case"]["country"] = admin.get("2", "")
CASE["case"]["coordinates"] = {"lat": round(lat, 6), "lon": round(lon, 6)}
CASE["case"]["sources"] = [{
    "id": "S1", "title": "OpenStreetMap (Overpass API, is_in query)",
    "author_or_publisher": "OpenStreetMap contributors",
    "date": datetime.now().strftime("%Y-%m-%d"), "type": "dataset",
    "url": "https://www.openstreetmap.org"}]

CASE["site"]["area_m2"] = round(area)
CASE["site"]["shape_index"] = round(shape_index, 2)

CASE["provenance"]["case"]["tag"] = "source_documented"
CASE["provenance"]["case"]["field_notes"] = {
    "coordinates": "centroid of boundary file, script",
    "city, country": "OSM admin areas containing the centre (S1)"}
CASE["provenance"]["site"]["tag"] = "source_documented"
CASE["provenance"]["site"]["field_notes"] = {
    "area_m2, shape_index": "computed by script from " + os.path.basename(BOUNDARY_FILE)}

# extra information that has no field in the template (kept for later steps)
AUTO_INFO = {"admin_areas": admin, "osm_matches": osm_matches,
             "boundary_file": BOUNDARY_FILE, "run": OUT_DIR}


# --- 5. save + compare with the manual JSON (test only) ---
case_path = os.path.join(OUT_DIR, SLUG + ".json")
with open(case_path, "w", encoding="utf-8") as fh:
    json.dump(CASE, fh, ensure_ascii=False, indent=2)
with open(os.path.join(OUT_DIR, "auto_info.json"), "w", encoding="utf-8") as fh:
    json.dump(AUTO_INFO, fh, ensure_ascii=False, indent=2)
print("Saved:", case_path)

if MANUAL_JSON and os.path.exists(MANUAL_JSON):
    with open(MANUAL_JSON, encoding="utf-8") as fh:
        M = json.load(fh)
    checks = [("case.city", M["case"]["city"], CASE["case"]["city"]),
              ("case.country", M["case"]["country"], CASE["case"]["country"]),
              ("case.lat", M["case"]["coordinates"]["lat"], CASE["case"]["coordinates"]["lat"]),
              ("case.lon", M["case"]["coordinates"]["lon"], CASE["case"]["coordinates"]["lon"]),
              ("site.area_m2", M["site"]["area_m2"], CASE["site"]["area_m2"]),
              ("site.shape_index", M["site"]["shape_index"], CASE["site"]["shape_index"])]
    print("\nfield | manual | script")
    for name, m, s in checks:
        print(name, "|", m, "|", s)
