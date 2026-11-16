# ==============================================================
# auto_case.py  -  boundary file + name -> case JSON
# v0.25, 16 Nov 2026
# Steps: 1 settings · 2 boundary · 3 OSM location info
#        4 fill case JSON · 5 save + compare · 6 download IRC (WMS)
#        7 NDVI · 8 parks · 9 Urban Atlas · 10 write JSON + comparison
#        11 connectivity + water (OSM) · 12 heights, land cover, retained, slope
#        13 rules: parcel_shape, location, urban_network, biodiversity
#        14 rules: succession_stage, surrounding_context, neighbour_sensitivity, physical_end_state
#        15 cadastral parcels (Catastro WFS) · 16 geology, flood, zoning
#        17 surroundings (Open Data BCN padró)
#        18 rules: enclosure, site_layout, surface_substrate, infrastructure, reclaimed_area_m2
# ==============================================================
import os
import copy
import json
import unicodedata
import urllib.request
import urllib.parse
from datetime import datetime
from qgis.core import (QgsVectorLayer, QgsGeometry, QgsFeature, QgsProject,
                       QgsCoordinateReferenceSystem, QgsCoordinateTransform)

# --- 1. settings (the only part you change per site) ---
SITE_NAME = "Can Batlló"
CASE_ID = "1.1-BCN-01"
BOUNDARY_FILE = r"C:\gis\can_batllo_boundary_25831.gpkg"   # gpkg, shp or kml
TEMPLATE_JSON = r"C:\Users\eceus\OneDrive\Desktop\main folders\classes\iaac\thesis\The-City-In-Waiting\data\categories\1.1-former-industrial-service-estates.json"
MANUAL_JSON = r"C:\Users\eceus\OneDrive\Desktop\main folders\classes\iaac\thesis\The-City-In-Waiting\data\cases\can_batllo.json"  # only for the test; set to None for new sites

CITY_CENTRE = ("Plaça de Catalunya", 41.38701, 2.17000)  # name, lat, lon (for distance_to_centre_km)

GIS_DIR = r"C:\gis"
CRS = "EPSG:25831"
USER_AGENT = "IAAC-MAA02-thesis-script"


def slugify(text):
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(c if c.isalnum() else "_" for c in t.lower()).strip("_")

SLUG = slugify(SITE_NAME)
SITE_DIR = os.path.join(GIS_DIR, "auto_case", SLUG)                  # cache per site
OUT_DIR = os.path.join(SITE_DIR, datetime.now().strftime("%Y%m%d_%H%M%S"))  # one folder per run
os.makedirs(OUT_DIR, exist_ok=True)
print("Site:", SITE_NAME, "| output:", OUT_DIR)


# --- 2. boundary: read the file, merge parts, convert to metres ---
def to_crs(g, src, dst):
    tr = QgsCoordinateTransform(QgsCoordinateReferenceSystem(src),
                                QgsCoordinateReferenceSystem(dst),
                                QgsProject.instance())
    g = QgsGeometry(g)
    g.transform(tr)
    return g

bnd = QgsVectorLayer(BOUNDARY_FILE, "boundary", "ogr")
if not bnd.isValid():
    raise Exception("Boundary file not found or not readable: " + BOUNDARY_FILE)
site_geom = QgsGeometry.unaryUnion([f.geometry() for f in bnd.getFeatures()])
src_crs = bnd.crs().authid()
if src_crs != CRS:
    site_geom = to_crs(site_geom, src_crs, CRS)
    print("Boundary reprojected from", src_crs)

area = site_geom.area()
perimeter = site_geom.length()
shape_index = 0.25 * perimeter / area ** 0.5
centre_wgs = to_crs(site_geom.centroid(), CRS, "EPSG:4326").asPoint()
lat, lon = centre_wgs.y(), centre_wgs.x()
print("Area (m2):", round(area), "| perimeter (m):", round(perimeter),
      "| shape index:", round(shape_index, 2))
print("Centre (WGS84):", round(lat, 6), round(lon, 6))


# --- 3. OSM: which named areas contain the site centre? (cached) ---
import time

OVERPASS_SERVERS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

