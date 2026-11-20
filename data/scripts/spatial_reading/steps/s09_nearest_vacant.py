# ==============================================================
# s09_nearest_vacant.py - nearest other vacant site (Urban Atlas 2012, code 13400)
# Part of auto_case (split from auto_case.py v0.25, 20 Nov 2026). Run through main.py.
# uses (from earlier steps): CRS, GIS_DIR, site_geom
# makes (used by later steps): nearest_vacant
# shared functions (to_crs, overpass, zonal, log ...) are in helpers.py
# ==============================================================
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
