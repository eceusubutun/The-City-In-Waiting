# ==============================================================
# helpers.py - functions shared by the steps of auto_case (no calculations run here)
# Loaded first by main.py. The functions use the settings (CRS, USER_AGENT, OUT_DIR ...)
# from settings.py when they are called.
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
import math
import time
import re
import csv
import glob
import shutil
import numpy as np
import processing
from osgeo import gdal, ogr
from qgis.core import QgsRasterLayer, QgsField, QgsFields, QgsPointXY, QgsWkbTypes, QgsFeatureRequest
from qgis.PyQt.QtCore import QVariant


# --- geometry and coordinates ---

def to_crs(g, src, dst):
    tr = QgsCoordinateTransform(QgsCoordinateReferenceSystem(src),
                                QgsCoordinateReferenceSystem(dst),
                                QgsProject.instance())
    g = QgsGeometry(g)
    g.transform(tr)
    return g

def geom_layer(geom, name):
    # one geometry -> memory polygon layer (needed by zonal statistics)
    lyr = QgsVectorLayer("MultiPolygon?crs=" + CRS, name, "memory")
    g = QgsGeometry(geom)
    g.convertToMultiType()
    f = QgsFeature()
    f.setGeometry(g)
    lyr.dataProvider().addFeatures([f])
    return lyr

def snapped_extent(geom, step):
    # bounding box rounded outwards to a multiple of step (keeps grids aligned)
    bb = geom.boundingBox()
    return (math.floor(bb.xMinimum() / step) * step, math.floor(bb.yMinimum() / step) * step,
            math.ceil(bb.xMaximum() / step) * step, math.ceil(bb.yMaximum() / step) * step)

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


# --- text, files and logging ---

def slugify(text):
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(c if c.isalnum() else "_" for c in t.lower()).strip("_")

def out_path(name):
    return os.path.join(OUT_DIR, name)

def log(*parts):
    # print and also write to log.txt (readable even if QGIS closes)
    text = " ".join(str(p) for p in parts)
    print(text)
    with open(os.path.join(OUT_DIR, "log.txt"), "a", encoding="utf-8") as fh:
        fh.write(text + "\n")

def leaves(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from leaves(v)
    elif isinstance(x, list) and x and isinstance(x[0], dict):
        for v in x:
            yield from leaves(v)
    else:
        yield x

def num(v):
    # '..' = value hidden for privacy (small counts) -> counted as 0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0

def label(el):
    if el is None:
        return "none found"
    t = el.get("tags", {})
    kind = next((f"{k}={t[k]}" for k in ("highway", "railway", "shop", "amenity",
                                        "natural", "waterway", "place") if k in t), "")
    return f'{t.get("name", "(no name)")} [{kind}]'


# --- web services (OSM, WMS, Nominatim) ---

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

def http_get(url, data=None, timeout=60):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")

def nominatim_polygon(osm_id):
    # simplified outline of an OSM area from Nominatim (small answer, already assembled)
    params = urllib.parse.urlencode({"osm_ids": osm_id, "format": "geojson",
                                     "polygon_geojson": 1, "polygon_threshold": 0.0005})
    req = urllib.request.Request("https://nominatim.openstreetmap.org/lookup?" + params,
                                 headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

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

def wms_feature_info(base, layer, x, y, fmt):
    d = 25
    p = {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetFeatureInfo",
         "LAYERS": layer, "QUERY_LAYERS": layer, "STYLES": "", "CRS": "EPSG:25831",
         "BBOX": f"{x-d},{y-d},{x+d},{y+d}", "WIDTH": 51, "HEIGHT": 51,
         "I": 25, "J": 25, "INFO_FORMAT": fmt, "FEATURE_COUNT": 1}
    return http_get(base + "?" + urllib.parse.urlencode(p))


# --- rasters and zonal statistics ---

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

def project_layer_path(name):
    lyrs = QgsProject.instance().mapLayersByName(name)
    if not lyrs:
        raise Exception("Layer not found in the project: " + name)
    return lyrs[0].source().split("|")[0]

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

def zonal_all(raster_path, polygon_layer, prefix):
    out = processing.run("native:zonalstatisticsfb", {
        "INPUT": polygon_layer, "INPUT_RASTER": raster_path, "RASTER_BAND": 1,
        "COLUMN_PREFIX": prefix, "STATISTICS": [2], "OUTPUT": "TEMPORARY_OUTPUT",
    })["OUTPUT"]
    return [(f, f[prefix + "mean"]) for f in out.getFeatures()]
