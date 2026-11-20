# The-City-In-Waiting
## Scripts: reading a vacant site

The system reads a site in three parts. Each part fills its own fields of the same case JSON. All scripts are in `data/scripts/`.

| Folder | Reads | Data sources | Runs in |
|---|---|---|---|
| `spatial_reading/` | Spatial fields: boundary, location, heights, vegetation, parks, connectivity, cadastre, geology, flood risk, zoning, surroundings | ICGC orthophotos and LiDAR / DSM, OpenStreetMap, cadastre, Catalan map services | QGIS Python console |
| `visual_reading/` | Surface land cover from 25 cm aerial images: trees, grass, bare earth, water, impervious, buildings | ICGC orthophotos + fine-tuned SegFormer model | Conda environment `thesis-ai` |
| `document_reading/` | Fields that maps cannot show: use history, years vacant, ownership, temporary use, actors, costs, new use | Documents and web sources, read by an LLM and checked by hand | Python |

### 1. Spatial reading

`main.py` is the only file to run. It loads `helpers.py` (shared functions) and `settings.py` (site settings, the only file changed per site). It then runs the steps in `steps/` in order:

s02 boundary → s03 OSM location → s04 case JSON → s06 orthophotos → s07 NDVI → s08–s10 green spaces → s11 connectivity and water → s12 heights and land cover → s13–s14 site and context rules → s15 cadastre → s16 geology, flood, zoning → s17 surroundings → s18 layout and surface rules

Each step file lists at its top what it uses from earlier steps and what it makes for later ones. If a step fails, set `START_AT` in `main.py` to that step and run again.

It needs QGIS's own libraries (`qgis.core`, `processing`), so it only runs inside QGIS.

### 2. Visual reading (AI)

**`training/`** (done once; paused for now)
1. `egitim_hazirla.py`: chooses training tiles from Barcelona sites and makes pre-labels.
2. Labels are corrected by hand in QGIS.
3. `geometri_onar.py`: repairs invalid label polygons.
4. `egitim_finetune.py`: fine-tunes SegFormer-B2, starting from an OpenEarthMap checkpoint, into 6 material classes.
5. `nokta_kontrol.py`: blind point check on Can Batlló. Model plus height / NDVI fusion: 74.5% agreement (kappa 0.64). For comparison, a repeated human check agreed with itself 80.4% of the time.

**`apply/`** (per site)
1. `ai_arazi.py`: runs the model on the site and fuses it with LiDAR / DSM height and NDVI.
2. `auto_case_12b_ai.py`: writes the 2025 land cover and surface substrate into the case JSON, replacing the rule-based estimate.

These scripts use PyTorch with the GPU, `transformers` and `rasterio`. They run in a separate conda environment, because installing them into QGIS's Python would conflict with its libraries and running the model there freezes QGIS. Conda only manages the environment and keeps these library versions compatible.

### 3. Document reading

1. `doc_sources.py`: finds candidate sources from open, citable catalogues, without an LLM: the sources already in the manual case JSON, Wikipedia (ca / es / en) and the references it cites, and OpenAlex (academic works). Each source gets a reliability tier (1 official, 2 academic, 3 institutional, 4 press, 5 other) and a suggestion. Output: `sources_candidates.csv`, where the user marks which sources to keep.
2. `doc_extract.py`: an LLM reads the kept sources and proposes a value for each document field, with the quote it is based on. Output: `review.csv`.
3. The user reviews each proposal in `review.csv` (accept, reject, keep the manual value, or write their own).
4. `doc_merge.py`: writes the reviewed values into the case JSON and marks each field as "AI-drafted, checked by Ece", with its source.

### Not in this repository

Model weights, orthophotos, LiDAR and other rasters are too large for GitHub and stay on the local machine (`C:\gis\`).
