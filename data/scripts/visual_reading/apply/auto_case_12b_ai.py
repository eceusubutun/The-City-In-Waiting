# ==============================================================
# auto_case_12b_ai.py  -  step 12b: land cover from the fine-tuned image model
# v2 (20 Nov 2026): runs on its own in the thesis-ai environment (Anaconda Prompt), NOT in QGIS.
#   conda activate thesis-ai
#   python "C:\Users\eceus\Claude\Projects\Thesis Iaac\ai-sam3\auto_case_12b_ai.py"
# Before: ai_arazi.py for the same site (writes <site>\ai_landcover.json).
# What it does: takes the case JSON of the LATEST finished auto_case.py run of the site
# (C:\gis\auto_case\<site>\<run>\<site>.json), replaces land_cover_pct (6 classes incl. bare_earth
# and water) and tree_canopy_cover_pct with the model + fusion result, and saves
#   <run>\<site>_ai.json        (the case JSON with AI land cover; original file untouched)
#   <run>\comparison_ai.csv     (manual | rules (step 12) | AI)
# Also recomputes surface_substrate (step 18c rule) with the AI shares. Rules in auto_case steps
# 13-14 are not recomputed (they keep the step-12 values).
# ==============================================================
import os, json, csv, glob, copy, unicodedata
from datetime import datetime

SITE_NAME = "Can Batlló"                      # same as in auto_case.py / ai_arazi.py
GIS_DIR = r"C:\gis"
YEAR_BEFORE, YEAR_AFTER = 2010, 2025
# Years that take the AI land cover (decision 20 Nov 2026): 2025 only - validated with the blind
# 51-point check (74.5 %). 2010 keeps the rule-based step-12 values (same method as the manual
# values, matches them within 0.1 pt); the model is trained on 2025 imagery and not validated for 2010.
AI_YEARS = [YEAR_AFTER]
# manual values (field notes 15 Nov 2026) - only for the Can Batlló test
MANUAL_H = {YEAR_BEFORE: {"buildings": 73.7, "trees_shrubs": 2.7, "grass_herbaceous": 1.7,
                          "impervious_surface": 21.9},
            YEAR_AFTER: {"buildings": 45.6, "trees_shrubs": 4.6, "grass_herbaceous": 13.7,
                         "impervious_surface": 36.1}}


def slugify(text):
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(c if c.isalnum() else "_" for c in t.lower()).strip("_")


SLUG = slugify(SITE_NAME)
SITE_DIR = os.path.join(GIS_DIR, "auto_case", SLUG)
AI_JSON = os.path.join(SITE_DIR, "ai_landcover.json")
if not os.path.exists(AI_JSON):
    raise SystemExit("ai_landcover.json yok: önce ai_arazi.py çalıştır.")

# latest auto_case run that has a case JSON with land_cover_pct filled (step 12 finished)
runs = []
for p in glob.glob(os.path.join(SITE_DIR, "*", SLUG + ".json")):
    try:
        c = json.load(open(p, encoding="utf-8"))
        if c.get("after", {}).get("land_cover_pct", {}).get("buildings") not in (None, ""):
            runs.append(p)
    except Exception:
        pass
if not runs:
    raise SystemExit(f"{SITE_DIR} içinde adım 12'yi bitirmiş bir auto_case.py çalıştırması bulunamadı.")
case_path = max(runs, key=os.path.getmtime)
RUN_DIR = os.path.dirname(case_path)
print("Case JSON:", case_path)

