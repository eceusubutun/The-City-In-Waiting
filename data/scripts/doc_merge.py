# ==============================================================
# doc_merge.py  -  step D3: write the reviewed document fields into the case JSON
# v0.3, 16 Nov 2026 (m = manual value; derived fields: duration, area %, years vacant, assessment)
# Reads documents\review.csv after you filled the 'decision' column:
#   y            -> accept the proposed value
#   n (or empty) -> leave the field empty
#   m            -> keep the value of your manual case JSON (MANUAL_JSON)
#   anything else-> your own value (JSON like ["a","b"] or {"type":"private"} is read as JSON,
#                   otherwise as text / number)
# Writes into the newest auto_case run (or CASE_JSON if set), adds the sources used, marks every
# accepted field in provenance.field_notes as 'ai_drafted, checked by Ece' with its quote, and
# writes doc_comparison.csv (manual value vs final value).
# ==============================================================
import os
import io
import re
import csv
import json
import glob
import unicodedata
from datetime import datetime

# --- 1. settings ---
SITE_NAME = "Can Batlló"
GIS_DIR = r"C:\gis"
CASE_JSON = None          # None = can_batllo.json of the newest auto_case run
MANUAL_JSON = r"C:\Users\eceus\OneDrive\Desktop\main folders\classes\iaac\thesis\The-City-In-Waiting\data\cases\can_batllo.json"


def slugify(text):
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(c if c.isalnum() else "_" for c in t.lower()).strip("_")

SLUG = slugify(SITE_NAME)
SITE_DIR = os.path.join(GIS_DIR, "auto_case", SLUG)
DOC_DIR = os.path.join(SITE_DIR, "documents")

if CASE_JSON is None:
    runs = sorted(p for p in glob.glob(os.path.join(SITE_DIR, "2*", SLUG + ".json")))
    if not runs:
        raise Exception("no auto_case run found - run auto_case.py first")
    CASE_JSON = runs[-1]
print("case JSON:", CASE_JSON)

def read_csv_any(path):
    for enc in ("utf-8-sig", "cp1254", "cp1252"):
        try:
            raw = open(path, encoding=enc).read()
            break
        except UnicodeDecodeError:
            continue
    first = raw.splitlines()[0]
    delim = ";" if first.count(";") > first.count(",") else ","
    return list(csv.DictReader(io.StringIO(raw), delimiter=delim))

def parse_value(text):
    text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        return text

with open(CASE_JSON, encoding="utf-8") as fh:
    CASE = json.load(fh)
draft = json.load(open(os.path.join(DOC_DIR, "draft_fields.json"), encoding="utf-8"))
SRC = {s["id"]: s for s in draft["sources"]}
TYPE_BY_TIER = {"1": "report", "2": "paper", "3": "project_page", "4": "press", "5": "other"}

# fields stored somewhere else than block.field, and helper fields that are only used for calculations
PATHS = {"after.memory_intangible": ("after", "memory_protection", "memory_intangible")}
HELPERS = {"temporary.area_m2", "before.original_use_end_year"}
HELP = {}
NOW = datetime.now()

def path_of(key):
    return PATHS.get(key, tuple(key.split(".", 1)))

def get_in(d, key):
    for part in path_of(key):
        if not isinstance(d, dict):
            return None
        d = d.get(part)
    return d

def set_field(key, value, note):
    *parents, last = path_of(key)
    d = CASE
    for part in parents:
        d = d.setdefault(part, {})
    d[last] = value
    CASE.setdefault("provenance", {}).setdefault(parents[0], {}).setdefault("field_notes", {})[
        ".".join(path_of(key)[1:])] = note

def is_empty(v):
    return v in (None, "", [], {}) or (isinstance(v, dict) and all(is_empty(x) for x in v.values()))

MANUAL = json.load(open(MANUAL_JSON, encoding="utf-8")) if MANUAL_JSON and os.path.exists(MANUAL_JSON) else {}

# --- 2. apply decisions ---
accepted, own, rejected, from_manual, used_sources = 0, 0, 0, 0, set()
llm_same_as_manual, llm_proposals = 0, 0
for r in read_csv_any(os.path.join(DOC_DIR, "review.csv")):
    d = (r.get("decision") or "").strip()
    key = r["field"]
    if r["proposed_value"] and key not in HELPERS:      # how good was the LLM before the review?
        llm_proposals += 1
        if json.dumps(parse_value(r["proposed_value"]), sort_keys=True, ensure_ascii=False) == \
                json.dumps(get_in(MANUAL, key), sort_keys=True, ensure_ascii=False):
            llm_same_as_manual += 1
    if d.lower() == "m":
        if key in HELPERS:
            continue
        set_field(key, get_in(MANUAL, key), f"manual value (Ece), kept during review {NOW:%Y-%m-%d}")
        from_manual += 1
        continue
    if not d or d.lower() == "n":
        rejected += 1
        continue
    if d.lower() == "y":
        if not r["proposed_value"]:
            continue
        value = parse_value(r["proposed_value"])
        note = (f"ai_drafted ({draft['model']}), checked by Ece {NOW:%Y-%m-%d}; "
                f"source {r['source_id']}: \"{r['quote'][:300]}\" ({r['where']})")
        for sid in [x.strip() for x in r["source_id"].split(",") if x.strip()]:
            used_sources.add(sid)
        accepted += 1
    else:
        value = parse_value(d)
        note = f"value set by Ece {NOW:%Y-%m-%d} during review (proposal was {r['proposed_value'][:120]})"
        own += 1
    if key in HELPERS:
        HELP[key] = (value, note)
        continue
    set_field(key, value, note)

