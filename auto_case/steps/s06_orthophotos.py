# ==============================================================
# s06_orthophotos.py - download infrared orthophotos (ICGC WMS) for the site and the 500 m buffer
# Part of auto_case (split from auto_case.py v0.25, 20 Nov 2026). Run through main.py.
# uses (from earlier steps): BUFFER_M, IRC_LAYERS, SITE_DIR, site_geom
# makes (used by later steps): IRC_BUF, IRC_SITE, buffer_geom
# shared functions (to_crs, overpass, zonal, log ...) are in helpers.py
# ==============================================================
# --- 6. download infrared orthophotos (ICGC WMS), cached per site ---
import math
import shutil
from osgeo import gdal
from qgis.core import QgsRasterLayer

DATA_DIR = os.path.join(SITE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

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
