# ==============================================================
# s02_boundary.py - boundary: read the file, merge parts, area, shape index, centre
# Part of auto_case (split from auto_case.py v0.25, 20 Nov 2026). Run through main.py.
# uses (from earlier steps): BOUNDARY_FILE, CRS
# makes (used by later steps): area, bnd, lat, lon, shape_index, site_geom
# shared functions (to_crs, overpass, zonal, log ...) are in helpers.py
# ==============================================================
# --- 2. boundary: read the file, merge parts, convert to metres ---
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