# --- 2b. derived fields (rules, only where the field is still empty) ---
def year_of(text):
    m = re.match(r"\s*(\d{4})(?:-(\d{1,2}))?", str(text or ""))
    return (int(m.group(1)), int(m.group(2) or 6)) if m else None

derived = 0
T, A = CASE.setdefault("temporary", {}), CASE.setdefault("after", {})
start = year_of(T.get("start_date"))
if is_empty(T.get("duration_months")) and start:
    end = year_of(T.get("end_date")) or (NOW.year, NOW.month)       # 'ongoing' -> until today
    set_field("temporary.duration_months", (end[0] - start[0]) * 12 + end[1] - start[1],
              f"derived: start_date {T.get('start_date')} to {T.get('end_date') or 'today'}"
              + (f" (ongoing, counted to {NOW:%Y-%m})" if not year_of(T.get('end_date')) else ""))
    derived += 1
site_area = (CASE.get("site") or {}).get("area_m2")
if is_empty(T.get("area_pct")) and "temporary.area_m2" in HELP and site_area:
    m2, why = HELP["temporary.area_m2"]
    try:
        set_field("temporary.area_pct", round(float(m2) / site_area * 100, 1),
                  f"derived: {m2} m² of temporary use / site area {site_area} m²; area from {why}")
        derived += 1
    except (TypeError, ValueError):
        print("temporary.area_m2 is not a number:", m2)
b = CASE.setdefault("before", {})
if is_empty(b.get("years_vacant")) and "before.original_use_end_year" in HELP:
    end_use, why = HELP["before.original_use_end_year"]
    reopen = start[0] if start else A.get("completion_year")
    try:
        end_use = int(end_use)
        yv = (reopen - end_use) if reopen else f"{NOW.year - end_use}+"
        set_field("before.years_vacant", yv, f"derived: original use ended {end_use}, new use from "
                  f"{reopen or 'not yet (still vacant)'}; end year from {why}")
        derived += 1
    except (TypeError, ValueError):
        print("before.original_use_end_year is not a year:", end_use)
asm = A.get("assessment") or {}
if isinstance(asm, dict):
    changed = False
    if is_empty(asm.get("date")):
        asm["date"] = f"{NOW:%Y-%m}"; changed = True
    cy = A.get("completion_year")
    if asm.get("years_after_completion") in (None, "") and isinstance(cy, int):
        asm["years_after_completion"] = NOW.year - cy; changed = True
    if is_empty(asm.get("phase")) and isinstance(cy, int):
        asm["phase"] = "ex_post" if cy <= NOW.year else "ongoing"; changed = True
    if changed:
        set_field("after.assessment", asm, f"derived: date = date of this run, years after completion_year {cy}")
        derived += 1

# --- 3. add the document sources (S-ids continue after the existing ones) ---
existing = CASE["case"].get("sources", [])
n = len(existing)
id_map = {}
for sid in sorted(used_sources, key=lambda x: int(x[1:])):
    s = SRC.get(sid)
    if not s:
        continue
    n += 1
    id_map[sid] = f"S{n}"
    existing.append({"id": f"S{n}", "title": s["title"] or s["url"], "author_or_publisher": "",
                     "date": "", "type": TYPE_BY_TIER.get(str(s["tier"]), "other"), "url": s["url"]})
CASE["case"]["sources"] = existing
# replace D-ids by S-ids in the notes
for block in CASE.get("provenance", {}).values():
    for k, v in block.get("field_notes", {}).items():
        for d_id, s_id in id_map.items():
            v = v.replace(f"source {d_id}", f"source {s_id}").replace(f"{d_id} (", f"{s_id} (")
        block["field_notes"][k] = v

with open(CASE_JSON, "w", encoding="utf-8") as fh:
    json.dump(CASE, fh, ensure_ascii=False, indent=2)
print(f"accepted {accepted}, own values {own}, manual values {from_manual}, left empty {rejected}, "
      f"derived {derived}; "
      f"sources added: {len(id_map)}")
print(f"LLM proposals identical to the manual case before review: {llm_same_as_manual} of {llm_proposals}")
print("Saved:", CASE_JSON)

# --- 4. comparison with the manual case ---
if MANUAL_JSON and os.path.exists(MANUAL_JSON):
    M = json.load(open(MANUAL_JSON, encoding="utf-8"))
    out = os.path.join(os.path.dirname(CASE_JSON), "doc_comparison.csv")
    same = 0
    with open(out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["field", "manual", "final", "same"])
        rows = read_csv_any(os.path.join(DOC_DIR, "review.csv"))
        rows += [{"field": k} for k in ("temporary.duration_months", "temporary.area_pct", "before.years_vacant")
                 if k not in {x["field"] for x in rows}]
        for r in rows:
            if r["field"] in HELPERS:
                continue
            mv, fv = get_in(M, r["field"]), get_in(CASE, r["field"])
            eq = json.dumps(mv, sort_keys=True, ensure_ascii=False) == json.dumps(fv, sort_keys=True, ensure_ascii=False)
            same += eq
            w.writerow([r["field"], json.dumps(mv, ensure_ascii=False), json.dumps(fv, ensure_ascii=False), eq])
    print("identical to the manual case:", same, "| Saved:", out)
