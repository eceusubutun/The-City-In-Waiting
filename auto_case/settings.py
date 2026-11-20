# ==============================================================
# settings.py - the only file you change per site
# ==============================================================
# --- site ---
SITE_NAME = "Can Batlló"
CASE_ID = "1.1-BCN-01"
BOUNDARY_FILE = r"C:\gis\can_batllo_boundary_25831.gpkg"   # gpkg, shp or kml
TEMPLATE_JSON = r"C:\Users\eceus\OneDrive\Desktop\main folders\classes\iaac\thesis\The-City-In-Waiting\data\categories\1.1-former-industrial-service-estates.json"
MANUAL_JSON = r"C:\Users\eceus\OneDrive\Desktop\main folders\classes\iaac\thesis\The-City-In-Waiting\data\cases\can_batllo.json"  # only for the test; set to None for new sites

CITY_CENTRE = ("Plaça de Catalunya", 41.38701, 2.17000)  # name, lat, lon (for distance_to_centre_km)

GIS_DIR = r"C:\gis"
CRS = "EPSG:25831"
USER_AGENT = "IAAC-MAA02-thesis-script"


# --- fixed settings (same for every site) ---
WMS_URL = "https://geoserveis.icgc.cat/servei/catalunya/orto-territorial/wms"
IRC_LAYERS = {2010: "ortofoto_25cm_infraroig_2010",
              2025: "ortofoto_25cm_infraroig_2025"}
BUFFER_M = 500
TILE_PX = 2000                      # max image size per WMS request
OVERPASS_SERVERS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
