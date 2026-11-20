# ==============================================================
# doc_extract.py  -  step D2: read the chosen sources and draft the document fields
# v0.13, 16 Nov 2026 (version printed, redirect details in errors; v0.12 redirects followed by the script; v0.11 BCNROC via its DSpace 7 API; v0.10 cookies; v0.9: codebook fields, sub-type, helper fields)
# 1. reads sources_candidates.csv (rows with keep = y)
# 2. downloads each source once and turns it into text (HTML or PDF)
# 3. asks an LLM, source by source, to fill the document fields of the template,
#    using the template's own definitions and options, with a quote as evidence
# 4. writes review.csv (one row per field: proposed value, quote, source, alternatives)
#    and draft_fields.json - nothing goes into the case JSON before you review it (step D3)
# The API key is read from an environment variable, never from a file:
#   in the QGIS console, once per session:  os.environ["ANTHROPIC_API_KEY"] = "..."
#                                       or:  os.environ["OPENAI_API_KEY"] = "..."
# ==============================================================
import os
import re
import csv
import json
import time
import html
import hashlib
import unicodedata
import urllib.request
import urllib.parse
import urllib.error

print("doc_extract.py v0.13")

# --- 1. settings ---
SITE_NAME = "Can Batlló"
CITY = "Barcelona"
NAME_WORDS = ["Can Batlló", "Can Batllo", "Batlló"]       # used to cut long texts to the relevant parts
GIS_DIR = r"C:\gis"
TEMPLATE_GUIDE = r"C:\Users\eceus\OneDrive\Desktop\main folders\classes\iaac\thesis\The-City-In-Waiting\data\categories\1.1-former-industrial-service-estates_template.json"

PROVIDER = "openai"             # "anthropic" or "openai"
MODEL = "gpt-5.4-mini"         # openai: gpt-5.4-mini (better) or gpt-4o-mini (cheapest, weaker); anthropic: claude-sonnet-5-5
MAX_SOURCES = None              # None = all kept sources; a number (e.g. 5) for a quick test
PARALLEL = 4                    # sources read at the same time (lower it if the API says 'busy')
MAX_CHARS = 60000               # text sent per source (long documents are cut to the parts naming the site)
USE_SUGGESTED_IF_NO_KEEP = True # if you have not filled 'keep' yet, use the 'suggest = y' rows
USER_AGENT = "IAAC-MAA02-thesis-script (research)"


def slugify(text):
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(c if c.isalnum() else "_" for c in t.lower()).strip("_")

DOC_DIR = os.path.join(GIS_DIR, "auto_case", slugify(SITE_NAME), "documents")
TXT_DIR = os.path.join(DOC_DIR, "text")
ANS_DIR = os.path.join(DOC_DIR, "llm_answers")
os.makedirs(TXT_DIR, exist_ok=True)
os.makedirs(ANS_DIR, exist_ok=True)


# --- 2. which fields are document fields (decided 16 Nov 2026) ---
DOC_FIELDS = [
    ("case", "use_history"), ("case", "year_built"),
    ("before", "years_vacant"), ("before", "cause_of_vacancy"), ("before", "secondary_causes"),
    ("before", "status"), ("before", "contamination"), ("before", "previous_use_risk"),
    ("before", "ownership"), ("before", "reuse_cost"), ("before", "response_to_vacancy"),
    ("before", "zoning"), ("before", "planning_status"),
    ("temporary", "type"), ("temporary", "type_category"), ("temporary", "start_date"),
    ("temporary", "end_date"), ("temporary", "duration_months"), ("temporary", "area_pct"),
    ("temporary", "legal_framework"), ("temporary", "agreement_type"), ("temporary", "users_count"),
    ("temporary", "visitors_per_year"), ("temporary", "user_rent"), ("temporary", "funding"),
    ("temporary", "reversibility"), ("temporary", "link_to_permanent_plan"), ("temporary", "outcome"),
    ("temporary", "actors"),
    ("after", "assessment"), ("after", "completion_year"), ("after", "new_use"),
    ("after", "end_use_sensitivity"), ("after", "regeneration_cost"), ("after", "jobs_created"),
    ("after", "community_objections"), ("after", "actors"), ("after", "governance_type"),
    ("after", "governance"),
    # added v0.9: codebook judgement fields and the sub-type
    ("case", "sub_type"), ("case", "secondary_types"),
    ("before", "heritage_value"), ("before", "access"),
    ("after", "memory_intangible"), ("after", "public_access"), ("after", "inclusion"),
    ("after", "gentrification"), ("after", "urban_role"), ("after", "economic_viability"),
    # helper fields: not written to the case JSON, doc_merge.py computes from them
    ("temporary", "area_m2"), ("before", "original_use_end_year"),
]

