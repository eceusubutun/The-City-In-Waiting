# =============================================================
# Can Batlló automation – canbatllo_auto.py  (v0.5, 15 Nov 2026, English)
# Steps: 1 settings · 2 boundary/ring · 3 NDVI · 4 heights
#        5 ring measurements · 6 JSON + comparison table
# =============================================================
import os
import csv
import json
import processing
import numpy as np
from osgeo import gdal
from datetime import datetime

# --- 1. settings ---
SITE_NAME = "Can Batlló"
GIS_DIR = r"C:\gis"
CRS = "EPSG:25831"
BUFFER_M = 500
YEAR_BEFORE = 2010
YEAR_AFTER = 2025
YEARS = [YEAR_BEFORE, YEAR_AFTER]
PARK_MIN_GREEN = 0.1          # minimum green share for a park to count
RESAMPLE = "average"          # 1 m → 2 m resampling: "average" (default, 16 Nov 2026) or "near"

BOUNDARY = os.path.join(GIS_DIR, "can_batllo_boundary_25831.gpkg")
IRC_SITE = {YEAR_BEFORE: "can_batllo_IRC_2010.tif", YEAR_AFTER: "can_batllo_IRC_2025.tif"}
IRC_BUF = {YEAR_BEFORE: "buffer500_IRC_2010_1m.tif", YEAR_AFTER: "buffer500_IRC_2025_1m.tif"}
DTM = os.path.join(GIS_DIR, "buffer500_dtm.tif")             # 2010 LiDAR ground (DTM), 2 m
NDSM_BEFORE = os.path.join(GIS_DIR, "buffer500_ndsm.tif")    # 2010 LiDAR nDSM
PARKS = os.path.join(GIS_DIR, "parks_500_25831.gpkg")        # OSM leisure=park
UA_VACANT = os.path.join(GIS_DIR, "ua2012_13400_25831.gpkg") # Urban Atlas 2012, 13400

RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_DIR = os.path.join(GIS_DIR, "auto", RUN_ID)              # one folder per run
os.makedirs(OUT_DIR, exist_ok=True)
print("Settings loaded:", SITE_NAME, YEAR_BEFORE, YEAR_AFTER)
print("Output folder:", OUT_DIR)

# Manual values (for comparison; field notes 15 Nov 2026)
MANUAL = {
    YEAR_BEFORE: {"ndvi_mean": -0.27, "vegetated_pct": 4.4, "trees_shrubs": 2.7,
                  "grass_herbaceous": 1.7, "buildings": 73.7, "impervious_surface": 21.9,
                  "vegetation_height_m": 4.9, "green_share_pct": 14.9,
                  "surrounding_built_up_pct": 58.8, "nearest_park_m": 5,
                  "nearest_other_vacant_site_m": 1867},
    YEAR_AFTER: {"ndvi_mean": -0.053, "vegetated_pct": 18.3, "trees_shrubs": 4.6,
                 "grass_herbaceous": 13.7, "buildings": 45.6, "impervious_surface": 36.1,
                 "vegetation_height_m": 6.4, "green_share_pct": 23.3,
                 "surrounding_built_up_pct": 48.7, "nearest_park_m": 3,
                 "building_shell_reused_pct": 50.2, "volume_conserved_m3": 210396},
}


# =============================================================
# HELPER FUNCTIONS
# =============================================================
def load_vector(path, name):
    """Open a vector file; raise an error if it cannot be loaded."""
    lyr = QgsVectorLayer(path, name, "ogr")
    if not lyr.isValid():
        raise Exception("Layer could not be loaded: " + path)
    return lyr


def layer_path(name):
    """Return the file path of a project layer, by layer name."""
    lyrs = QgsProject.instance().mapLayersByName(name)
    if not lyrs:
        raise Exception("No layer with this name in the project: " + name)
    return lyrs[0].source()


def out_path(name):
    """Return an output path inside this run's folder."""
    return os.path.join(OUT_DIR, name)


def area_m2(layer):
    """Total area of all polygons in a layer (m²)."""
    return sum(f.geometry().area() for f in layer.getFeatures())


def union_geom(layer):
    """Merge all polygons of a layer into one geometry."""
    return QgsGeometry.unaryUnion([f.geometry() for f in layer.getFeatures()])


def write_like(ref_ds, arr, name, nodata=-9999):
    """Write an array as GeoTIFF with the position and CRS of a reference file."""
    p = out_path(name)
    out = gdal.GetDriverByName("GTiff").Create(
        p, ref_ds.RasterXSize, ref_ds.RasterYSize, 1, gdal.GDT_Float32)
    out.SetGeoTransform(ref_ds.GetGeoTransform())
    out.SetProjection(ref_ds.GetProjection())
    band = out.GetRasterBand(1)
    band.SetNoDataValue(nodata)
    band.WriteArray(arr)
    out = None                      # close the file and write it to disk
    return p


