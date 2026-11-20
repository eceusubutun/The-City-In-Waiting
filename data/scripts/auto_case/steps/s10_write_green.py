# ==============================================================
# s10_write_green.py - write vegetation + green spaces into the case JSON, comparison table
# Part of auto_case (split from auto_case.py v0.25, 20 Nov 2026). Run through main.py.
# uses (from earlier steps): BUFFER_M, CASE, IRC_LAYERS, MANUAL_NDVI, MANUAL_PARKS, OUT_DIR,
#                            PARK_MIN_GREEN, R, WMS_URL, case_path, nearest_vacant
# makes (used by later steps): SCRIPT_NOTE, YEAR_AFTER, YEAR_BEFORE, sv
# shared functions (to_crs, overpass, zonal, log ...) are in helpers.py
# ==============================================================
# --- 10. write the results into the case JSON + comparison table ---
import csv

YEAR_BEFORE, YEAR_AFTER = min(IRC_LAYERS), max(IRC_LAYERS)
SCRIPT_NOTE = "computed by auto_case.py (" + os.path.basename(OUT_DIR) + ")"

for block, year in (("before", YEAR_BEFORE), ("after", YEAR_AFTER)):
    r = R[year]
    CASE[block]["vegetation"]["present"] = r["vegetated_pct"] > 0
    CASE[block]["vegetation"]["ndvi_mean"] = r["ndvi_mean"]
    CASE[block]["nearby_green_spaces"] = {
        "names": r["nearby_green_names"],
        "nearest_distance_m": r["nearest_park_m"],
        "green_share_pct": r["green_share_pct"],
        "buffer_m": BUFFER_M}
    CASE["provenance"][block]["tag"] = "source_documented"
    CASE["provenance"][block]["field_notes"] = {
        "vegetation.present, vegetation.ndvi_mean":
            f"ICGC infrared orthophoto {year}, 25 cm, NDVI > 0; " + SCRIPT_NOTE,
        "nearby_green_spaces":
            f"OSM leisure=park in {BUFFER_M} m buffer, kept if >= {PARK_MIN_GREEN} green in {year}; "
            f"green share = NDVI > 0 in ring, 1 m; " + SCRIPT_NOTE}
CASE["before"]["nearest_other_vacant_site_m"] = nearest_vacant
CASE["provenance"]["before"]["field_notes"]["nearest_other_vacant_site_m"] = \
    "Urban Atlas 2012 code 13400, nearest polygon not touching the site; " + SCRIPT_NOTE

CASE["case"]["sources"] += [
    {"id": "S2", "title": "Ortofoto de Catalunya infraroig 25 cm 2010 (WMS)",
     "author_or_publisher": "ICGC", "date": "2010", "type": "orthophoto", "url": WMS_URL},
    {"id": "S3", "title": "Ortofoto de Catalunya infraroig 25 cm 2025 (WMS)",
     "author_or_publisher": "ICGC", "date": "2025", "type": "orthophoto", "url": WMS_URL},
    {"id": "S4", "title": "Urban Atlas 2012, Barcelona (code 13400)",
     "author_or_publisher": "Copernicus Land Monitoring Service", "date": "2012",
     "type": "dataset", "url": "https://land.copernicus.eu/en/products/urban-atlas"}]

with open(case_path, "w", encoding="utf-8") as fh:            # overwrite the file from step 5
    json.dump(CASE, fh, ensure_ascii=False, indent=2)
log("Saved:", case_path)

# how much of the case is filled? (case, site, before, after; text "" and null = empty)
for block in ("case", "site", "before", "after"):
    vals = list(leaves({k: v for k, v in CASE[block].items() if k != "sources"}))
    filled = sum(1 for v in vals if v not in ("", None, []))
    log(f"{block}: {filled} of {len(vals)} fields filled by the script")

# one comparison table for everything checked against the manual case
rows = [
    ["", "site.area_m2", 59853, CASE["site"]["area_m2"]],
    ["", "site.shape_index", 1.11, CASE["site"]["shape_index"]],
    ["", "case.lat", 41.368393, CASE["case"]["coordinates"]["lat"]],
    ["", "case.lon", 2.137333, CASE["case"]["coordinates"]["lon"]],
    [YEAR_BEFORE, "nearest_other_vacant_site_m", 1867, nearest_vacant],
]
for year in IRC_LAYERS:
    for field, manual in MANUAL_NDVI[year].items():
        rows.append([year, field, manual, R[year][field]])
    rows.append([year, "park_names_count", MANUAL_PARKS[year]["names"],
                 len(R[year]["nearby_green_names"])])
    rows.append([year, "nearest_park_m", MANUAL_PARKS[year]["nearest_m"],
                 R[year]["nearest_park_m"]])
with open(os.path.join(OUT_DIR, "comparison.csv"), "w", newline="", encoding="utf-8") as fh:
    wr = csv.writer(fh)
    wr.writerow(["year", "field", "manual", "script", "diff"])
    for year, field, m, sv in rows:
        wr.writerow([year, field, m, sv, None if sv is None else round(sv - m, 3)])
log("Saved:", os.path.join(OUT_DIR, "comparison.csv"))