with open(TEMPLATE_GUIDE, encoding="utf-8") as fh:
    GUIDE = json.load(fh)["field_options"]

def field_spec(block, field):
    spec = GUIDE.get(block, {}).get(field, {})
    if isinstance(spec, str):                       # e.g. "same as before.site_layout"
        spec = {"definition": spec}
    keep = {k: spec[k] for k in ("type", "definition", "options", "fields", "unit", "note") if k in spec}
    return keep

SPECS = {f"{b}.{f}": field_spec(b, f) for b, f in DOC_FIELDS}
# fields whose options live in analysis/cases/codebook.json, not in the template guide
SPECS["temporary.outcome"]["options"] = {
    "ended": "it stopped", "stayed": "it became permanent",
    "shaped_the_plan": "it influenced the final project", "moved": "it moved or was copied elsewhere"}
SPECS["case.use_history"]["definition"] = "Earlier uses, oldest first, each as 'use, years' (e.g. 'textile factory, 1878-1960s')."

# v0.9 - options from analysis/cases/codebook.json (v2) and the category's sub_types
SUB_TYPES = {
    "1.1.a": "former industrial sites: factories, works, workshops, breweries, slaughterhouses, shipyards",
    "1.1.b": "former logistics & storage sites: warehouses, storage yards, distribution centres",
    "1.1.c": "former energy & utility plants: power stations, gasworks, water and sewage works",
    "1.1.d": "former extraction & disposal sites: quarries, mines, spoil heaps, landfills",
    "1.1.e": "former military sites: barracks, bases, training grounds, depots",
    "1.1.f": "former institutional estates: hospital complexes, campuses, prisons",
    "1.1.g": "former commercial & leisure complexes: shopping centres, amusement parks, exhibition grounds",
    "1.1.h": "other former service estates"}
SPECS["case.sub_type"] = {"type": "one_of", "definition": "Main sub-type of the site (its original main use).",
                          "options": SUB_TYPES}
SPECS["case.secondary_types"] = {"type": "list_of", "definition": "Other sub-types also present on the site "
                                 "(not the main one).", "options": SUB_TYPES}
SPECS["before.heritage_value"] = {"type": "one_of", "definition": "Whether the site carried heritage value at the "
    "time of vacancy. Legal listing is not required.", "options": {
    "yes": "the structure (or part of it) survives AND it carries historic meaning for the city or community",
    "no": "otherwise"}}
SPECS["before.access"] = {"type": "one_of", "definition": "Who could enter the site while vacant.", "options": {
    "open": "anyone could enter", "restricted": "by permission, partial or seasonal",
    "closed_informal_use": "officially closed, but people got in anyway", "closed": "closed and not used"}}
SPECS["after.memory_intangible"] = {"type": "one_of", "definition": "Social memory: the site's stories, uses and "
    "meaning to people are carried into the project.", "options": {"yes": "kept", "no": "erased or not told"}}
SPECS["after.public_access"] = {"type": "one_of", "definition": "Whether the public is allowed in today "
    "(rules, fees, opening hours).", "options": {"yes": "open to anyone, free",
    "partly": "only some parts open, or paid, or seasonal", "no": "closed"}}
SPECS["after.inclusion"] = {"type": "one_of", "definition": "Whether a wide range of people, especially local and "
    "low-income residents, actually use the space and feel it is for them.", "options": {
    "inclusive": "evidence that local or low-income people use it or help run it",
    "limited": "open in principle, but evidence that some groups (often locals) use it much less",
    "exclusionary": "exclusion or displacement of users is documented"}}