CASE = json.load(open(case_path, encoding="utf-8"))
AI = json.load(open(AI_JSON, encoding="utf-8"))
print("AI land cover:", os.path.basename(AI["model"]), "| created", AI["created"])
OUT = copy.deepcopy(CASE)
rows = []
for block, year in (("before", YEAR_BEFORE), ("after", YEAR_AFTER)):
    a = AI["years"].get(str(year)) if year in AI_YEARS else None
    if not a:
        print(f"\n{year}: rule-based values (step 12) kept" + ("" if year in AI_YEARS else " (not in AI_YEARS)"))
        continue
    rules = dict(CASE[block]["land_cover_pct"])
    lc = a["land_cover_pct"]
    OUT[block]["land_cover_pct"].update(lc)
    OUT[block]["vegetation"]["tree_canopy_cover_pct"] = lc["trees_shrubs"]
    fus = a.get("fusion")
    OUT["provenance"][block]["field_notes"]["land_cover_pct, tree canopy, vegetation height"] = (
        f"land_cover_pct and tree canopy: provenance {a['provenance']}; fine-tuned SegFormer-B2 "
        f"({os.path.basename(AI['model'])}, 6 material classes, labelling guide v1.1) on ICGC RGB {year} 25 cm"
        + (f" + fusion rules (height: {fus['height']}, NDVI > 0)" if fus else " (image only, no height)")
        + f"; validation: {a['validation']}; vegetation height from auto_case step 12 (2 m grid, height > 2 m "
          f"and vegetated); rule-based values in comparison_ai.csv; ai_arazi.py + auto_case_12b_ai.py v2")
    # surface_substrate (auto_case step 18c rule) recomputed with the AI land cover:
    # impervious >= 10 % -> asphalt_or_concrete; bare earth + grass >= 10 % -> soil_clay;
    # substrates that step 18c took from OSM surface tags (sand, brick ...) are kept
    old_subs = list(CASE[block].get("surface_substrate") or [])
    subs = [s for s in old_subs if s not in ("asphalt_or_concrete", "soil_clay")]
    if lc["impervious_surface"] >= 10:
        subs.insert(0, "asphalt_or_concrete")
    soil = round(lc["bare_earth"] + lc["grass_herbaceous"], 1)
    if soil >= 10:
        subs.insert(1 if "asphalt_or_concrete" in subs else 0, "soil_clay")
    OUT[block]["surface_substrate"] = subs
    old_note = CASE["provenance"][block]["field_notes"].get("surface_substrate", "")
    osm_part = "; ".join(p for p in old_note.split("; ") if p.startswith("OSM surface"))
    OUT["provenance"][block]["field_notes"]["surface_substrate"] = (
        f"rule (auto_case step 18c) recomputed with the AI land cover: impervious {lc['impervious_surface']} %, "
        f"bare earth {lc['bare_earth']} % + grass {lc['grass_herbaceous']} % = {soil} %"
        + (f"; {osm_part} (kept from step 18c)" if osm_part else "")
        + "; rubble, ballast, brick, cracked concrete not separated by the model; auto_case_12b_ai.py v2")
    print(f"\n{year} surface_substrate | rules (step 18c): {old_subs} | with AI: {subs}")
    print(f"\n{year} | field | manual | rules (step 12) | AI")
    for k, v in lc.items():
        m = MANUAL_H.get(year, {}).get(k)
        print(f"  {k:20s} | {str(m):>6s} | {str(rules.get(k)):>6s} | {v}")
        rows.append([year, k, m, rules.get(k), v])
if not any(s.get("id") == "S12" for s in OUT["case"]["sources"]):
    OUT["case"]["sources"].append(
        {"id": "S12", "title": "ICGC colour orthophoto 25 cm (WMS, ortofoto_color_serie_anual) + fine-tuned "
                               "land-cover model (thesis, Nov 2026)",
         "author_or_publisher": "ICGC; model: thesis", "date": "2010; 2025", "type": "dataset",
         "url": "https://geoserveis.icgc.cat/servei/catalunya/orto-territorial/wms"})
out_path = os.path.join(RUN_DIR, SLUG + "_ai.json")
json.dump(OUT, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
with open(os.path.join(RUN_DIR, "comparison_ai.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh); w.writerow(["year", "field", "manual", "rules_step12", "ai"]); w.writerows(rows)
print("\nKaydedildi:", out_path, "\n           ", os.path.join(RUN_DIR, "comparison_ai.csv"))
