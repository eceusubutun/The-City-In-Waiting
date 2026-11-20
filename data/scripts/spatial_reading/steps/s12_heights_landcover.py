# ==============================================================
# s12_heights_landcover.py - heights, land cover, retained fabric, built-up ring, slope
# Part of auto_case (split from auto_case.py v0.25, 20 Nov 2026). Run through main.py.
# uses (from earlier steps): CASE, GIS_DIR, IRC_LAYERS, OUT_DIR, R, SCRIPT_NOTE, YEAR_AFTER,
#                            YEAR_BEFORE, case_path, ring_geom, ring_lyr, site_lyr
# makes (used by later steps): DTM_FILE, ndsm, veg2
# shared functions (to_crs, overpass, zonal, log ...) are in helpers.py
# ==============================================================
# --- 12. heights, land cover, retained fabric, built-up ring, slope ---
# Height data are not downloaded yet: they are read from files prepared once per area
# (2010 LiDAR DTM and nDSM, 2 m; ICGC correlation DSM 2024, 1 m).
DTM_FILE = os.path.join(GIS_DIR, "buffer500_dtm.tif")            # ground 2010, 2 m
NDSM_BEFORE_FILE = os.path.join(GIS_DIR, "buffer500_ndsm.tif")   # heights 2010, 2 m
DSM_AFTER_LAYER = "dsm_2024"                                     # layer name in the QGIS project
RESAMPLE = "average"                                             # 1 m -> 2 m (validated 16 Nov)

ref = gdal.Open(DTM_FILE)
cell_m2 = ref.GetGeoTransform()[1] * abs(ref.GetGeoTransform()[5])
dtm = read_nan(DTM_FILE)

def save(arr, name):
    return write_like(ref, np.where(np.isnan(arr), -9999, arr), name)

veg2, ndsm = {}, {}
for year in IRC_LAYERS:
    share = read_nan(align(out_path(f"buf_veg_{year}.tif"), DTM_FILE, f"buf_veg_{year}_2m.tif", RESAMPLE))
    veg2[year] = np.where(np.isnan(share), np.nan, (share >= 0.5).astype(float))
ndsm[YEAR_BEFORE] = read_nan(align(NDSM_BEFORE_FILE, DTM_FILE, "ndsm_before_2m.tif"))
ndsm[YEAR_AFTER] = read_nan(align(project_layer_path(DSM_AFTER_LAYER), DTM_FILE,
                                  "dsm_after_2m.tif", RESAMPLE)) - dtm

ring_area = ring_geom.area()
bldg = {}
for year in IRC_LAYERS:
    nd, vg = ndsm[year], veg2[year]
    valid = ~np.isnan(nd) & ~np.isnan(vg)
    bldg[year] = np.where(valid, ((nd > 2.5) & (vg == 0)).astype(float), np.nan)
    trees = np.where(valid, ((nd > 2) & (vg == 1)).astype(float), np.nan)
    th = np.where(trees == 1, nd, np.nan)
    b = zonal(save(bldg[year], f"bldg_{year}.tif"), site_lyr, "b_")
    t = zonal(save(trees, f"trees_{year}.tif"), site_lyr, "t_")
    h = zonal(save(th, f"treeheight_{year}.tif"), site_lyr, "h_")
    r = R[year]
    r["buildings"] = round(b["mean"] * 100, 1)
    r["trees_shrubs"] = round(t["mean"] * 100, 1)
    r["vegetation_height_m"] = round(h["mean"], 1) if h["count"] else None
    r["grass_herbaceous"] = round(r["vegetated_pct"] - r["trees_shrubs"], 1)
    r["impervious_surface"] = round(100 - r["vegetated_pct"] - r["buildings"], 1)
    rb = zonal(save(bldg[year], f"bldg_ring_{year}.tif"), ring_lyr, "rb_")
    r["surrounding_built_up_pct"] = round(rb["sum"] * cell_m2 / ring_area * 100, 1)

n10, n24 = ndsm[YEAR_BEFORE], ndsm[YEAR_AFTER]
valid = (~np.isnan(n10) & ~np.isnan(n24)
         & ~np.isnan(bldg[YEAR_BEFORE]) & ~np.isnan(bldg[YEAR_AFTER]))
ret = np.where(valid, ((bldg[YEAR_BEFORE] == 1) & (bldg[YEAR_AFTER] == 1)
                       & (np.abs(n24 - n10) < 2)).astype(float), np.nan)
rr = zonal(save(ret, "retained.tif"), site_lyr, "r_")
rh = zonal(save(ret * n10, "retained_h.tif"), site_lyr, "rh_")
b10 = zonal(save(bldg[YEAR_BEFORE], "bldg_before_check.tif"), site_lyr, "c_")
R[YEAR_AFTER]["building_shell_reused_pct"] = round(rr["sum"] / b10["sum"] * 100, 1)
R[YEAR_AFTER]["volume_conserved_m3"] = round(rh["sum"] * cell_m2)