SPECS["after.gentrification"] = {"type": "one_of", "definition": "Whether the project led to rising property values "
    "and displacement around the site.", "options": {"yes": "documented",
    "partial": "some evidence, or evidence is disputed", "no": "evidence that it did not happen"}}
SPECS["after.urban_role"] = {"type": "one_of", "definition": "What the project does to the city beyond its own "
    "boundary.", "options": {"interim": "a temporary role until something else happens",
    "contained": "the effect stays mainly inside the site",
    "connector": "it mainly links places, as a route or green corridor",
    "catalyst": "it triggers the transformation of the area around it"}}
SPECS["after.economic_viability"] = {"type": "one_of", "definition": "How the site is funded today.", "options": {
    "self_funded": "covered mainly by its own income or private fundraising",
    "subsidised": "stable, but needs regular public money", "failing": "closed, failing or rescued"}}
SPECS["temporary.area_m2"] = {"type": "number", "unit": "m²", "definition": "Surface (m²) of the site used by the "
    "temporary use (e.g. the area ceded or occupied). Only a figure stated in the source."}
SPECS["before.original_use_end_year"] = {"type": "number", "definition": "Year the original (industrial) use of the "
    "site ended. Only a year stated in the source."}


# --- 3. sources: read the list, download, turn into text ---
def read_csv_any(path):
    # Excel in Turkish / Spanish saves CSV with ';' instead of ',' - accept both
    for enc in ("utf-8-sig", "cp1254", "cp1252"):
        try:
            raw = open(path, encoding=enc).read()
            break
        except UnicodeDecodeError:
            continue
    first = raw.splitlines()[0]
    delim = ";" if first.count(";") > first.count(",") else ","
    import io
    return list(csv.DictReader(io.StringIO(raw), delimiter=delim))

rows = read_csv_any(os.path.join(DOC_DIR, "sources_candidates.csv"))
chosen = [r for r in rows if r.get("keep", "").strip().lower() == "y"]
if not chosen and USE_SUGGESTED_IF_NO_KEEP:
    chosen = [r for r in rows if r.get("suggest", "").strip().lower() == "y"]
    print("keep column empty - using the suggested sources")
chosen.sort(key=lambda r: int(r["tier"]))
if MAX_SOURCES:
    # for a small test take sources from different tiers and catalogues, not only the first tier
    picked, seen = [], set()
    for r in chosen:
        k = (r["tier"], r.get("found_by", ""))
        if k not in seen:
            picked.append(r); seen.add(k)
    for r in chosen:
        if len(picked) >= MAX_SOURCES:
            break
        if r not in picked:
            picked.append(r)
    chosen = picked[:MAX_SOURCES]
print("sources to read:", len(chosen))

from html.parser import HTMLParser
class _Strip(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer", "header"):
            self.skip += 1
    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "header") and self.skip:
            self.skip -= 1
    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(data.strip())

def html_to_text(raw):
    p = _Strip()
    p.feed(raw.decode("utf-8", errors="ignore"))
    return "\n".join(p.parts)

def pdf_to_text(raw):
    try:
        import fitz                                    # PyMuPDF
        doc = fitz.open(stream=raw, filetype="pdf")
        return "\n".join(f"[page {i + 1}]\n" + pg.get_text() for i, pg in enumerate(doc))
    except ImportError:
        pass
    try:
        import io
        from pypdf import PdfReader
        rd = PdfReader(io.BytesIO(raw))
        return "\n".join(f"[page {i + 1}]\n" + (pg.extract_text() or "") for i, pg in enumerate(rd.pages))
    except ImportError:
        raise Exception("No PDF reader: install pypdf once (OSGeo4W Shell: python -m pip install pypdf)")

import ssl
# Some official servers (e.g. the City Council repository BCNROC) send an incomplete certificate
# chain that Python cannot check, although browsers can. Only for the hosts listed here the
# script retries without the certificate check (public documents, read only).
UNVERIFIED_OK_HOSTS = ("bcnroc.ajuntament.barcelona.cat", "api-bcnroc.ajuntament.barcelona.cat", "hdl.handle.net")

