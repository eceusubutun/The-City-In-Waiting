# ==============================================================
# doc_sources.py  -  step D1: find candidate sources for a case
# v0.2, 16 Nov 2026
# Finds sources from open, citable catalogues (no LLM, no API key):
#   1. the sources already listed in the manual case JSON
#   2. Wikipedia (ca / es / en): the article and the external links it cites
#   3. OpenAlex: academic papers, reports and books that name the site
# Every candidate gets a reliability tier; you choose what to keep.
# Output: C:\gis\auto_case\<slug>\documents\sources_candidates.csv
# Runs in the QGIS Python console or any Python 3.
# ==============================================================
import os
import csv
import json
import time
import unicodedata
import urllib.request
import urllib.parse
from urllib.parse import urlparse

# --- 1. settings ---
SITE_NAME = "Can Batlló"
CITY = "Barcelona"
EXTRA_TERMS = ["Bordeta"]          # other words that often appear with the site name
MANUAL_JSON = r"C:\Users\eceus\OneDrive\Desktop\main folders\classes\iaac\thesis\The-City-In-Waiting\data\cases\can_batllo.json"
GIS_DIR = r"C:\gis"
USER_AGENT = "IAAC-MAA02-thesis-script (research; contact via IAAC)"


def slugify(text):
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(c if c.isalnum() else "_" for c in t.lower()).strip("_")

DOC_DIR = os.path.join(GIS_DIR, "auto_case", slugify(SITE_NAME), "documents")
os.makedirs(DOC_DIR, exist_ok=True)