def read_nan(path):
    """Read a raster; set no-data cells to NaN."""
    ds = gdal.Open(path)
    b = ds.GetRasterBand(1)
    a = b.ReadAsArray().astype("float64")
    nd = b.GetNoDataValue()
    if nd is not None:
        a[a == nd] = np.nan
    ds = None
    return a


def align(src_path, ref_path, name, alg="near"):
    """Resample a raster onto the grid (extent + cell size) of a reference raster.
    alg='average' averages small pixels (1 m → 2 m without depending on which pixel is picked)."""
    ref = gdal.Open(ref_path)
    gt = ref.GetGeoTransform()
    xmin, ymax = gt[0], gt[3]
    xmax = xmin + gt[1] * ref.RasterXSize
    ymin = ymax + gt[5] * ref.RasterYSize
    ref = None
    p = out_path(name)
    gdal.Warp(p, src_path, outputBounds=(xmin, ymin, xmax, ymax),
              xRes=gt[1], yRes=abs(gt[5]), resampleAlg=alg,
              dstNodata=-9999, outputType=gdal.GDT_Float32)
    return p


def zonal(raster_path, polygon_layer, prefix):
    """Zonal statistics (single polygon): count, sum, mean."""
    out = processing.run("native:zonalstatisticsfb", {
        "INPUT": polygon_layer, "INPUT_RASTER": raster_path, "RASTER_BAND": 1,
        "COLUMN_PREFIX": prefix, "STATISTICS": [0, 1, 2], "OUTPUT": "TEMPORARY_OUTPUT",
    })["OUTPUT"]
    f = next(out.getFeatures())
    return {"count": f[prefix + "count"], "sum": f[prefix + "sum"], "mean": f[prefix + "mean"]}


def zonal_all(raster_path, polygon_layer, prefix):
    """Zonal statistics (many polygons): (feature, mean) for each polygon."""
    out = processing.run("native:zonalstatisticsfb", {
        "INPUT": polygon_layer, "INPUT_RASTER": raster_path, "RASTER_BAND": 1,
        "COLUMN_PREFIX": prefix, "STATISTICS": [2], "OUTPUT": "TEMPORARY_OUTPUT",
    })["OUTPUT"]
    return [(f, f[prefix + "mean"]) for f in out.getFeatures()]


# =============================================================
# 2. BOUNDARY, BUFFER, RING
# =============================================================
def make_buffer_and_ring(site_layer, dist):
    """Buffer the site, then subtract the site to get the ring (in memory)."""
    buf = processing.run("native:buffer", {
        "INPUT": site_layer, "DISTANCE": dist, "SEGMENTS": 5, "DISSOLVE": True,
        "OUTPUT": "TEMPORARY_OUTPUT",
    })["OUTPUT"]
    ring = processing.run("native:difference", {
        "INPUT": buf, "OVERLAY": site_layer, "OUTPUT": "TEMPORARY_OUTPUT",
    })["OUTPUT"]
    return buf, ring


# =============================================================
# 3. NDVI AND VEGETATION MASK
# =============================================================
def ndvi(irc_path, out_name):
    """NDVI from IRC: (NIR - red) / (NIR + red), computed as float."""
    ds = gdal.Open(irc_path)
    nir = ds.GetRasterBand(1).ReadAsArray().astype("float64")   # band 1 = NIR
    red = ds.GetRasterBand(2).ReadAsArray().astype("float64")   # band 2 = red
    total = nir + red
    nd = np.where(total == 0, -9999, (nir - red) / np.where(total == 0, 1, total))
    p = write_like(ds, nd, out_name)
    ds = None
    return p


def veg_mask(ndvi_path, out_name):
    """NDVI > 0 → 1 (vegetated), else 0; no-data stays no-data."""
    ds = gdal.Open(ndvi_path)
    arr = ds.GetRasterBand(1).ReadAsArray()
    mask = np.where(arr == -9999, -9999, (arr > 0).astype("float64"))
    p = write_like(ds, mask, out_name)
    ds = None
    return p


# =============================================================
# RUN
# =============================================================
R = {YEAR_BEFORE: {}, YEAR_AFTER: {}}          # all results are collected here

site = load_vector(BOUNDARY, "site")
site_geom = union_geom(site)
buffer_lyr, ring_lyr = make_buffer_and_ring(site, BUFFER_M)
ring_area = area_m2(ring_lyr)
print("Site (m²):", round(area_m2(site)), "| Ring (m²):", round(ring_area))

