# ==============================================================
# main.py  -  auto_case: boundary file + name -> case JSON   (v0.26, 20 Nov 2026)
# Run THIS file in the QGIS Python console editor (open it, press the green Run button).
# It loads helpers.py and settings.py, then runs the steps in steps\ one after the other,
# all in the same QGIS console session, so later steps can use what earlier steps made.
#
# Files:  settings.py  - site name, boundary file, template (the only file you change per site)
#         helpers.py   - shared functions (coordinates, OSM, WMS, rasters, logging)
#         steps\s02 ... s18  - one file per step; each starts with a note of what it uses / makes
# Outputs: C:\gis\auto_case\<site>\<run>\<site>.json + comparison.csv + log.txt (as before)
# Same calculations as auto_case.py v0.25; only the structure changed.
# ==============================================================
import os, time, traceback
from datetime import datetime
from qgis.PyQt.QtWidgets import QApplication

AUTO_DIR = r"C:\gis\script\auto_case"        # folder of this file

STEPS = [
    "s02_boundary",              # boundary, area, shape index, centre
    "s03_osm_location",          # city, country, neighbourhood (OSM)
    "s04_case_json",             # case JSON from the category template
    "s06_orthophotos",           # ICGC infrared orthophotos 2010 / 2025
    "s07_ndvi",                  # NDVI, vegetated share, green share of the ring
    "s08_parks",                 # parks around the site
    "s09_nearest_vacant",        # nearest other vacant site (Urban Atlas)
    "s10_write_green",           # vegetation + green spaces into the JSON
    "s11_connectivity_water",    # bus, metro, main road, services, centre, water
    "s12_heights_landcover",     # heights, land cover, retained fabric, slope
    "s13_rules_site",            # parcel_shape, location, urban_network, biodiversity
    "s14_rules_context",         # succession, context, sensitivity, end state
    "s15_cadastre",              # cadastral parcels
    "s16_geology_flood_zoning",  # geology, flood risk, zoning
    "s17_surroundings",          # padró indicators (Barcelona only)
    "s18_rules_layout_surface",  # enclosure, layout, substrate, infrastructure, reclaimed area
]
START_AT = STEPS[0]     # to re-run from a later step in the SAME QGIS session, put its name here
STOP_AFTER = STEPS[-1]  # to stop early, put a step name here


def run_file(path):
    with open(path, encoding="utf-8") as fh:
        exec(compile(fh.read(), path, "exec"), globals())


run_file(os.path.join(AUTO_DIR, "helpers.py"))
run_file(os.path.join(AUTO_DIR, "settings.py"))

if START_AT == STEPS[0]:
    # new run: one output folder per run (cache per site is kept between runs)
    SLUG = slugify(SITE_NAME)
    SITE_DIR = os.path.join(GIS_DIR, "auto_case", SLUG)
    OUT_DIR = os.path.join(SITE_DIR, datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(OUT_DIR, exist_ok=True)
    print("Site:", SITE_NAME, "| output:", OUT_DIR)
elif "CASE" not in globals():
    raise Exception("START_AT is a later step, but the earlier steps have not run in this QGIS session. "
                    "Set START_AT = STEPS[0].")
else:
    print("Continuing run", OUT_DIR, "from", START_AT)

todo = STEPS[STEPS.index(START_AT):STEPS.index(STOP_AFTER) + 1]
t_all = time.time()
for step in todo:
    t0 = time.time()
    print(f"\n========== {step} ==========")
    try:
        run_file(os.path.join(AUTO_DIR, "steps", step + ".py"))
    except Exception:
        traceback.print_exc()
        print(f"\nSTOPPED in {step}. Fix it, then set START_AT = '{step}' and run main.py again "
              "(the earlier steps stay in memory in this QGIS session).")
        break
    print(f"---------- {step} done in {time.time() - t0:.0f} s")
    QApplication.processEvents()          # lets QGIS redraw between steps
else:
    print(f"\nAll steps done in {(time.time() - t_all) / 60:.1f} min. Case JSON: {case_path}")