import http.cookiejar
# Redirects are followed by the script itself (not by urllib), so a loop shows where it goes
# instead of a bare 'HTTP 301'. Cookies are kept between requests.
COOKIES = http.cookiejar.CookieJar()

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def _opener(check=True):
    hs = [urllib.request.HTTPCookieProcessor(COOKIES), _NoRedirect()]
    if not check:
        hs.append(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
    return urllib.request.build_opener(*hs)
OPENER, OPENER_NOCHECK = _opener(True), _opener(False)

def open_url(url, timeout=120, accept="*/*"):
    first_host = urllib.parse.urlparse(url).netloc.lower()
    may_skip_check = any(h in first_host for h in UNVERIFIED_OK_HOSTS)
    hops = []
    for _ in range(10):
        url = url.replace("http://bcnroc.", "https://bcnroc.").replace("http://api-bcnroc.", "https://api-bcnroc.")
        hops.append(url)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
        try:
            try:
                return OPENER.open(req, timeout=timeout)
            except urllib.error.URLError as e:
                if isinstance(e, urllib.error.HTTPError) or "CERTIFICATE_VERIFY_FAILED" not in str(e) \
                        or not may_skip_check:
                    raise
                return OPENER_NOCHECK.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location")
            if e.code in (301, 302, 303, 307, 308) and not loc:
                raise Exception(f"HTTP {e.code} without a new address from {url} "
                                f"(server: {e.headers.get('Server')}, type: {e.headers.get('Content-Type')})")
            if e.code in (301, 302, 303, 307, 308) and loc:
                nxt = urllib.parse.urljoin(url, loc)
                if hops.count(nxt) >= 2:
                    raise Exception(f"redirect loop: {' -> '.join(hops[-4:])} -> {nxt}")
                url = nxt
                continue
            raise
    raise Exception("too many redirects: " + " -> ".join(hops[-4:]))

def resolve_handle(url):
    # hdl.handle.net/<prefix>/<id> -> the repository page, via the Handle API (avoids a redirect loop)
    m = re.search(r"hdl\.handle\.net/(\d+(?:\.\d+)*/\d+)", url)
    if not m:
        return url
    with open_url("https://hdl.handle.net/api/handles/" + m.group(1)) as r:
        data = json.loads(r.read().decode("utf-8"))
    for v in data.get("values", []):
        if v.get("type") == "URL":
            return v["data"]["value"]
    return url

# BCNROC moved to DSpace 7 (2026): old handle / jspui links end in a redirect loop, but its REST API
# gives the item and its PDF files directly (checked in a browser, 16 Nov 2026)
BCNROC_API = "https://api-bcnroc.ajuntament.barcelona.cat/api"

def fetch_bcnroc(handle_id):
    try:
        return _fetch_bcnroc(handle_id)
    except Exception as e:
        raise Exception(f"BCNROC API ({handle_id}): {e}")

def _fetch_bcnroc(handle_id):
    with open_url(f"{BCNROC_API}/pid/find?id=11703/{handle_id}", accept="application/json") as r:
        item = json.loads(r.read().decode("utf-8"))
    with open_url(f"{BCNROC_API}/core/items/{item['uuid']}/bundles?embed=bitstreams", accept="application/json") as r:
        bundles = json.loads(r.read().decode("utf-8"))["_embedded"]["bundles"]
    texts = []
    for b in bundles:
        if b["name"] != "ORIGINAL":
            continue
        for f in b.get("_embedded", {}).get("bitstreams", {}).get("_embedded", {}).get("bitstreams", []):
            with open_url(f"{BCNROC_API}/core/bitstreams/{f['uuid']}/content") as r:
                raw = r.read()
            body = pdf_to_text(raw) if raw[:4] == b"%PDF" else html_to_text(raw)
            texts.append(f"[file: {f['name']}]\n{body}")
    return f"[BCNROC item: {item.get('name', '')}]\n" + "\n\n".join(texts)

def fetch_text(url):
    key = hashlib.md5(url.encode()).hexdigest()[:12]
    path = os.path.join(TXT_DIR, key + ".txt")
    if os.path.exists(path):
        return open(path, encoding="utf-8").read(), path
    m = re.search(r"(?:hdl\.handle\.net|bcnroc\.ajuntament\.barcelona\.cat).*?11703/(\d+)", url)
    if m:
        text = fetch_bcnroc(m.group(1))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return text, path
    url = resolve_handle(url)
    with open_url(url) as r:
        raw = r.read()
        ctype = r.headers.get("Content-Type", "").lower()
        final_url = r.geturl()
    # a repository landing page (handle) is HTML: follow its first PDF link
    if "pdf" not in ctype and raw[:4] != b"%PDF":
        m = re.search(rb'href="([^"]+?\.pdf[^"]*)"', raw, re.I)
        if m and ("handle" in url or "bcnroc" in final_url):
            pdf_url = urllib.parse.urljoin(final_url, html.unescape(m.group(1).decode("utf-8", "ignore")))
            with open_url(pdf_url) as r2:
                raw = r2.read()
                ctype = r2.headers.get("Content-Type", "").lower()
    if "pdf" in ctype or raw[:4] == b"%PDF":
        text = pdf_to_text(raw)
    else:
        text = html_to_text(raw)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return text, path

def relevant_part(text):
    # long texts: keep 3,000 characters around every mention of the site, up to MAX_CHARS
    if len(text) <= MAX_CHARS:
        return text
    spans = []
    low = text.lower()
    for w in NAME_WORDS:
        for m in re.finditer(re.escape(w.lower()), low):
            spans.append((max(0, m.start() - 1500), m.end() + 1500))
    spans.sort()
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    out = "\n[...]\n".join(text[a:b] for a, b in merged)
    return out[:MAX_CHARS] if out else text[:MAX_CHARS]


# --- 4. the LLM call (no extra library needed) ---
SYSTEM = (
    "You extract facts about one urban site for an architecture thesis database. "
    "Use ONLY the source text you are given. For each field listed, fill it only if the text "
    "states it or states facts that directly determine it; otherwise leave the field out. "
    "When a field has options, the value must be one of the options exactly (or a list of options "
    "for list fields). For every value give a short verbatim quote from the text (max 40 words, "
    "in the original language) and where it is (page number if shown as [page N], else section). "
    "Never guess, never use outside knowledge. Answer with one JSON object only.\n"
    "STRICT FORMAT: every field you return must be {\"value\": ..., \"quote\": ..., \"where\": ...}, "
    "also for object fields (then value is the object) and list fields (then value is the list). "
    "The quote must be copied character by character from the SOURCE TEXT - never from the field "
    "definitions or options. Do not return fields whose value would be 'unknown', empty or null.\n"
    "Silence is not evidence: never answer 'none_known', 'no', 0 or false only because the text does "
    "not mention something. The quote must state the fact itself, not something nearby.\n"
    "Mind the date of the source: 'before' = while the site was vacant; 'temporary' = the temporary use; "
    "'after' = the situation after the regeneration. Do not describe plans or intentions as facts."
)
PROMPT_VERSION = "p4"   # p4 = v0.9 fields (all sources are read again once)
NO_TEMPERATURE = False     # change when the instructions change, so cached answers are redone

def ask_llm(prompt, tries=4, system=None):
    for t in range(tries):
        try:
            return _ask_llm(prompt, system or SYSTEM)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            if e.code == 429 and ("insufficient_quota" in body or "credit" in body.lower()):
                raise Exception("the API account has no credit yet (add a payment / credit on the "
                                "provider's billing page): " + body[:300])
            if e.code in (429, 500, 502, 503, 529) and t < tries - 1:
                wait = 20 * (t + 1)
                print(f"   API busy ({e.code}), waiting {wait} s ...")
                time.sleep(wait)
                continue
            if e.code == 400 and "temperature" in body and not NO_TEMPERATURE:
                globals()["NO_TEMPERATURE"] = True       # newer reasoning models only accept the default
                print("   model does not accept temperature=0, using its default")
                continue
            raise Exception(f"HTTP {e.code}: {body[:300]}")

def _ask_llm(prompt, system):
    if PROVIDER == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY")
        body = {"model": MODEL, "max_tokens": 4000, "temperature": 0, "system": system,
                "messages": [{"role": "user", "content": prompt}]}
        req = urllib.request.Request("https://api.anthropic.com/v1/messages",
                                     data=json.dumps(body).encode(),
                                     headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                              "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            res = json.loads(r.read().decode("utf-8"))
        text = "".join(c.get("text", "") for c in res.get("content", []))
    else:
        key = os.environ.get("OPENAI_API_KEY")
        body = {"model": MODEL, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        if not NO_TEMPERATURE:
            body["temperature"] = 0
        req = urllib.request.Request("https://api.openai.com/v1/chat/completions",
                                     data=json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {key}",
                                              "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:
            res = json.loads(r.read().decode("utf-8"))
        text = res["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {}

if not os.environ.get("ANTHROPIC_API_KEY" if PROVIDER == "anthropic" else "OPENAI_API_KEY"):
    raise Exception("Set the API key first, e.g. os.environ['ANTHROPIC_API_KEY'] = '...' (not saved in any file)")

FIELD_BLOCK = json.dumps(SPECS, ensure_ascii=False, indent=1)

def build_prompt(src, text):
    return (
        f"SITE: {SITE_NAME}, {CITY}.\n"
        f"SOURCE: {src['title'] or src['url']} ({src['url']}).\n\n"
        "FIELDS (definitions, allowed options and units come from the thesis template):\n"
        f"{FIELD_BLOCK}\n\n"
        "Return JSON like {\"before.cause_of_vacancy\": {\"value\": \"planning_blight\", "
        "\"quote\": \"...\", \"where\": \"p. 2\"}, ...}. For object fields (ownership, reuse_cost, "
        "regeneration_cost, assessment, jobs_created) the value is an object with the listed sub-fields; "
        "for actors the value is a list of {name, sector, role, initiator}. Leave out fields without evidence.\n\n"
        f"SOURCE TEXT:\n{text}"
    )


# PDFs you download yourself (paywalled papers, sites that block scripts) can be dropped in
# documents\manual_pdfs\ - each file is read as one more source (tier 2 unless renamed 'tier1_...')
MAN_DIR = os.path.join(DOC_DIR, "manual_pdfs")
os.makedirs(MAN_DIR, exist_ok=True)
for fn in sorted(os.listdir(MAN_DIR)):
    if fn.lower().endswith(".pdf"):
        chosen.append({"url": "file:///" + os.path.join(MAN_DIR, fn).replace("\\", "/"),
                       "title": fn, "tier": "1" if fn.lower().startswith("tier1") else "2"})

def fetch_local(url):
    path = url.replace("file:///", "")
    with open(path, "rb") as fh:
        return pdf_to_text(fh.read()), path

def _norm(t):
    t = unicodedata.normalize("NFKC", t or "").lower()
    t = re.sub(r"[\u2018\u2019\u201c\u201d'\"«»]", "", t)
    return re.sub(r"\s+", " ", t).strip()

def quote_found(quote, text):
    # every piece of the quote (split at '...') must appear in the source text
    q = _norm(quote)
    if len(q) < 8:
        return False
    nt = _norm(text)
    pieces = [p.strip() for p in re.split(r"\.\.\.|\u2026|\[\.\.\.\]", q) if len(p.strip()) >= 8]
    return bool(pieces) and all(p in nt for p in pieces)

def normalise(ans, text):
    # accept bare values, drop 'unknown', mark whether the quote is really in the source
    out = {}
    for k, v in ans.items():
        if k not in SPECS:
            continue
        if not (isinstance(v, dict) and "value" in v):
            v = {"value": v, "quote": "", "where": ""}
        val = v.get("value")
        if val in (None, "", [], {}) or (isinstance(val, str) and val.strip().lower() in ("unknown", "n/a", "not stated")):
            continue
        v["quote_check"] = "found" if quote_found(v.get("quote", ""), text) else (
            "missing" if not v.get("quote") else "NOT IN SOURCE")
        out[k] = v
    return out

# --- 5. run: one LLM call per source (answers cached), PARALLEL sources at the same time ---
from concurrent.futures import ThreadPoolExecutor

def process(i, src):
    sid = f"D{i}"
    try:
        text, tpath = fetch_local(src["url"]) if src["url"].startswith("file:///") else fetch_text(src["url"])
    except Exception as e:
        return sid, src, None, f"download failed: {src['url'][:80]} - {e}"
    part = relevant_part(text)
    if len(part.strip()) < 200:
        return sid, src, None, f"too little text, skipped: {src['url'][:80]}"
    cache = os.path.join(ANS_DIR, hashlib.md5((src["url"] + MODEL + PROMPT_VERSION).encode()).hexdigest()[:12] + ".json")
    if os.path.exists(cache):
        ans = json.load(open(cache, encoding="utf-8"))
    else:
        try:
            ans = ask_llm(build_prompt(src, part))
        except Exception as e:
            return sid, src, None, f"LLM failed: {e}"
        json.dump(ans, open(cache, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ans = normalise(ans, part)
    return sid, src, ans, f"tier {src['tier']} | fields found: {len(ans)} | {(src['title'] or src['url'])[:70]}"

ANSWERS = []
t0 = time.time()
with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
    futures = [pool.submit(process, i, src) for i, src in enumerate(chosen, 1)]
    for fut in futures:                          # results printed in source order
        sid, src, ans, msg = fut.result()
        print(sid, msg)
        if ans is not None:
            ANSWERS.append((sid, src, ans))
print(f"read {len(ANSWERS)} of {len(chosen)} sources in {round((time.time() - t0) / 60, 1)} min")


# --- 6. check + combine ---
# A quote can be real but not support the value (e.g. a 2024 park article used for the 2011
# temporary use). A second, short LLM call checks every distinct proposal against its quote and the
# field definition; the value chosen is the one supported by the most sources, then the most reliable.
JUDGE = (
    "You check evidence for a thesis database. For each candidate you get a field definition, "
    "a proposed value and a quote from a source. Answer 'yes' only if the quote by itself directly "
    "supports that value for that field and that phase (before = while vacant; temporary = the "
    "temporary use; after = after regeneration). Answer 'partly' if it supports part of the value, "
    "'no' otherwise. Return JSON {\"1\": \"yes\", \"2\": \"no\", ...} only."
)

def judge(key, cands):
    cache = os.path.join(ANS_DIR, "judge_" + hashlib.md5((key + MODEL + json.dumps(
        [(c["value"], c["quote"]) for c in cands], ensure_ascii=False)).encode()).hexdigest()[:12] + ".json")
    if os.path.exists(cache):
        return json.load(open(cache, encoding="utf-8"))
    lines = [f"FIELD {key}: {json.dumps(SPECS[key], ensure_ascii=False)}"]
    for i, c in enumerate(cands, 1):
        lines.append(f"{i}. value={json.dumps(c['value'], ensure_ascii=False)} | source: {c['title'][:90]} | "
                     f"quote: \"{c['quote']}\"")
    res = ask_llm("\n".join(lines), system=JUDGE)
    json.dump(res, open(cache, "w", encoding="utf-8"))
    return res

def vkey(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True)

def combine(key):
    allf = [(int(src["tier"]), sid, src, ans[key]) for sid, src, ans in ANSWERS if key in ans]
    found = [x for x in allf if x[3].get("quote_check") == "found"]
    unverified = [x for x in allf if x[3].get("quote_check") != "found"]
    unv_txt = " || ".join(f"{x[1]} (tier {x[0]}, quote {x[3].get('quote_check')}): "
                          f"{json.dumps(x[3].get('value'), ensure_ascii=False)}" for x in unverified)
    row = {"field": key, "proposed_value": "", "quote": "", "where": "", "source_id": "", "source_tier": "",
           "source": "", "support": "", "n_sources_supporting": 0, "alternatives": "",
           "rejected_no_evidence": unv_txt[:1500], "decision": ""}
    if not found:
        return row
    found.sort(key=lambda x: x[0])
    cands = [{"value": x[3]["value"], "quote": x[3].get("quote", ""), "title": x[2]["title"] or x[2]["url"]}
             for x in found[:8]]
    try:
        verdict = judge(key, cands)
    except Exception as e:
        print("   judge failed for", key, "-", e)
        verdict = {}
    scored = []
    for i, x in enumerate(found[:8], 1):
        scored.append((verdict.get(str(i), "unchecked"), x))
    if SPECS[key].get("type") == "list_of" or key.endswith(".actors"):
        return combine_list(key, row, scored)
    ok = [x for v, x in scored if v == "yes"] or [x for v, x in scored if v == "partly"]
    if not ok:
        row["alternatives"] = " || ".join(f"{x[1]} (tier {x[0]}, check {v}): {vkey(x[3]['value'])}"
                                          for v, x in scored)[:1500]
        return row
    counts = {}
    for x in ok:
        counts[vkey(x[3]["value"])] = counts.get(vkey(x[3]["value"]), 0) + 1
    ok.sort(key=lambda x: (-counts[vkey(x[3]["value"])], x[0]))
    t, sid, src, best = ok[0]
    row.update({"proposed_value": vkey(best["value"]), "quote": best.get("quote", ""),
                "where": best.get("where", ""), "source_id": sid, "source_tier": t, "source": src["url"],
                "support": next(v for v, x in scored if x[1] == sid),
                "n_sources_supporting": counts[vkey(best["value"])],
                "alternatives": " || ".join(f"{x[1]} (tier {x[0]}, check {v}): {vkey(x[3]['value'])}"
                                            for v, x in scored if x[1] != sid)[:1500]})
    return row

def combine_list(key, row, scored):
    # list fields (new_use, actors, causes ...): union of the items supported in any source,
    # each item with the sources that name it
    items, where = {}, {}
    for verdict, (t, sid, src, ans) in scored:
        if verdict not in ("yes", "partly"):
            continue
        vals = ans["value"] if isinstance(ans["value"], list) else [ans["value"]]
        for it in vals:
            k = (it.get("name", "") if isinstance(it, dict) else str(it)).strip().lower()
            if not k:
                continue
            items.setdefault(k, it)
            where.setdefault(k, []).append(f"{sid} (t{t}, {verdict}): \"{ans.get('quote', '')[:120]}\"")
    if not items:
        row["alternatives"] = " || ".join(f"{x[1]} (tier {x[0]}, check {v}): {vkey(x[3]['value'])}"
                                          for v, x in scored)[:1500]
        return row
    row.update({"proposed_value": vkey(list(items.values())),
                "quote": " | ".join(f"{k}: {where[k][0]}" for k in items)[:1500],
                "where": "see quote", "source_id": ", ".join(sorted({w.split(' ')[0] for k in where for w in where[k]})),
                "source_tier": "", "source": "several (union of supported items)", "support": "union",
                "n_sources_supporting": len({w.split(' ')[0] for k in where for w in where[k]})})
    return row

with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
    review = list(pool.map(lambda bf: combine(f"{bf[0]}.{bf[1]}"), DOC_FIELDS))

rev_path = os.path.join(DOC_DIR, "review.csv")
# keep decisions you already typed, when the proposal did not change
if os.path.exists(rev_path):
    old_rows = {r["field"]: r for r in read_csv_any(rev_path)}
    kept = 0
    for r in review:
        o = old_rows.get(r["field"])
        if o and (o.get("decision") or "").strip() and o.get("proposed_value", "") == r["proposed_value"]:
            r["decision"] = o["decision"].strip()
            kept += 1
    os.replace(rev_path, os.path.join(DOC_DIR, "review_previous.csv"))
    print(f"decisions kept from the previous review.csv: {kept} (old file saved as review_previous.csv)")
with open(rev_path, "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.DictWriter(fh, fieldnames=list(review[0].keys()))
    w.writeheader()
    w.writerows(review)
with open(os.path.join(DOC_DIR, "draft_fields.json"), "w", encoding="utf-8") as fh:
    json.dump({"model": f"{PROVIDER}/{MODEL}", "sources": [{"id": sid, "url": s["url"], "tier": s["tier"],
               "title": s["title"]} for sid, s, _ in ANSWERS], "fields": review}, fh, ensure_ascii=False, indent=1)
filled = sum(1 for r in review if r["proposed_value"])
rejected = sum(1 for r in review if r["rejected_no_evidence"])
print(f"\nfields with a proposal (quote in the source AND supporting the value): {filled} of {len(review)}")
print(f"fields with answers rejected because the quote is not in the source: {rejected}")
print("Saved:", rev_path)
print("Open review.csv: in 'decision' write  y  (accept),  n  (reject)  or your corrected value.")