# --- 3. site NDVI (25 cm) ---
for year in YEARS:
    nd = ndvi(os.path.join(GIS_DIR, IRC_SITE[year]), f"site_NDVI_{year}.tif")
    veg = veg_mask(nd, f"site_veg_{year}.tif")
    R[year]["ndvi_mean"] = round(zonal(nd, site, "n_")["mean"], 3)
    R[year]["vegetated_pct"] = round(zonal(veg, site, "v_")["mean"] * 100, 1)
    print(year, "| ndvi_mean:", R[year]["ndvi_mean"], "| vegetated %:", R[year]["vegetated_pct"])

# --- 4. heights (2 m grid) ---
ref = gdal.Open(DTM)
cell_m2 = ref.GetGeoTransform()[1] * abs(ref.GetGeoTransform()[5])
dtm = read_nan(DTM)


def save(arr, name):
    """Save an array on the DTM grid, with NaN written as -9999."""
    return write_like(ref, np.where(np.isnan(arr), -9999, arr), name)


veg, veg_1m, ndsm = {}, {}, {}
for year in YEARS:
    nd_b = ndvi(os.path.join(GIS_DIR, IRC_BUF[year]), f"buf_NDVI_{year}.tif")
    veg_1m[year] = veg_mask(nd_b, f"buf_veg_{year}.tif")                 # 1 m, used for the ring
    share = read_nan(align(veg_1m[year], DTM, f"buf_veg_{year}_2m.tif", RESAMPLE))
    veg[year] = np.where(np.isnan(share), np.nan, (share >= 0.5).astype(float))

ndsm[YEAR_BEFORE] = read_nan(align(NDSM_BEFORE, DTM, "ndsm_before_2m.tif"))
ndsm[YEAR_AFTER] = read_nan(align(layer_path("dsm_2024"), DTM, "dsm_after_2m.tif", RESAMPLE)) - dtm

bldg = {}
for year in YEARS:
    nd, vg = ndsm[year], veg[year]
    valid = ~np.isnan(nd) & ~np.isnan(vg)
    bldg[year] = np.where(valid, ((nd > 2.5) & (vg == 0)).astype(float), np.nan)
    trees = np.where(valid, ((nd > 2) & (vg == 1)).astype(float), np.nan)
    th = np.where(trees == 1, nd, np.nan)
    b = zonal(save(bldg[year], f"bldg_{year}.tif"), site, "b_")
    t = zonal(save(trees, f"trees_{year}.tif"), site, "t_")
    h = zonal(save(th, f"treeheight_{year}.tif"), site, "h_")
    R[year]["buildings"] = round(b["mean"] * 100, 1)
    R[year]["trees_shrubs"] = round(t["mean"] * 100, 1)
    R[year]["vegetation_height_m"] = round(h["mean"], 1) if h["count"] else None
    R[year]["grass_herbaceous"] = round(R[year]["vegetated_pct"] - R[year]["trees_shrubs"], 1)
    R[year]["impervious_surface"] = round(100 - R[year]["vegetated_pct"] - R[year]["buildings"], 1)
    # 5a. built-up share of the ring: building cells × cell area ÷ ring area
    rb = zonal(save(bldg[year], f"bldg_ring_{year}.tif"), ring_lyr, "rb_")
    R[year]["surrounding_built_up_pct"] = round(rb["sum"] * cell_m2 / ring_area * 100, 1)

n10, n24 = ndsm[YEAR_BEFORE], ndsm[YEAR_AFTER]
valid = (~np.isnan(n10) & ~np.isnan(n24)
         & ~np.isnan(bldg[YEAR_BEFORE]) & ~np.isnan(bldg[YEAR_AFTER]))
ret = np.where(valid, ((bldg[YEAR_BEFORE] == 1) & (bldg[YEAR_AFTER] == 1)
                       & (np.abs(n24 - n10) < 2)).astype(float), np.nan)
r = zonal(save(ret, "retained.tif"), site, "r_")
rh = zonal(save(ret * n10, "retained_h.tif"), site, "rh_")
b10 = zonal(save(bldg[YEAR_BEFORE], "bldg_before_check.tif"), site, "c_")
R[YEAR_AFTER]["building_shell_reused_pct"] = round(r["sum"] / b10["sum"] * 100, 1)
R[YEAR_AFTER]["volume_conserved_m3"] = round(rh["sum"] * cell_m2)
for year in YEARS:
    print(year, "| buildings %:", R[year]["buildings"], "| trees %:", R[year]["trees_shrubs"],
          "| tree height m:", R[year]["vegetation_height_m"],
          "| built-up ring %:", R[year]["surrounding_built_up_pct"])
