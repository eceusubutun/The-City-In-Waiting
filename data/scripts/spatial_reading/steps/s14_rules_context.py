# ==============================================================
# s14_rules_context.py - rules: succession_stage, surrounding_context, neighbour_sensitivity, physical_end_state
# Part of auto_case (split from auto_case.py v0.25, 20 Nov 2026). Run through main.py.
# uses (from earlier steps): BUFFER_M, CASE, CRS, GIS_DIR, OUT_DIR, R, SCRIPT_NOTE, YEAR_AFTER,
#                            YEAR_BEFORE, case_path, ring_geom
# makes (used by later steps): code
# shared functions (to_crs, overpass, zonal, log ...) are in helpers.py
# ==============================================================
# --- 14. more rules (decided by Ece, 16 Nov 2026): succession_stage, surrounding_context,
#         neighbour_sensitivity, physical_end_state ---
import glob
from qgis.core import QgsFeatureRequest
log("\nstep 14: more rule-based fields")
RULES2 = {}

# 14a. before.succession_stage: vegetated < 10 % -> unknown (no real succession);
#      trees >= 50 % of the green and height >= 5 m -> young_woodland; trees 20-50 % -> shrub;
#      else grassland
rb_ = R[YEAR_BEFORE]
veg_b = rb_["vegetated_pct"]
tree_frac = rb_["trees_shrubs"] / veg_b if veg_b else 0
if veg_b < 10:
    succession = "unknown"
elif tree_frac >= 0.5 and (rb_["vegetation_height_m"] or 0) >= 5:
    succession = "young_woodland"
elif tree_frac >= 0.2:
    succession = "shrub"
else:
    succession = "grassland"
RULES2["succession_stage"] = ("before", succession,
    f"vegetated {veg_b} %, trees {round(tree_frac * 100)} % of the green, "
    f"height {rb_['vegetation_height_m']} m; planted vs spontaneous not detectable")

# 14b. surrounding_context and neighbour_sensitivity from Urban Atlas 2012 in the 500 m ring
UA_FOLDER = os.path.join(GIS_DIR, "urban_atlas_2012")
UA_RES = ("11100", "11210", "11220", "11230", "11240", "11300")   # residential fabric
UA_IND = ("12100",)                                               # industrial, commercial, public
ua_full = None
for gp in glob.glob(os.path.join(UA_FOLDER, "**", "*.gpkg"), recursive=True):
    ds = ogr.Open(gp)
    for i in range(ds.GetLayerCount()):
        lyr = ds.GetLayerByIndex(i)
        names = [lyr.GetLayerDefn().GetFieldDefn(k).GetName().lower()
                 for k in range(lyr.GetLayerDefn().GetFieldCount())]
        if "code_2012" in names:
            ua_full = (gp, lyr.GetName())
    ds = None
    if ua_full:
        break
if ua_full is None:
    raise Exception("Urban Atlas 2012 GeoPackage with code_2012 not found in " + UA_FOLDER)
log("Urban Atlas file:", os.path.basename(ua_full[0]), "| layer:", ua_full[1])
ua_lyr = QgsVectorLayer(ua_full[0] + "|layername=" + ua_full[1], "ua2012", "ogr")
ring_ua = to_crs(ring_geom, CRS, ua_lyr.crs().authid())         # work in the UA CRS
area_by_class = {}
for f in ua_lyr.getFeatures(QgsFeatureRequest().setFilterRect(ring_ua.boundingBox())):
    inter = f.geometry().intersection(ring_ua)
    if inter.isEmpty():
        continue
    code = str(f["code_2012"])
    area_by_class[code] = area_by_class.get(code, 0) + inter.area()
ring_a = ring_ua.area()
res_a = sum(v for k, v in area_by_class.items() if k in UA_RES)
ind_a = sum(v for k, v in area_by_class.items() if k in UA_IND)
res_of_built = res_a / (res_a + ind_a) if (res_a + ind_a) else 0
res_of_ring = res_a / ring_a
if res_of_built >= 0.6:
    context = "residential"
elif res_of_built <= 0.4:
    context = "industrial"
else:
    context = "mixed"
if res_of_ring >= 0.3:
    sensitivity = "high"
elif ind_a > res_a:
    sensitivity = "low"
else:
    sensitivity = "moderate"
ua_why = (f"Urban Atlas 2012 in the {BUFFER_M} m ring: residential {round(res_of_ring * 100, 1)} % of ring, "
          f"industrial/commercial {round(ind_a / ring_a * 100, 1)} % of ring; residential = "
          f"{round(res_of_built * 100)} % of residential + industrial/commercial land "
          "(UA does not split industrial from commercial)")
RULES2["surrounding_context"] = ("before", context, ua_why)
RULES2["neighbour_sensitivity"] = ("before", sensitivity, ua_why)

# 14c. after.physical_end_state from the retained building share
ret = R[YEAR_AFTER]["building_shell_reused_pct"]
if ret >= 90:
    end_state = "adapted"
elif ret >= 10:
    end_state = "partly_retained"
elif R[YEAR_AFTER]["buildings"] >= 10:
    end_state = "replaced"
elif R[YEAR_AFTER]["vegetated_pct"] >= 50:
    end_state = "left_wild"
else:
    end_state = "cleared"
RULES2["physical_end_state"] = ("after", end_state,
    f"retained {ret} % of {YEAR_BEFORE} building cells; buildings after {R[YEAR_AFTER]['buildings']} %; "
    ">= 90 % written as adapted (retained vs adapted needs judgement)")

for field, (block, value, why) in RULES2.items():
    CASE[block][field] = value
    CASE["provenance"][block]["field_notes"][field] = f"rule: {why}; " + SCRIPT_NOTE
CASE["case"]["sources"].append(
    {"id": "S6", "title": "Urban Atlas 2012, Barcelona (land use in the 500 m ring)",
     "author_or_publisher": "Copernicus Land Monitoring Service", "date": "2012",
     "type": "dataset", "url": "https://land.copernicus.eu/en/products/urban-atlas"})

with open(case_path, "w", encoding="utf-8") as fh:
    json.dump(CASE, fh, ensure_ascii=False, indent=2)

MANUAL_RULES2 = {"succession_stage": "(pending)", "surrounding_context": "mixed",
                 "neighbour_sensitivity": "high", "physical_end_state": "partly_retained"}
log("\nfield | manual | script | why")
with open(os.path.join(OUT_DIR, "comparison.csv"), "a", newline="", encoding="utf-8") as fh:
    wr = csv.writer(fh)
    for field, (block, value, why) in RULES2.items():
        m = MANUAL_RULES2[field]
        log(field, "|", m, "|", value, "|", why)
        wr.writerow(["", field, m, value, "same" if value == m else "different"])

for block in ("case", "site", "before", "after"):
    vals = list(leaves({k: v for k, v in CASE[block].items() if k != "sources"}))
    filled = sum(1 for v in vals if v not in ("", None, []))
    log(f"FINAL {block}: {filled} of {len(vals)} fields filled by the script")
