# ==============================================================
# s17_surroundings.py - surroundings: neighbourhood indicators (Open Data BCN padró)
# Part of auto_case (split from auto_case.py v0.25, 20 Nov 2026). Run through main.py.
# uses (from earlier steps): CASE, CRS, GIS_DIR, OUT_DIR, SCRIPT_NOTE, USER_AGENT, YEAR_AFTER,
#                            YEAR_BEFORE, admin, case_path, muni_area_km2, osm, rc_get
# makes (used by later steps): -
# shared functions (to_crs, overpass, zonal, log ...) are in helpers.py
# ==============================================================
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
