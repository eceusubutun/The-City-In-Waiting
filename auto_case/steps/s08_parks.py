# ==============================================================
# s08_parks.py - parks: OSM leisure=park around the site, kept per year if green
# Part of auto_case (split from auto_case.py v0.25, 20 Nov 2026). Run through main.py.
# uses (from earlier steps): CRS, IRC_LAYERS, R, SITE_DIR, buffer_geom, site_geom
# makes (used by later steps): MANUAL_PARKS, PARK_MIN_GREEN, bb, names
# shared functions (to_crs, overpass, zonal, log ...) are in helpers.py
# ==============================================================
# --- 8. parks: OSM leisure=park around the site, filtered per year by green share ---
from qgis.core import QgsField, QgsFields, QgsPointXY, QgsWkbTypes
from qgis.PyQt.QtCore import QVariant

PARK_MIN_GREEN = 0.1     # a park counts in a year only if >= 10 % of it is green

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
