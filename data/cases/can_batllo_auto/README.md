# Can Batlló: automatic case (16 Nov 2026)

Case JSON filled by the scripts in `data/scripts/`, then reviewed by Ece. Compare with the manual case `data/cases/can_batllo.json`.

| File | What it is |
|---|---|
| `can_batllo.json` | Final case JSON (run 20261116_204608): auto_case.py steps 1–18 + reviewed document fields (doc_merge.py). 92 of 99 fields filled. |
| `comparison.csv` | Measured and rule-based fields: manual vs script |
| `doc_comparison.csv` | Document fields after review: manual vs final |
| `review.csv` | LLM proposals (doc_extract.py v0.13, gpt-5.4-mini) with quotes, sources and Ece's decisions (y = accept, n = leave empty, m = manual value, or own value) |
| `sources_candidates.csv` | Candidate sources found by doc_sources.py (tier 1 official … tier 5 other) |
| `objects_draft.json` | Objects inventory draft: names, footprints, dimensions and fate suggestions from OSM + LiDAR 2010 / DSM 2024. Interpretive fields (materials, year, condition, fate, design potential) still to be filled by Ece; `_check` blocks to delete after checking. |

Where the fields come from: 50 data and rules, 15 LLM proposals accepted by Ece, 27 manual values, 7 empty (maintenance, human_traces, terrain_vague, form_tag, years_vacant, users_count, jobs_created).

Not in the repo (kept in `C:\gis`): rasters, LiDAR, downloaded PDFs and full source texts, LLM answer cache.