def get_json(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# --- 2. reliability tiers (by web domain or catalogue) ---
# 1 official: government, planning registers, statistics, mapping agencies
# 2 academic: peer-reviewed papers, books, research reports (OpenAlex / DOI)
# 3 institutional: universities, NGOs, the project's own organisation, encyclopaedias
# 4 press
# 5 other (blogs, social media, unknown)
OFFICIAL = ("barcelona.cat", "bcn.cat", "gencat.cat", "icgc.cat", "amb.cat", "diba.cat",
            "boe.es", "gob.es", "europa.eu", "ine.es", "idescat.cat", "catastro",
            "hdl.handle.net/11703")          # BCNROC = Barcelona City Council repository
ENCYCLOPAEDIA = ("wikipedia.org", "enciclopedia.cat")
NOISE = ("geohack", "wmflabs", "toolforge", "openstreetmap.org", "osmsurround", "virtuelle-loipe",
         "worldcat", "books.google", "facebook.com", "twitter.com", "youtube.com", "instagram.com")
ACADEMIC = ("doi.org", "openalex.org", "researchgate", "academia.edu", "jstor", "springer",
            "elsevier", "sciencedirect", "tandfonline", "wiley", "sagepub", "mdpi", "upc.edu",
            "uab.cat", "ub.edu", "upf.edu", "raco.cat", "dialnet", "recercat", "core.ac.uk")
PRESS = ("beteve.cat", "elperiodico", "lavanguardia", "elpais", "ara.cat", "naciodigital",
         "elnacional", "eldiario", "timeout", "publico.es", "elmundo", "abc.es", "efe",
         "ccma.cat", "betevé", "construible", "elcritic", "directa.cat", "catalunyapress")

def tier_of(url, found_by):
    host = urlparse(url).netloc.lower()
    full = url.lower()
    if "web.archive.org" in host:                 # archived copy: judge the original address
        orig = full.split("/http", 1)[-1]
        host = urlparse("http" + orig).netloc.lower() if orig else host
        full = "http" + orig
    if any(k in full for k in OFFICIAL):
        return 1, "report"
    if found_by == "openalex":
        return 2, "paper"
    if any(k in host for k in ENCYCLOPAEDIA):
        return 3, "other"
    if any(k in host for k in ACADEMIC):
        return 2, "paper"
    if any(k in host for k in PRESS):
        return 4, "press"
    if "wikipedia" in host or host.endswith(".org") or host.endswith(".edu"):
        return 3, "project_page" if slugify(SITE_NAME).replace("_", "") in host.replace(".", "") else "other"
    return 5, "other"

CANDIDATES = {}      # url -> record

NAME_WORDS = [slugify(SITE_NAME)] + [slugify(t) for t in EXTRA_TERMS]

def add(url, title, found_by, extra=""):
    if not url or url in CANDIDATES:
        return
    if any(k in url.lower() for k in NOISE):
        return                                   # map tools, social media, catalogue stubs
    tier, typ = tier_of(url, found_by)
    title = (title or "").strip()[:200]
    # suggestion only - you decide in the keep column:
    # official, academic and project sources; academic works only if the site is in the title
    named = any(w.replace("_", "") in slugify(title).replace("_", "") for w in NAME_WORDS)
    if found_by == "manual_case":
        suggest = "y"
    elif found_by == "openalex":
        suggest = "y" if named else "check: site not in title"
    elif tier in (1, 2) or typ == "project_page":
        suggest = "y"
    elif tier == 4:
        suggest = "maybe (press)"
    else:
        suggest = ""
    CANDIDATES[url] = {"suggest": suggest, "tier": tier, "type": typ, "title": title,
                       "url": url, "found_by": found_by, "note": extra}


# --- 3. sources already used in the manual case ---
if MANUAL_JSON and os.path.exists(MANUAL_JSON):
    with open(MANUAL_JSON, encoding="utf-8") as fh:
        man = json.load(fh)
    for s in man.get("case", {}).get("sources", []):
        add(s.get("url"), s.get("title"), "manual_case", s.get("id", ""))
    print("manual sources:", len(CANDIDATES))


# --- 4. Wikipedia: article text + the external references it cites ---
for lang in ("ca", "es", "en"):
    api = f"https://{lang}.wikipedia.org/w/api.php"
    try:
        res = get_json(api + "?" + urllib.parse.urlencode({
            "action": "query", "list": "search", "srsearch": f'"{SITE_NAME}" {CITY}',
            "format": "json", "srlimit": 3}))
        for hit in res["query"]["search"]:
            title = hit["title"]
            if slugify(SITE_NAME) not in slugify(title):
                continue                                     # only articles about the site
            page_url = f"https://{lang}.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
            add(page_url, f"Wikipedia ({lang}): {title}", "wikipedia")
            links = get_json(api + "?" + urllib.parse.urlencode({
                "action": "query", "titles": title, "prop": "extlinks", "ellimit": 500,
                "format": "json"}))
            for page in links["query"]["pages"].values():
                for l in page.get("extlinks", []):
                    u = l.get("*") or l.get("url")
                    if u and u.startswith("http"):
                        add(u, "", f"wikipedia_{lang}_reference", title)
        time.sleep(1)
    except Exception as e:
        print("Wikipedia", lang, "failed:", e)
print("after Wikipedia:", len(CANDIDATES))


# --- 5. OpenAlex: academic works that name the site ---
for term in [f'"{SITE_NAME}"'] + [f'"{SITE_NAME}" {t}' for t in EXTRA_TERMS]:
    try:
        res = get_json("https://api.openalex.org/works?" + urllib.parse.urlencode({
            "search": term, "per-page": 50,
            "select": "id,doi,display_name,publication_year,type,open_access,primary_location"}))
        for w in res.get("results", []):
            title = w.get("display_name") or ""
            url = w.get("doi") or (w.get("primary_location") or {}).get("landing_page_url") or w["id"]
            oa = (w.get("open_access") or {}).get("oa_url") or ""
            add(url, f"{title} ({w.get('publication_year')})", "openalex",
                f"type={w.get('type')}; open_access_pdf={oa}")
        time.sleep(1)
    except Exception as e:
        print("OpenAlex failed:", e)
print("after OpenAlex:", len(CANDIDATES))


# --- 6. save the list for review ---
out = os.path.join(DOC_DIR, "sources_candidates.csv")
rows = sorted(CANDIDATES.values(), key=lambda r: (r["tier"], r["found_by"], r["url"]))
with open(out, "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.DictWriter(fh, fieldnames=["keep", "suggest", "tier", "type", "title", "url", "found_by", "note"])
    w.writeheader()
    for r in rows:
        w.writerow({"keep": "", **r})
counts = {}
for r in rows:
    counts[r["tier"]] = counts.get(r["tier"], 0) + 1
print("\ncandidates per tier (1 official, 2 academic, 3 institutional, 4 press, 5 other):", counts)
print("Saved:", out)
print("suggested 'y':", sum(1 for r in rows if r["suggest"] == "y"))
print("Open it in Excel and write 'y' in the keep column for the sources to use (see the suggest column).")
