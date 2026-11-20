# ==============================================================
# s15_cadastre.py - cadastral parcels (Catastro INSPIRE WFS)
# Part of auto_case (split from auto_case.py v0.25, 20 Nov 2026). Run through main.py.
# uses (from earlier steps): CASE, CRS, SCRIPT_NOTE, SITE_DIR, USER_AGENT, case_path, site_geom
# makes (used by later steps): cad_text
# shared functions (to_crs, overpass, zonal, log ...) are in helpers.py
# ==============================================================
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