def overpass(query, timeout=90):
    last_error = None
    for attempt in range(2):                 # go through the list twice
        for url in OVERPASS_SERVERS:
            try:
                req = urllib.request.Request(
                    url,
                    data=urllib.parse.urlencode({"data": query}).encode(),
                    headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    print("Overpass OK:", url)
                    return json.loads(r.read().decode("utf-8"))
            except Exception as e:
                print("Overpass failed:", url, "-", e)
                last_error = e
                time.sleep(5)               # wait before trying the next server
    raise last_error

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


# --- 6. download infrared orthophotos (ICGC WMS), cached per site ---
import math
import shutil
from osgeo import gdal
from qgis.core import QgsRasterLayer

WMS_URL = "https://geoserveis.icgc.cat/servei/catalunya/orto-territorial/wms"
IRC_LAYERS = {2010: "ortofoto_25cm_infraroig_2010",
              2025: "ortofoto_25cm_infraroig_2025"}
BUFFER_M = 500
TILE_PX = 2000                      # max image size per WMS request
DATA_DIR = os.path.join(SITE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

def snapped_extent(geom, step):
    # bounding box rounded outwards to a multiple of step (keeps grids aligned)
    bb = geom.boundingBox()
    return (math.floor(bb.xMinimum() / step) * step, math.floor(bb.yMinimum() / step) * step,
            math.ceil(bb.xMaximum() / step) * step, math.ceil(bb.yMaximum() / step) * step)

def wms_getmap(layer, bbox, width, height, path):
    params = {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap",
              "LAYERS": layer, "STYLES": "", "CRS": CRS,
              "BBOX": ",".join(str(v) for v in bbox),
              "WIDTH": width, "HEIGHT": height, "FORMAT": "image/png"}
    url = WMS_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
        ctype = r.headers.get("Content-Type", "")
    if "image" not in ctype:
        raise Exception("WMS did not return an image: " + data[:300].decode(errors="ignore"))
    with open(path, "wb") as fh:
        fh.write(data)

def download_wms(layer, extent, res, out_tif):
    if os.path.exists(out_tif):
        print("cached:", os.path.basename(out_tif))
        return out_tif
    xmin, ymin, xmax, ymax = extent
    tile_m = TILE_PX * res
    nx = math.ceil((xmax - xmin) / tile_m)
    ny = math.ceil((ymax - ymin) / tile_m)
    tmp = out_tif + "_tiles"
    os.makedirs(tmp, exist_ok=True)
    tifs = []
    for i in range(nx):
        for j in range(ny):
            x0 = xmin + i * tile_m
            x1 = min(x0 + tile_m, xmax)
            y0 = ymin + j * tile_m
            y1 = min(y0 + tile_m, ymax)
            png = os.path.join(tmp, f"t_{i}_{j}.png")
            wms_getmap(layer, (x0, y0, x1, y1),
                       round((x1 - x0) / res), round((y1 - y0) / res), png)
            src = gdal.Open(png)
            opts = {"rgbExpand": "rgb"} if src.RasterCount == 1 else {"bandList": [1, 2, 3]}
            src = None
            tif = png.replace(".png", ".tif")
            gdal.Translate(tif, png, outputBounds=[x0, y1, x1, y0], outputSRS=CRS, **opts)
            tifs.append(tif)
    vrt_path = out_tif + ".vrt"
    vrt = gdal.BuildVRT(vrt_path, tifs)
    gdal.Translate(out_tif, vrt, creationOptions=["COMPRESS=DEFLATE", "TILED=YES"])
    vrt = None
    os.remove(vrt_path)
    shutil.rmtree(tmp)
    print("downloaded:", os.path.basename(out_tif), f"({nx * ny} tile(s))")
    return out_tif

buffer_geom = site_geom.buffer(BUFFER_M, 16)
site_ext = snapped_extent(site_geom, 2)
buf_ext = snapped_extent(buffer_geom, 2)

IRC_SITE, IRC_BUF = {}, {}
for year, layer in IRC_LAYERS.items():
    IRC_SITE[year] = download_wms(layer, site_ext, 0.25,
                                  os.path.join(DATA_DIR, f"irc_site_{year}_025m.tif"))
    IRC_BUF[year] = download_wms(layer, buf_ext, 1.0,
                                 os.path.join(DATA_DIR, f"irc_buffer_{year}_1m.tif"))
    QgsProject.instance().addMapLayer(QgsRasterLayer(IRC_SITE[year], f"auto_irc_site_{year}"))


# --- 7. NDVI: site (25 cm) and green share of the 500 m ring (1 m) ---
import numpy as np
import processing

def geom_layer(geom, name):
    # one geometry -> memory polygon layer (needed by zonal statistics)
    lyr = QgsVectorLayer("MultiPolygon?crs=" + CRS, name, "memory")
    g = QgsGeometry(geom)
    g.convertToMultiType()
    f = QgsFeature()
    f.setGeometry(g)
    lyr.dataProvider().addFeatures([f])
    return lyr

def out_path(name):
    return os.path.join(OUT_DIR, name)

def write_like(ref_ds, arr, name, nodata=-9999):
    p = out_path(name)
    out = gdal.GetDriverByName("GTiff").Create(
        p, ref_ds.RasterXSize, ref_ds.RasterYSize, 1, gdal.GDT_Float32)
    out.SetGeoTransform(ref_ds.GetGeoTransform())
    out.SetProjection(ref_ds.GetProjection())
    band = out.GetRasterBand(1)
    band.SetNoDataValue(nodata)
    band.WriteArray(arr)
    out = None
    return p

def ndvi(irc_path, out_name):
    # NDVI = (NIR - red) / (NIR + red); band 1 = NIR, band 2 = red
    ds = gdal.Open(irc_path)
    nir = ds.GetRasterBand(1).ReadAsArray().astype("float64")
    red = ds.GetRasterBand(2).ReadAsArray().astype("float64")
    total = nir + red
    nd = np.where(total == 0, -9999, (nir - red) / np.where(total == 0, 1, total))
    p = write_like(ds, nd, out_name)
    ds = None
    return p

def veg_mask(ndvi_path, out_name):
    # NDVI > 0 -> 1 (vegetated), else 0
    ds = gdal.Open(ndvi_path)
    arr = ds.GetRasterBand(1).ReadAsArray()
    mask = np.where(arr == -9999, -9999, (arr > 0).astype("float64"))
    p = write_like(ds, mask, out_name)
    ds = None
    return p

def zonal(raster_path, polygon_layer, prefix):
    out = processing.run("native:zonalstatisticsfb", {
        "INPUT": polygon_layer, "INPUT_RASTER": raster_path, "RASTER_BAND": 1,
        "COLUMN_PREFIX": prefix, "STATISTICS": [0, 1, 2], "OUTPUT": "TEMPORARY_OUTPUT",
    })["OUTPUT"]
    f = next(out.getFeatures())
    return {"count": f[prefix + "count"], "sum": f[prefix + "sum"], "mean": f[prefix + "mean"]}

site_lyr = geom_layer(site_geom, "site")
ring_geom = buffer_geom.difference(site_geom)
ring_lyr = geom_layer(ring_geom, "ring")

R = {year: {} for year in IRC_LAYERS}
for year in IRC_LAYERS:
    nd = ndvi(IRC_SITE[year], f"site_ndvi_{year}.tif")
    veg = veg_mask(nd, f"site_veg_{year}.tif")
    R[year]["ndvi_mean"] = round(zonal(nd, site_lyr, "n_")["mean"], 3)
    R[year]["vegetated_pct"] = round(zonal(veg, site_lyr, "v_")["mean"] * 100, 1)
    nd_b = ndvi(IRC_BUF[year], f"buf_ndvi_{year}.tif")
    veg_b = veg_mask(nd_b, f"buf_veg_{year}.tif")
    R[year]["green_share_pct"] = round(zonal(veg_b, ring_lyr, "g_")["mean"] * 100, 1)

# manual values (field notes) - only for the Can Batlló test
MANUAL_NDVI = {2010: {"ndvi_mean": -0.27, "vegetated_pct": 4.4, "green_share_pct": 14.9},
               2025: {"ndvi_mean": -0.053, "vegetated_pct": 18.3, "green_share_pct": 23.3}}
print("\nyear | field | manual | script")
for year in IRC_LAYERS:
    for field, value in R[year].items():
        print(year, "|", field, "|", MANUAL_NDVI.get(year, {}).get(field), "|", value)


# --- 8. parks: OSM leisure=park around the site, filtered per year by green share ---
from qgis.core import QgsField, QgsFields, QgsPointXY, QgsWkbTypes
from qgis.PyQt.QtCore import QVariant

PARK_MIN_GREEN = 0.1     # a park counts in a year only if >= 10 % of it is green

def log(*parts):
    # print and also write to log.txt (readable even if QGIS closes)
    text = " ".join(str(p) for p in parts)
    print(text)
    with open(os.path.join(OUT_DIR, "log.txt"), "a", encoding="utf-8") as fh:
        fh.write(text + "\n")

log("step 8 start")

# bounding box of the 500 m buffer in lat/lon (Overpass order: south, west, north, east)
bb = to_crs(QgsGeometry.fromRect(buffer_geom.boundingBox()), CRS, "EPSG:4326").boundingBox()
s, w, n, e = bb.yMinimum(), bb.xMinimum(), bb.yMaximum(), bb.xMaximum()

parks_json = os.path.join(SITE_DIR, "osm_parks.json")
if os.path.exists(parks_json):
    with open(parks_json, encoding="utf-8") as fh:
        parks_data = json.load(fh)
    log("OSM parks read from cache")
else:
    parks_data = overpass(f'[out:json][timeout:60];'
                          f'(way["leisure"="park"]({s},{w},{n},{e});'
                          f'relation["leisure"="park"]({s},{w},{n},{e}););out geom;')
    if not parks_data.get("elements"):
        raise Exception("Overpass returned no parks")
    with open(parks_json, "w", encoding="utf-8") as fh:
        json.dump(parks_data, fh, ensure_ascii=False)
    log("OSM parks downloaded")
log("OSM park objects:", len(parks_data["elements"]))

def polygon_parts(g):
    # keep only the polygon parts of a geometry, as one (multi)polygon
    parts = [p for p in g.asGeometryCollection() if p.type() == QgsWkbTypes.PolygonGeometry]
    return QgsGeometry.unaryUnion(parts) if parts else QgsGeometry()

def osm_polygon(el):
    # way -> polygon from its points; relation -> polygons from its outer members
    if el["type"] == "way":
        pts = el.get("geometry", [])
        if len(pts) < 4 or pts[0] != pts[-1]:
            return QgsGeometry()                       # not a closed outline
        return QgsGeometry.fromPolygonXY([[QgsPointXY(p["lon"], p["lat"]) for p in pts]])
    lines = [QgsGeometry.fromPolylineXY([QgsPointXY(p["lon"], p["lat"]) for p in m["geometry"]])
             for m in el.get("members", [])
             if m.get("role") == "outer" and m.get("geometry")]
    if not lines:
        return QgsGeometry()
    return polygon_parts(QgsGeometry.polygonize(lines))

parks_lyr = QgsVectorLayer("MultiPolygon?crs=" + CRS, "parks", "memory")
fields = QgsFields()
fields.append(QgsField("name", QVariant.String))
parks_lyr.dataProvider().addAttributes(fields)
parks_lyr.updateFields()
feats = []
for el in parks_data["elements"]:
    g = osm_polygon(el)
    if g.isEmpty():
        continue
    g = to_crs(g, "EPSG:4326", CRS).makeValid()
    g = polygon_parts(g.intersection(buffer_geom))     # clip to the 500 m buffer
    if g.isEmpty() or g.area() == 0:
        continue
    g.convertToMultiType()
    nf = QgsFeature(parks_lyr.fields())
    nf.setGeometry(g)
    nf["name"] = el.get("tags", {}).get("name")
    feats.append(nf)
parks_lyr.dataProvider().addFeatures(feats)
log("Park polygons in the buffer:", parks_lyr.featureCount())

def zonal_all(raster_path, polygon_layer, prefix):
    out = processing.run("native:zonalstatisticsfb", {
        "INPUT": polygon_layer, "INPUT_RASTER": raster_path, "RASTER_BAND": 1,
        "COLUMN_PREFIX": prefix, "STATISTICS": [2], "OUTPUT": "TEMPORARY_OUTPUT",
    })["OUTPUT"]
    return [(f, f[prefix + "mean"]) for f in out.getFeatures()]

for year in IRC_LAYERS:
    names, dists = set(), []
    for f, green in zonal_all(out_path(f"buf_veg_{year}.tif"), parks_lyr, "p_"):
        g = f.geometry()
        if green is None or green < PARK_MIN_GREEN:
            continue                                   # not green in that year
        if g.intersection(site_geom).area() > 0.5 * g.area():
            continue                                   # mostly inside the site = the site itself
        dists.append(g.distance(site_geom))
        if f["name"]:
            names.add(f["name"])
    R[year]["nearby_green_names"] = sorted(names)
    R[year]["nearest_park_m"] = round(min(dists)) if dists else None
    log(year, "parks done")

MANUAL_PARKS = {2010: {"names": 15, "nearest_m": 5}, 2025: {"names": 19, "nearest_m": 3}}
log("\nyear | park names (manual / script) | nearest park m (manual / script)")
for year in IRC_LAYERS:
    log(year, "|", MANUAL_PARKS[year]["names"], "/", len(R[year]["nearby_green_names"]),
        "|", MANUAL_PARKS[year]["nearest_m"], "/", R[year]["nearest_park_m"])
log("Names 2025:", R[2025]["nearby_green_names"])


# --- 9. nearest other vacant site (Urban Atlas 2012, code 13400) ---
UA_VACANT = os.path.join(GIS_DIR, "ua2012_13400_25831.gpkg")   # Barcelona FUA, prepared once
ua = QgsVectorLayer(UA_VACANT, "ua_vacant", "ogr")
if not ua.isValid():
    raise Exception("Urban Atlas file not found: " + UA_VACANT)
ua_crs = ua.crs().authid()
d_ua = []
for f in ua.getFeatures():
    g = f.geometry()
    if ua_crs != CRS:
        g = to_crs(g, ua_crs, CRS)
    if g.intersects(site_geom):
        continue                                  # the site itself (if mapped)
    d_ua.append(g.distance(site_geom))
nearest_vacant = round(min(d_ua)) if d_ua else None
log("Nearest vacant site (UA 13400) m - manual / script:", 1867, "/", nearest_vacant)


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
def leaves(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from leaves(v)
    elif isinstance(x, list) and x and isinstance(x[0], dict):
        for v in x:
            yield from leaves(v)
    else:
        yield x

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

def osm_geom(el):
    # node -> point; way -> line; relation -> its member lines (enough for distances)
    if el["type"] == "node":
        g = QgsGeometry.fromPointXY(QgsPointXY(el["lon"], el["lat"]))
    elif el["type"] == "way" and el.get("geometry"):
        g = QgsGeometry.fromPolylineXY([QgsPointXY(p["lon"], p["lat"]) for p in el["geometry"]])
    else:
        lines = [QgsGeometry.fromPolylineXY([QgsPointXY(p["lon"], p["lat"]) for p in m["geometry"]])
                 for m in el.get("members", []) if m.get("geometry")]
        if not lines:
            return QgsGeometry()
        g = QgsGeometry.collectGeometry(lines)
    return to_crs(g, "EPSG:4326", CRS)

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

def label(el):
    if el is None:
        return "none found"
    t = el.get("tags", {})
    kind = next((f"{k}={t[k]}" for k in ("highway", "railway", "shop", "amenity",
                                        "natural", "waterway", "place") if k in t), "")
    return f'{t.get("name", "(no name)")} [{kind}]'

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


# --- 12. heights, land cover, retained fabric, built-up ring, slope ---
# Height data are not downloaded yet: they are read from files prepared once per area
# (2010 LiDAR DTM and nDSM, 2 m; ICGC correlation DSM 2024, 1 m).
DTM_FILE = os.path.join(GIS_DIR, "buffer500_dtm.tif")            # ground 2010, 2 m
NDSM_BEFORE_FILE = os.path.join(GIS_DIR, "buffer500_ndsm.tif")   # heights 2010, 2 m
DSM_AFTER_LAYER = "dsm_2024"                                     # layer name in the QGIS project
RESAMPLE = "average"                                             # 1 m -> 2 m (validated 16 Nov)

def project_layer_path(name):
    lyrs = QgsProject.instance().mapLayersByName(name)
    if not lyrs:
        raise Exception("Layer not found in the project: " + name)
    return lyrs[0].source().split("|")[0]

def read_nan(path):
    ds = gdal.Open(path)
    b = ds.GetRasterBand(1)
    a = b.ReadAsArray().astype("float64")
    nd = b.GetNoDataValue()
    if nd is not None:
        a[a == nd] = np.nan
    ds = None
    return a

def align(src_path, ref_path, name, alg="near"):
    # resample a raster onto the grid of the reference raster
    ref = gdal.Open(ref_path)
    gt = ref.GetGeoTransform()
    xmin, ymax = gt[0], gt[3]
    xmax = xmin + gt[1] * ref.RasterXSize
    ymin = ymax + gt[5] * ref.RasterYSize
    ref = None
    p = out_path(name)
    gdal.Warp(p, src_path, outputBounds=(xmin, ymin, xmax, ymax), xRes=gt[1], yRes=abs(gt[5]),
              resampleAlg=alg, dstNodata=-9999, outputType=gdal.GDT_Float32)
    return p

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


# --- 13. rule-based fields (rules decided by Ece, 16 Nov 2026) ---
# parcel_shape, location, urban_network, after.biodiversity
from osgeo import ogr
log("\nstep 13: rule-based fields")

def nominatim_polygon(osm_id):
    # simplified outline of an OSM area from Nominatim (small answer, already assembled)
    params = urllib.parse.urlencode({"osm_ids": osm_id, "format": "geojson",
                                     "polygon_geojson": 1, "polygon_threshold": 0.0005})
    req = urllib.request.Request("https://nominatim.openstreetmap.org/lookup?" + params,
                                 headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

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


# --- 15. cadastral parcels (Catastro INSPIRE WFS) ---
log("\nstep 15: cadastral parcels")
CATASTRO_WFS = "https://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx"
PARCEL_MIN_SHARE = 0.5      # a parcel counts if >= 50 % of it lies inside the site boundary

cp_cache = os.path.join(SITE_DIR, "catastro_parcels.gml")
if not os.path.exists(cp_cache):
    bx = site_geom.boundingBox()
    params = urllib.parse.urlencode({
        "service": "wfs", "version": "2.0.0", "request": "getfeature",
        "typenames": "CP.CadastralParcel", "srsname": "EPSG::25831",
        "bbox": f"{bx.xMinimum():.0f},{bx.yMinimum():.0f},{bx.xMaximum():.0f},{bx.yMaximum():.0f}"})
    req = urllib.request.Request(CATASTRO_WFS + "?" + params, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    if b"CadastralParcel" not in data:
        raise Exception("Catastro WFS returned no parcels: " + data[:400].decode(errors="ignore"))
    with open(cp_cache, "wb") as fh:
        fh.write(data)
    log("Catastro parcels downloaded")
else:
    log("Catastro parcels read from cache")

cp_lyr = QgsVectorLayer(cp_cache, "parcels", "ogr")
log("parcel layer valid:", cp_lyr.isValid(), "| parcels in bbox:", cp_lyr.featureCount(),
    "| CRS:", cp_lyr.crs().authid())
cp_crs = cp_lyr.crs().authid() or CRS
ref_field = next((f.name() for f in cp_lyr.fields()
                  if f.name().lower() in ("nationalcadastralreference", "localid")), None)
if ref_field is None:
    raise Exception("No cadastral reference field; fields are: " + ", ".join(f.name() for f in cp_lyr.fields()))
parcels_in = []
for f in cp_lyr.getFeatures():
    g = f.geometry()
    if cp_crs != CRS:
        g = to_crs(g, cp_crs, CRS)
    if g.isEmpty() or g.area() == 0:
        continue
    share = g.intersection(site_geom).area() / g.area()
    if share >= PARCEL_MIN_SHARE:
        parcels_in.append((str(f[ref_field]), round(g.area()), round(share, 2)))
parcels_in.sort()

# text in the style of the manual field: block (first 5 digits) + parcel numbers (next 2)
blocks = {}
for ref, a, sh in parcels_in:
    blocks.setdefault(ref[:5], []).append(ref[5:7])
cad_text = "; ".join(f"{b} (parcels {', '.join(p)})" for b, p in blocks.items())
cad_area = sum(a for _, a, _ in parcels_in)

CASE["site"]["cadastral_ref"] = cad_text
CASE["provenance"]["site"]["field_notes"]["cadastral_ref"] = (
    f"Catastro INSPIRE WFS (CP.CadastralParcel, {datetime.now().strftime('%Y-%m-%d')}): parcels with "
    f">= {int(PARCEL_MIN_SHARE * 100)} % of their area inside the boundary; {len(parcels_in)} parcels, "
    f"{cad_area} m2; full references: {', '.join(r for r, _, _ in parcels_in)}; " + SCRIPT_NOTE)
CASE["case"]["sources"].append(
    {"id": "S7", "title": "Catastro INSPIRE cadastral parcels (WFS)",
     "author_or_publisher": "Dirección General del Catastro",
     "date": datetime.now().strftime("%Y-%m-%d"), "type": "cadastre", "url": CATASTRO_WFS})
with open(case_path, "w", encoding="utf-8") as fh:
    json.dump(CASE, fh, ensure_ascii=False, indent=2)

log("cadastral_ref | manual: 79021 (parcels 61-64, 73-77, 87) | script:", cad_text)
log("parcels:", len(parcels_in), "| total area m2:", cad_area)
for ref, a, sh in parcels_in:
    log("  ", ref, "|", a, "m2 | share inside site:", sh)


# --- 16. geology, flood zones, zoning (point queries to public services) ---
import re
log("\nstep 16: geology, flood zones, zoning")

def http_get(url, data=None, timeout=60):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")

def wms_feature_info(base, layer, x, y, fmt):
    d = 25
    p = {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetFeatureInfo",
         "LAYERS": layer, "QUERY_LAYERS": layer, "STYLES": "", "CRS": "EPSG:25831",
         "BBOX": f"{x-d},{y-d},{x+d},{y+d}", "WIDTH": 51, "HEIGHT": 51,
         "I": 25, "J": 25, "INFO_FORMAT": fmt, "FEATURE_COUNT": 1}
    return http_get(base + "?" + urllib.parse.urlencode(p))

def sample_points(geom, n=4):
    # n x n grid over the bounding box, kept if inside the geometry, plus the centroid
    bb = geom.boundingBox()
    pts = [geom.centroid().asPoint()]
    for i in range(n):
        for j in range(n):
            x = bb.xMinimum() + (i + 0.5) * bb.width() / n
            y = bb.yMinimum() + (j + 0.5) * bb.height() / n
            if geom.contains(QgsGeometry.fromPointXY(QgsPointXY(x, y))):
                pts.append(QgsPointXY(x, y))
    return pts

svc_cache_path = os.path.join(SITE_DIR, "services_cache.json")
SVC = {}
if os.path.exists(svc_cache_path):
    with open(svc_cache_path, encoding="utf-8") as fh:
        SVC = json.load(fh)
def svc_save():
    with open(svc_cache_path, "w", encoding="utf-8") as fh:
        json.dump(SVC, fh, ensure_ascii=False)

PTS = sample_points(site_geom)
log("sample points inside the site:", len(PTS))

# 16a. geology: ICGC 1:50,000 geological units at the sample points
GEO_WMS = "https://geoserveis.icgc.cat/servei/catalunya/geologia-territorial/wms"
if "geology" not in SVC:
    SVC["geology"] = []
    for p in PTS:
        js = json.loads(wms_feature_info(GEO_WMS, "unitats-geologiques-50000", p.x(), p.y(),
                                         "application/geo+json"))
        props = js["features"][0]["properties"] if js.get("features") else {}
        SVC["geology"].append({"code": props.get("Codi"), "description": props.get("Descripcio")})
    svc_save()
units = {}
for u in SVC["geology"]:
    if u["code"]:
        units.setdefault(u["code"], {"n": 0, "description": u["description"]})["n"] += 1
main_code = max(units, key=lambda k: units[k]["n"]) if units else None
main_desc = (units[main_code]["description"] or "") if main_code else ""

# soil_type: first lithology word in the unit description (Catalan); permeability from soil_type
LITHO = [("made_ground", ("reblert", "antròpic", "antropic")),
         ("gravel", ("grava", "graves", "còdol", "codol", "conglomerat")),
         ("sand", ("sorra", "sorres", "arena", "arenes")),
         ("silt", ("llim", "llims", "lim", "loess")),
         ("clay", ("argila", "argiles", "lutita", "lutites", "marga", "margues")),
         ("rock", ("calcàri", "calcari", "granit", "pissarr", "gres", "dolomi", "esquist", "basalt"))]
low = main_desc.lower()
first = None
for soil, words in LITHO:
    for w in words:
        k = low.find(w)
        if k >= 0 and (first is None or k < first[1]):
            first = (soil, k)
soil_type = first[0] if first else "unknown"
# decision Ece (16 Nov 2026): clay together with silt / loess in the same unit -> silt (mixed fine soil)
has_clay = any(w in low for w in dict(LITHO)["clay"])
has_silt = any(w in low for w in dict(LITHO)["silt"])
if has_clay and has_silt:
    soil_type = "silt"
PERM = {"gravel": "permeable", "sand": "permeable", "silt": "semi_permeable",
        "clay": "impermeable", "rock": "unknown", "made_ground": "unknown", "unknown": "unknown"}
permeability = PERM[soil_type]
CASE["site"]["geology"] = {"soil_type": soil_type, "permeability": permeability}
CASE["provenance"]["site"]["field_notes"]["geology"] = (
    f"ICGC geological map 1:50,000 (unitats-geologiques-50000), {len(PTS)} points inside the site; "
    f"units {', '.join(f'{k} x{v['n']}' for k, v in units.items())}; main unit {main_code}: "
    f"'{main_desc[:160]}'; soil_type = first lithology named in the description, but clay + silt/loess "
    "together -> silt (decision Ece); permeability from "
    "soil_type (gravel/sand permeable, silt semi_permeable, clay impermeable); " + SCRIPT_NOTE)
log("geology | manual: silt / semi_permeable | script:", soil_type, "/", permeability)
log("   units:", {k: v["n"] for k, v in units.items()}, "| main:", main_code, "|", main_desc[:200])

# 16b. flood zones (SNCZI via IDEE INSPIRE WMS): raster value at sample points, the site edge
#      (25 m outside) and a test point in the Llobregat river bed (to read what 'flooded' looks like)
FLOOD_WMS = "https://servicios.idee.es/wms-inspire/riesgos-naturales/inundaciones"
FLOOD_LAYERS = {"T10": "NZ.Flood.FluvialT10", "T100": "NZ.Flood.FluvialT100",
                "T500": "NZ.Flood.FluvialT500", "marine_T100": "NZ.Flood.MarinaT100"}
def flood_value(layer, x, y):
    txt = wms_feature_info(FLOOD_WMS, layer, x, y, "text/plain")
    m = re.search(r"GRAY_INDEX\s*=\s*([-0-9.Ee+]+)", txt)
    return float(m.group(1)) if m else None
import re
edge_pts = [QgsPointXY(v.x(), v.y()) for v in site_geom.buffer(25, 4).vertices()][::max(1, len(list(site_geom.buffer(25, 4).vertices())) // 8)]
test_pt = to_crs(QgsGeometry.fromPointXY(QgsPointXY(2.0533, 41.3466)), "EPSG:4326", CRS).asPoint()
if "flood" not in SVC:
    SVC["flood"] = {}
    for key, layer in FLOOD_LAYERS.items():
        SVC["flood"][key] = {
            "site": [flood_value(layer, p.x(), p.y()) for p in PTS],
            "edge": [flood_value(layer, p.x(), p.y()) for p in edge_pts],
            "test_llobregat": flood_value(layer, test_pt.x(), test_pt.y())}
    svc_save()
for key, v in SVC["flood"].items():
    log(f"flood {key} | site values: {sorted(set(v['site']))} | edge: {sorted(set(v['edge']))} "
        f"| Llobregat test: {v['test_llobregat']}")

# 16c. zoning: MUC qualifications (Diputació de Barcelona ArcGIS service, Jan 2023) intersecting the site
MUC = "https://gissrv.diba.cat/arcgis/rest/services/CARTOBASE/MUC/MapServer"
if "zoning" not in SVC:
    mg = QgsGeometry(site_geom)
    mg.convertToMultiType()
    rings = [[[pt.x(), pt.y()] for pt in ring] for poly in mg.asMultiPolygon() for ring in poly]
    body = urllib.parse.urlencode({
        "geometry": json.dumps({"rings": rings, "spatialReference": {"wkid": 25831}}),
        "geometryType": "esriGeometryPolygon", "inSR": 25831, "outSR": 25831,
        "spatialRel": "esriSpatialRelIntersects", "outFields": "*", "returnGeometry": "true",
        "f": "json"}).encode()
    SVC["zoning"] = json.loads(http_get(MUC + "/1/query", data=body, timeout=120))
    svc_save()
zone_area = {}
zone_desc = {}
def esri_polygon(rings):
    # Esri JSON rings: clockwise = outer ring, counter-clockwise = hole
    outer, holes = [], []
    for r in rings:
        signed = sum(r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1] for i in range(len(r) - 1))
        poly = QgsGeometry.fromPolygonXY([[QgsPointXY(x, y) for x, y in r]])
        (outer if signed < 0 else holes).append(poly)
    g = QgsGeometry.unaryUnion(outer) if outer else QgsGeometry()
    for h in holes:
        g = g.difference(h)
    return g

for f in SVC["zoning"].get("features", []):
    g = esri_polygon(f["geometry"]["rings"])
    a = g.intersection(site_geom).area()
    if a <= 0:
        continue
    code = f["attributes"].get("C_QUAL_MUC")
    zone_area[code] = zone_area.get(code, 0) + a
    zone_desc[code] = f["attributes"].get("D_QUAL_AJT")
zoning_text = "MUC (Jan 2023): " + "; ".join(
    f"{c} {zone_desc[c]} {round(a / area * 100)} %"
    for c, a in sorted(zone_area.items(), key=lambda kv: -kv[1]) if a / area >= 0.01)
if SVC["zoning"].get("features"):
    log("MUC fields:", list(SVC["zoning"]["features"][0]["attributes"].keys()),
        "| features:", len(SVC["zoning"]["features"]))
log("after.zoning | manual: MPGM Can Batlló–Magòria 2017, qualifications 5, 6b, 6b/p, 6b/18, 7b, 18, 18/HS"
    " | script:", zoning_text)
CASE["after"]["zoning"] = zoning_text
CASE["provenance"]["after"]["field_notes"]["zoning"] = (
    "Mapa Urbanístic de Catalunya, qualification layer (Diputació de Barcelona ArcGIS service, "
    "updated Jan 2023); share of site area per MUC code (>= 1 %); municipal plan codes not included; "
    "before.zoning (plan in force at vacancy) stays manual; " + SCRIPT_NOTE)
CASE["case"]["sources"] += [
    {"id": "S8", "title": "Mapa geològic de Catalunya 1:50.000 (WMS Geologia territorial)",
     "author_or_publisher": "ICGC", "date": "2026", "type": "dataset", "url": GEO_WMS},
    {"id": "S9", "title": "Mapa Urbanístic de Catalunya (MUC), qualificació",
     "author_or_publisher": "Generalitat de Catalunya / Diputació de Barcelona", "date": "2023-01",
     "type": "plan", "url": MUC}]
with open(case_path, "w", encoding="utf-8") as fh:
    json.dump(CASE, fh, ensure_ascii=False, indent=2)

# 16b (rule). flood_risk from SNCZI depth rasters (read on 16 Nov 2026 with a Llobregat test point:
# flooded cells carry a water depth in m, e.g. 0.36 at T100; 999 and very negative values = not flooded)
def flooded(v):
    return v is not None and 0 <= v < 900
fl = SVC["flood"]["T100"]
site_in = any(flooded(v) for v in fl["site"]) or any(flooded(v) for v in SVC["flood"]["marine_T100"]["site"])
edge_in = any(flooded(v) for v in fl["edge"]) or any(flooded(v) for v in SVC["flood"]["marine_T100"]["edge"])
flood_risk = "inside_flood_zone" if site_in else "edge_of_flood_zone" if edge_in else "outside"
CASE["site"]["flood_risk"] = flood_risk
CASE["site"]["flood_return_period"] = "T100"
CASE["provenance"]["site"]["field_notes"]["flood_risk"] = (
    f"SNCZI flood zones via IDEE INSPIRE WMS (fluvial and marine T100), {len(PTS)} points inside the site "
    f"and {len(edge_pts)} points 25 m outside; flooded = water depth value 0-900 (999 / no-data = not "
    "flooded); covers mapped river and coastal reaches only, not urban runoff; " + SCRIPT_NOTE)
CASE["case"]["sources"].append(
    {"id": "S10", "title": "SNCZI flood zones (IDEE INSPIRE WMS riesgos-naturales/inundaciones)",
     "author_or_publisher": "MITECO / IGN", "date": datetime.now().strftime("%Y-%m-%d"),
     "type": "dataset", "url": FLOOD_WMS})
with open(case_path, "w", encoding="utf-8") as fh:
    json.dump(CASE, fh, ensure_ascii=False, indent=2)
log("flood_risk | manual: unknown (viewer did not load) | script:", flood_risk, "(T100)")

with open(os.path.join(OUT_DIR, "comparison.csv"), "a", newline="", encoding="utf-8") as fh:
    wr = csv.writer(fh)
    wr.writerow(["", "cadastral_ref", "79021 (parcels 61-64, 73-77, 87)", cad_text, ""])
    wr.writerow(["", "geology", "silt / semi_permeable", f"{soil_type} / {permeability}", ""])
    wr.writerow(["", "flood_risk", "unknown", flood_risk, ""])
    wr.writerow(["", "after.zoning", "MPGM 2017: 5, 6b, 6b/p, 6b/18, 7b, 18, 18/HS", zoning_text, ""])

for block in ("case", "site", "before", "after"):
    vals = list(leaves({k: v for k, v in CASE[block].items() if k != "sources"}))
    filled = sum(1 for v in vals if v not in ("", None, []))
    log(f"FINAL {block}: {filled} of {len(vals)} fields filled by the script")
log("Saved:", case_path)


# --- 17. surroundings: neighbourhood indicators from the Barcelona padró (Open Data BCN) ---
# same source and definitions for both years (1 January of YEAR_BEFORE and YEAR_AFTER)
log("\nstep 17: surroundings (Open Data BCN, padró)")
BCN_API = "https://opendata-ajuntament.barcelona.cat/data/api/action/"
BCN_DIR = os.path.join(GIS_DIR, "auto_case", "_bcn_opendata")      # shared by all Barcelona sites
os.makedirs(BCN_DIR, exist_ok=True)

def bcn_csv(dataset, year):
    # download (once) the CSV of a padró dataset for a year; returns a list of dicts
    path = os.path.join(BCN_DIR, f"{year}_{dataset}.csv")
    if not os.path.exists(path):
        pkg = json.loads(http_get(BCN_API + "package_show?" + urllib.parse.urlencode({"id": dataset})))
        res = [r for r in pkg["result"]["resources"]
               if str(year) in r.get("name", "") and r.get("format", "").upper() == "CSV"]
        if not res:
            raise Exception(f"no CSV for {dataset} {year}")
        req = urllib.request.Request(res[0]["url"], headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=180) as r, open(path, "wb") as fh:
            fh.write(r.read())
    with open(path, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))

def num(v):
    # '..' = value hidden for privacy (small counts) -> counted as 0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0

# code lists (pad_dimensions.csv): pick codes by their labels
dim_path = os.path.join(BCN_DIR, "pad_dimensions.csv")
if not os.path.exists(dim_path):
    pkg = json.loads(http_get(BCN_API + "package_show?id=pad-dimensions"))
    req = urllib.request.Request(pkg["result"]["resources"][0]["url"], headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as r, open(dim_path, "wb") as fh:
        fh.write(r.read())
with open(dim_path, encoding="utf-8-sig") as fh:
    dim_rows = list(csv.DictReader(fh))
log("pad_dimensions columns:", list(dim_rows[0].keys()))

def codes_for(dimension, keep):
    # rows of one dimension (Codi_Dimensio or Desc_Dimensio = name); code = Codi_Valor;
    # label = English / Catalan / Spanish descriptions together (for keyword matching)
    out = {}
    for row in dim_rows:
        if dimension.lower() not in (row.get("Codi_Dimensio", "").strip().lower(),
                                     row.get("Desc_Dimensio", "").strip().lower()):
            continue
        label = " | ".join(row.get(k, "") for k in ("Desc_Valor_EN", "Desc_Valor_CA", "Desc_Valor_ES"))
        if keep(label.lower().replace("\xa0", " ")):
            out[row["Codi_Valor"].strip()] = row.get("Desc_Valor_EN") or row.get("Desc_Valor_CA")
    return out

def all_labels(dimension):
    return {row["Codi_Valor"].strip(): row.get("Desc_Valor_EN") or row.get("Desc_Valor_CA")
            for row in dim_rows
            if dimension.lower() in (row.get("Codi_Dimensio", "").strip().lower(),
                                     row.get("Desc_Dimensio", "").strip().lower())}

for d in ("LLOC_NAIX", "NIV_EDUCA_esta", "EDAT_Q"):
    log("labels", d, ":", all_labels(d))

# labels checked 16 Nov 2026: LLOC_NAIX 1 Barcelona, 2 rest of Catalonia, 3 rest of Spain,
# 4 rest of EU, 5 rest of world, 6 not available; NIV_EDUCA_esta 5 = tertiary, 6 = not available
FOREIGN = codes_for("LLOC_NAIX", lambda l: l.startswith("rest of european union") or l.startswith("rest of world"))
HIGHER = codes_for("NIV_EDUCA_esta", lambda l: l.startswith("tertiary"))
NA_BORN = codes_for("LLOC_NAIX", lambda l: l.startswith("not available"))
NA_EDU = codes_for("NIV_EDUCA_esta", lambda l: l.startswith("not available"))
def is_65_plus(l):
    m = re.search(r"(\d+)", l)
    return bool(m) and int(m.group(1)) >= 65
OLD = codes_for("EDAT_Q", is_65_plus)
log("codes used | born abroad:", FOREIGN, "| higher education:", HIGHER, "| age 65+:", list(OLD.values()))

BARRI = admin.get("10", "")
def barri_rows(rows):
    return [r for r in rows if slugify(r.get("Nom_Barri", "")) == slugify(BARRI)]

# barri area from its OSM outline (Nominatim), city area from step 13
barri_id = next((el["id"] for el in osm["elements"]
                 if el.get("tags", {}).get("admin_level") == "10"
                 and el.get("tags", {}).get("boundary") == "administrative"), None)
barri_poly = rc_get("barri", lambda: nominatim_polygon(f"R{barri_id}"))
bw = ogr.CreateGeometryFromJson(json.dumps(barri_poly["features"][0]["geometry"])).ExportToWkt()
barri_km2 = to_crs(QgsGeometry.fromWkt(bw), "EPSG:4326", CRS).area() / 1e6
log("barri:", BARRI, "| area km2:", round(barri_km2, 3), "| city km2:", round(muni_area_km2, 2))

def indicators(year):
    pop = bcn_csv("pad_mdbas", year)
    born = bcn_csv("pad_mdbas_lloc-naix_sexe", year)
    edu = bcn_csv("pad_mdbas_niv-educa-esta_sexe", year)
    alone = bcn_csv("pad_sol_mdb_sexe_edat-q", year)
    age = bcn_csv("pad_mdbas_edat-q", year)
    def tot(rows, cond=lambda r: True):
        return sum(num(r["Valor"]) for r in rows if cond(r))
    out = {}
    for area_name, pick, km2 in (("barri", barri_rows, barri_km2), ("city", lambda x: x, muni_area_km2)):
        p = tot(pick(pop))
        out[area_name] = {
            "population": p,
            "population_density": round(p / km2),
            "foreign_born_pct": round(tot(pick(born), lambda r: r["LLOC_NAIX"] in FOREIGN)
                                      / tot(pick(born), lambda r: r["LLOC_NAIX"] not in NA_BORN) * 100, 1),
            "higher_education_pct": round(tot(pick(edu), lambda r: r["NIV_EDUCA_esta"] in HIGHER)
                                          / tot(pick(edu), lambda r: r["NIV_EDUCA_esta"] not in NA_EDU) * 100, 1),
            "elderly_living_alone_pct": round(tot(pick(alone), lambda r: r["EDAT_Q"] in OLD)
                                              / tot(pick(age), lambda r: r["EDAT_Q"] in OLD) * 100, 1),
        }
    return out

SURR = {}
for block, year in (("before", YEAR_BEFORE), ("after", YEAR_AFTER)):
    ind = indicators(year)
    SURR[year] = ind
    s = CASE[block]["surroundings"]
    s["year"] = year
    s["spatial_unit"] = f"neighbourhood (barri {BARRI})"
    s["comparison_area"] = f"{admin.get('8', '')} (city)"
    s["indicators"] = [
        {"name": n, "value": ind["barri"][n], "comparison_value": ind["city"][n],
         "source": f"Open Data BCN, padró 1 Jan {year} ({ds}); " + SCRIPT_NOTE}
        for n, ds in (("population_density", "pad_mdbas; area from OSM outline"),
                      ("foreign_born_pct", "pad_mdbas_lloc-naix_sexe"),
                      ("higher_education_pct", "pad_mdbas_niv-educa-esta_sexe, population 16+"),
                      ("elderly_living_alone_pct", "pad_sol_mdb_sexe_edat-q / pad_mdbas_edat-q, 65+"))]
    CASE["provenance"][block]["field_notes"]["surroundings"] = (
        f"indicators from the municipal register (padró) 1 Jan {year}, same source both years; "
        "foreign-born = born in the rest of the EU or the rest of the world; higher education = tertiary "
        "(16+); 'not available' excluded from the denominators; elderly living alone = people 65+ "
        "living alone / people 65+; '..' (hidden small counts) counted as 0; income, unemployment, property value and safety not "
        "automated (no series for both years); " + SCRIPT_NOTE)
CASE["case"]["sources"].append(
    {"id": "S11", "title": "Padró municipal d'habitants (Open Data BCN)",
     "author_or_publisher": "Ajuntament de Barcelona", "date": f"{YEAR_BEFORE}; {YEAR_AFTER}",
     "type": "dataset", "url": "https://opendata-ajuntament.barcelona.cat"})
with open(case_path, "w", encoding="utf-8") as fh:
    json.dump(CASE, fh, ensure_ascii=False, indent=2)

MANUAL_SURR = {YEAR_BEFORE: {"population_density": (32122, 15960), "foreign_born_pct": (17.2, 21.8),
                             "higher_education_pct": (16.9, 24.9), "elderly_living_alone_pct": (23.2, 25.6)},
               YEAR_AFTER: {"population_density": (36386, 16904), "foreign_born_pct": (30.6, 34.6),
                            "higher_education_pct": (None, None), "elderly_living_alone_pct": (None, None)}}
log("\nyear | indicator | manual barri / city | script barri / city")
with open(os.path.join(OUT_DIR, "comparison.csv"), "a", newline="", encoding="utf-8") as fh:
    wr = csv.writer(fh)
    for year in (YEAR_BEFORE, YEAR_AFTER):
        for n, (mb, mc) in MANUAL_SURR[year].items():
            sb, sc = SURR[year]["barri"][n], SURR[year]["city"][n]
            log(year, "|", n, "|", mb, "/", mc, "|", sb, "/", sc)
            wr.writerow([year, n + " (barri)", mb, sb, None if mb is None else round(sb - mb, 1)])

for block in ("case", "site", "before", "after"):
    vals = list(leaves({k: v for k, v in CASE[block].items() if k != "sources"}))
    filled = sum(1 for v in vals if v not in ("", None, []))
    log(f"FINAL {block}: {filled} of {len(vals)} fields filled by the script")
log("Saved:", case_path)


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