print("retained buildings %:", R[YEAR_AFTER]["building_shell_reused_pct"],
      "| volume m³:", R[YEAR_AFTER]["volume_conserved_m3"])
ref = None

# --- 5. ring: green share, parks, nearest park, nearest vacant land ---
parks = load_vector(PARKS, "parks")
for year in YEARS:
    R[year]["green_share_pct"] = round(zonal(veg_1m[year], ring_lyr, "g_")["mean"] * 100, 1)
    names, dists = set(), []
    for f, green in zonal_all(veg_1m[year], parks, "p_"):
        g = f.geometry()
        if green is None or green < PARK_MIN_GREEN:
            continue                                         # not green in that year
        if g.intersection(site_geom).area() > 0.5 * g.area():
            continue                                         # mostly inside the site → the site itself
        dists.append(g.distance(site_geom))
        if f["name"]:
            names.add(f["name"])
    R[year]["nearby_green_names"] = sorted(names)
    R[year]["nearest_park_m"] = round(min(dists)) if dists else None
    print(year, "| green share %:", R[year]["green_share_pct"], "| parks:", len(names),
          "| nearest park m:", R[year]["nearest_park_m"])

ua = load_vector(UA_VACANT, "ua_vacant")
print("Urban Atlas CRS:", ua.crs().authid())
if ua.crs().authid() != CRS:                                  # reproject to 25831 if different
    ua = processing.run("native:reprojectlayer", {"INPUT": ua, "TARGET_CRS": CRS,
                                                  "OUTPUT": "TEMPORARY_OUTPUT"})["OUTPUT"]
d_ua = [f.geometry().distance(site_geom) for f in ua.getFeatures()
        if not f.geometry().intersects(site_geom)]
R[YEAR_BEFORE]["nearest_other_vacant_site_m"] = round(min(d_ua)) if d_ua else None
print("nearest vacant land (UA 13400) m:", R[YEAR_BEFORE]["nearest_other_vacant_site_m"])

# =============================================================
# 6. OUTPUT: JSON + COMPARISON TABLE
# =============================================================
def to_case_json(r, after=False):
    """Arrange results with the field names and structure of the Can Batlló case JSON."""
    block = {
        "land_cover_pct": {
            "trees_shrubs": r["trees_shrubs"],
            "grass_herbaceous": r["grass_herbaceous"],
            "impervious_surface": r["impervious_surface"],
            "buildings": r["buildings"],
        },
        "vegetation": {
            "present": r["vegetated_pct"] > 0,
            "tree_canopy_cover_pct": r["trees_shrubs"],
            "ndvi_mean": r["ndvi_mean"],
            "vegetation_height_m": r["vegetation_height_m"],
        },
        "nearby_green_spaces": {
            "names": r["nearby_green_names"],
            "nearest_distance_m": r["nearest_park_m"],
            "green_share_pct": r["green_share_pct"],
            "buffer_m": BUFFER_M,
        },
        "surrounding_built_up_pct": r["surrounding_built_up_pct"],
    }
    if after:
        block["retained_fabric"] = {
            "building_shell_reused_pct": r["building_shell_reused_pct"],
            "volume_conserved_m3": r["volume_conserved_m3"],
        }
    else:
        block["nearest_other_vacant_site_m"] = r["nearest_other_vacant_site_m"]
    return block


result = {
    "case": SITE_NAME,
    "run_id": RUN_ID,
    "provenance": {"tag": "script", "script": "canbatllo_auto.py v0.5",
                   "resample_1m_to_2m": RESAMPLE,
                   "heights_after": "ICGC DSM 2024 (1 m) - LiDAR 2010 DTM, 2 m grid",
                   "ndvi": "ICGC IRC WMS rendering (not reflectance)"},
    "before": to_case_json(R[YEAR_BEFORE]),
    "after": to_case_json(R[YEAR_AFTER], after=True),
}
with open(out_path("results.json"), "w", encoding="utf-8") as fh:
    json.dump(result, fh, ensure_ascii=False, indent=2)

rows = []
for year in YEARS:
    for field, manual in MANUAL[year].items():
        script = R[year].get(field)
        diff = None if script is None else round(script - manual, 2)
        rows.append([year, field, manual, script, diff])
with open(out_path("comparison.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["year", "field", "manual", "script", "diff"])
    w.writerows(rows)

print("\n--- manual vs script ---")
for year, field, manual, script, diff in rows:
    print(f"{year} | {field:28} | manual {manual:>9} | script {str(script):>9} | diff {diff}")
print("\nParks (after):", R[YEAR_AFTER]["nearby_green_names"])
print("Saved:", out_path("results.json"), "and comparison.csv")