# slope from the DTM (degrees), mean over the site
# on a 2 m grid small steps (kerbs, ramps, building edges in the ground model) raise the mean,
# so the slope is also computed on the DTM averaged to 10 m (the value written to the JSON)
SLOPE_RES = 10
slope_2m = out_path("slope_deg_2m.tif")
gdal.DEMProcessing(slope_2m, DTM_FILE, "slope", computeEdges=True)
s2 = zonal(slope_2m, site_lyr, "s_")
dtm_10 = out_path(f"dtm_{SLOPE_RES}m.tif")
gdal.Warp(dtm_10, DTM_FILE, xRes=SLOPE_RES, yRes=SLOPE_RES, resampleAlg="average",
          dstNodata=-9999, outputType=gdal.GDT_Float32)
slope_10 = out_path(f"slope_deg_{SLOPE_RES}m.tif")
gdal.DEMProcessing(slope_10, dtm_10, "slope", computeEdges=True)
mean_slope = round(zonal(slope_10, site_lyr, "s10_")["mean"], 1)
log("slope 2 m mean:", round(s2["mean"], 1), "| slope 10 m mean (used):", mean_slope)
ref = None

# write into the case JSON
CASE["site"]["mean_slope_deg"] = mean_slope
CASE["site"]["slope"] = "gentle" if mean_slope < 2.9 else "steep"     # 5 % = 2.9 degrees
CASE["provenance"]["site"]["field_notes"]["mean_slope_deg, slope"] = (
    f"slope of the 2010 LiDAR DTM averaged to {SLOPE_RES} m, mean over the site; gentle < 2.9 deg (5 %); " + SCRIPT_NOTE)
for block, year in (("before", YEAR_BEFORE), ("after", YEAR_AFTER)):
    r = R[year]
    CASE[block]["land_cover_pct"].update({
        "trees_shrubs": r["trees_shrubs"], "grass_herbaceous": r["grass_herbaceous"],
        "impervious_surface": r["impervious_surface"], "buildings": r["buildings"]})
    CASE[block]["vegetation"]["tree_canopy_cover_pct"] = r["trees_shrubs"]
    CASE[block]["vegetation"]["vegetation_height_m"] = r["vegetation_height_m"]
    CASE[block]["surrounding_built_up_pct"] = r["surrounding_built_up_pct"]
    CASE["provenance"][block]["field_notes"]["land_cover_pct, tree canopy, vegetation height"] = (
        "2 m grid: building = height > 2.5 m and not vegetated; tree = height > 2 m and vegetated; "
        "grass = vegetated minus trees; impervious = rest (bare_earth and water not separated); "
        f"1 m -> 2 m resampling: {RESAMPLE}; " + SCRIPT_NOTE)
    CASE["provenance"][block]["field_notes"]["surrounding_built_up_pct"] = (
        "building cells in the 500 m ring x cell area / ring area; " + SCRIPT_NOTE)
CASE["after"]["retained_fabric"] = {
    "building_shell_reused_pct": R[YEAR_AFTER]["building_shell_reused_pct"],
    "volume_conserved_m3": R[YEAR_AFTER]["volume_conserved_m3"]}
CASE["provenance"]["after"]["field_notes"]["retained_fabric"] = (
    "building in both years and height change < 2 m, share of 2010 building cells; volume = "
    "2010 height x cell area; " + SCRIPT_NOTE)
CASE["case"]["sources"].append(
    {"id": "S5", "title": "LiDAR 2010 DTM / nDSM (2 m) and correlation DSM 2024 (1 m)",
     "author_or_publisher": "ICGC", "date": "2010; 2024", "type": "dataset",
     "url": "https://www.icgc.cat"})

with open(case_path, "w", encoding="utf-8") as fh:
    json.dump(CASE, fh, ensure_ascii=False, indent=2)

MANUAL_H = {
    YEAR_BEFORE: {"buildings": 73.7, "trees_shrubs": 2.7, "grass_herbaceous": 1.7,
                  "impervious_surface": 21.9, "vegetation_height_m": 4.9,
                  "surrounding_built_up_pct": 58.8},
    YEAR_AFTER: {"buildings": 45.6, "trees_shrubs": 4.6, "grass_herbaceous": 13.7,
                 "impervious_surface": 36.1, "vegetation_height_m": 6.4,
                 "surrounding_built_up_pct": 48.7, "building_shell_reused_pct": 50.2,
                 "volume_conserved_m3": 210396}}
log("\nyear | field | manual | script")
with open(os.path.join(OUT_DIR, "comparison.csv"), "a", newline="", encoding="utf-8") as fh:
    wr = csv.writer(fh)
    for year in IRC_LAYERS:
        for k, m in MANUAL_H[year].items():
            log(year, "|", k, "|", m, "|", R[year][k])
            sv = R[year][k]
            wr.writerow([year, k, m, sv, None if sv is None else round(sv - m, 3)])
    wr.writerow(["", "mean_slope_deg", 1.4, mean_slope, round(mean_slope - 1.4, 3)])
log("mean_slope_deg | 1.4 |", mean_slope, "| slope:", CASE["site"]["slope"])

for block in ("case", "site", "before", "after"):
    vals = list(leaves({k: v for k, v in CASE[block].items() if k != "sources"}))
    filled = sum(1 for v in vals if v not in ("", None, []))
    log(f"FINAL {block}: {filled} of {len(vals)} fields filled by the script")
log("Saved:", case_path)
