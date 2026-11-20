# ==============================================================
# s07_ndvi.py - NDVI of the site (25 cm) and green share of the 500 m ring (1 m)
# Part of auto_case (split from auto_case.py v0.25, 20 Nov 2026). Run through main.py.
# uses (from earlier steps): IRC_BUF, IRC_LAYERS, IRC_SITE, buffer_geom, site_geom
# makes (used by later steps): MANUAL_NDVI, R, ring_geom, ring_lyr, site_lyr, veg_b
# shared functions (to_crs, overpass, zonal, log ...) are in helpers.py
# ==============================================================
# --- 7. NDVI: site (25 cm) and green share of the 500 m ring (1 m) ---
import numpy as np
import processing

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
