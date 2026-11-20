# =============================================================
# ai_arazi.py – fine-tuned görüntü modeliyle bir sitenin arazi örtüsü (land_cover_pct, 6 sınıf)
# auto_case.py'den ÖNCE, Anaconda Prompt'ta çalıştırılır (QGIS'in içinde değil):
#   conda activate thesis-ai
#   python "C:\Users\eceus\Claude\Projects\Thesis Iaac\ai-sam3\ai_arazi.py"
# Ayarlar: aşağıdaki SITE_NAME ve BOUNDARY_FILE, auto_case.py'deki ile AYNI olmalı.
# Ne yapar (her yıl için):
#   1. ICGC renkli (RGB) ve kızılötesi (IRC) ortofoto, 25 cm, site sınırının kutusu (önbellek: auto_case klasörü)
#   2. Ece'nin eğittiği son modeli (C:\gis\models\mat6_son.txt) çalıştırır: 6 malzeme sınıfı
#   3. Füzyon: yükseklik (2010 LiDAR nDSM; 2025 DSM 2024 - DTM 2010) + NDVI kuralları
#   4. Site içindeki payları yazar -> C:\gis\auto_case\<site>\ai_landcover.json (+ sınıf rasterları)
# Sonra QGIS'te auto_case.py ve hemen ardından auto_case_12b_ai.py: land_cover_pct'yi bu JSON'dan alır.
# Sınıflar (labelling guide v1.1): 1 ağaç · 2 çim/bitki · 3 toprak/kum · 4 su · 5 geçirimsiz · 6 bina
# =============================================================
import os, io, sys, json, glob, unicodedata
from datetime import datetime
import numpy as np
import requests
from PIL import Image

# --- ayarlar (auto_case.py ile aynı) ---
SITE_NAME = "Can Batlló"
BOUNDARY_FILE = r"C:\gis\can_batllo_boundary_25831.gpkg"
YEARS = [2010, 2025]

GIS_DIR = r"C:\gis"
CRS = "EPSG:25831"
WMS = "https://geoserveis.icgc.cat/servei/catalunya/orto-territorial/wms"
RES = 0.25
# yükseklik dosyaları (auto_case.py adım 12 ile aynı; şimdilik Can Batlló çevresi için hazırlanmış)
DTM = os.path.join(GIS_DIR, "buffer500_dtm.tif")
NDSM_2010 = os.path.join(GIS_DIR, "buffer500_ndsm.tif")
DSM_2024 = next(iter(glob.glob(os.path.join(GIS_DIR, "dsm_2024", "superficies-correlacio*.tif"))),
                r"C:\Users\eceus\Downloads\FME_46302427_1794751361827_32788\superficies-correlacio-Catalunya-1mtif1794751361724.tif")
H_MIN, NDVI_MIN = 2.5, 0.0
NAMES = {1: "trees_shrubs", 2: "grass_herbaceous", 3: "bare_earth", 4: "water", 5: "impervious_surface", 6: "buildings"}
COLORS = {1: (34, 97, 38), 2: (120, 220, 90), 3: (205, 160, 100), 4: (0, 69, 255), 5: (148, 148, 148), 6: (222, 31, 7)}
# Bilinen doğrulamalar (tezde raporlanan); yeni siteler için boş
VALIDATION = {("can_batllo", 2025): "blind 51-point check by Ece (20 Nov 2026): model + fusion 74.5 % "
                                     "(kappa 0.64); human self-consistency 80.4 %; bare_earth producer 50 %, user 100 %"}


def slugify(text):
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(c if c.isalnum() else "_" for c in t.lower()).strip("_")


SLUG = slugify(SITE_NAME)
SITE_DIR = os.path.join(GIS_DIR, "auto_case", SLUG)
DATA_DIR = os.path.join(SITE_DIR, "data")
AI_DIR = os.path.join(SITE_DIR, "ai_landcover")
os.makedirs(DATA_DIR, exist_ok=True); os.makedirs(AI_DIR, exist_ok=True)

import rasterio
from rasterio import features
from rasterio.transform import from_origin
from rasterio.warp import reproject, Resampling
import geopandas as gpd

site = gpd.read_file(BOUNDARY_FILE).to_crs(CRS)
minx, miny, maxx, maxy = site.total_bounds
minx, miny = np.floor(minx / 2) * 2, np.floor(miny / 2) * 2           # auto_case ile aynı: 2 m'ye yuvarla
maxx, maxy = np.ceil(maxx / 2) * 2, np.ceil(maxy / 2) * 2
W, H = int(round((maxx - minx) / RES)), int(round((maxy - miny) / RES))
T = from_origin(minx, maxy, RES, RES)
inside = features.geometry_mask(site.geometry, out_shape=(H, W), transform=T, invert=True)
print(f"Site: {SITE_NAME} | {maxx - minx:.0f} x {maxy - miny:.0f} m | çıktı: {SITE_DIR}")


def wms_download(layer, year, path):
    if os.path.exists(path):
        print("  önbellekten:", os.path.basename(path)); return path
    img = np.zeros((H, W, 3), np.uint8); TILE = 1000
    for r0 in range(0, H, TILE):
        for c0 in range(0, W, TILE):
            h, w = min(TILE, H - r0), min(TILE, W - c0)
            x0, y1 = minx + c0 * RES, maxy - r0 * RES
            p = {"SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.3.0", "LAYERS": layer, "STYLES": "",
                 "CRS": CRS, "BBOX": f"{x0},{y1 - h * RES},{x0 + w * RES},{y1}", "WIDTH": w, "HEIGHT": h,
                 "FORMAT": "image/jpeg"}
            if "serie_anual" in layer:
                p["TIME"] = str(year)
            r = requests.get(WMS, params=p, timeout=120)
            if "image" not in r.headers.get("Content-Type", ""):
                raise SystemExit(f"ICGC hata döndürdü ({layer} {year}):\n" + r.text[:400])
            img[r0:r0 + h, c0:c0 + w] = np.array(Image.open(io.BytesIO(r.content)).convert("RGB"))
    with rasterio.open(path, "w", driver="GTiff", height=H, width=W, count=3, dtype="uint8", crs=CRS,
                       transform=T, compress="deflate") as d:
        d.write(img.transpose(2, 0, 1))
    print("  indirildi:", os.path.basename(path)); return path


def onto_grid(path, band=1):
    o = np.full((H, W), np.nan, np.float32)
    with rasterio.open(path) as s:
        reproject(rasterio.band(s, band), o, src_transform=s.transform, src_crs=s.crs, src_nodata=s.nodata,
                  dst_transform=T, dst_crs=CRS, resampling=Resampling.bilinear, dst_nodata=np.nan)
    return o


# --- model ---
import torch, torch.nn.functional as F
from transformers import SegformerForSemanticSegmentation
from scipy import ndimage
MODEL = open(os.path.join(GIS_DIR, "models", "mat6_son.txt")).read().strip()
dev = "cuda" if torch.cuda.is_available() else "cpu"
model = SegformerForSemanticSegmentation.from_pretrained(MODEL).eval().to(dev)
print("Model:", MODEL, "| cihaz:", dev)
MEAN = np.array([0.485, 0.456, 0.406], "float32")[:, None, None]
STD = np.array([0.229, 0.224, 0.225], "float32")[:, None, None]
TILE, STRIDE = 512, 384


def starts(n):
    s = list(range(0, max(n - TILE, 0) + 1, STRIDE))
    if s[-1] + TILE < n: s.append(n - TILE)
    return s


wy = np.hanning(TILE + 2)[1:-1].astype("float32"); wwin = np.outer(wy, wy) + 1e-3

OUT = {"site": SITE_NAME, "model": MODEL, "created": datetime.now().isoformat(timespec="seconds"),
       "classes": "labelling guide v1.1 (material-based): trees_shrubs, grass_herbaceous, bare_earth, water, "
                  "impervious_surface, buildings", "script": "ai_arazi.py", "years": {}}
for year in YEARS:
    print(f"\n--- {year} ---")
    rgb_p = wms_download("ortofoto_color_serie_anual", year, os.path.join(DATA_DIR, f"rgb_site_{year}_025m_ai.tif"))
    irc_p = wms_download(f"ortofoto_25cm_infraroig_{year}", year,      # auto_case.py ile aynı katman
                         os.path.join(DATA_DIR, f"irc_site_{year}_025m_ai.tif"))
    with rasterio.open(rgb_p) as s:
        x = ((s.read([1, 2, 3]).astype("float32") / 255.0) - MEAN) / STD
    acc = np.zeros((6, H, W), np.float32); wsum = np.zeros((H, W), np.float32)
    with torch.inference_mode():
        for r0 in starts(H):
            for c0 in starts(W):
                t = torch.from_numpy(x[:, r0:r0 + TILE, c0:c0 + TILE].copy())[None].to(dev)
                h, w = t.shape[2:]
                p = F.interpolate(model(pixel_values=t).logits, size=(h, w), mode="bilinear",
                                  align_corners=False).softmax(1)[0].cpu().numpy()
                acc[:, r0:r0 + h, c0:c0 + w] += p * wwin[:h, :w]; wsum[r0:r0 + h, c0:c0 + w] += wwin[:h, :w]
    prob = acc / wsum
    cls = (prob.argmax(0) + 1).astype(np.uint8)

    # füzyon (fusion.py / egitim_finetune.py ile aynı kurallar)
    hsrc = None
    if year == 2010 and os.path.exists(NDSM_2010):
        hgt, hsrc = onto_grid(NDSM_2010), "LiDAR 2010 nDSM"
    elif year != 2010 and os.path.exists(DSM_2024) and os.path.exists(DTM):
        hgt, hsrc = onto_grid(DSM_2024) - onto_grid(DTM), "ICGC DSM 2024 - LiDAR 2010 DTM"
    fused, rules = cls.copy(), {}
    if hsrc:
        nir, red = onto_grid(irc_p, 1), onto_grid(irc_p, 2)
        ndvi = np.where((nir + red) > 0, (nir - red) / np.maximum(nir + red, 1e-6), np.nan)
        valid = ~np.isnan(hgt) & ~np.isnan(ndvi)
        tall = (hgt > H_MIN) & valid
        cell = max(1, int(round(2.0 / RES)))
        tall_core = ndimage.binary_erosion(tall, iterations=cell)
        low_sure = ~ndimage.binary_dilation(tall, iterations=cell) & valid
        veg = (ndvi > NDVI_MIN) & valid
        ground = np.where(prob[2] >= prob[4], 3, 5).astype(np.uint8)
        k1 = tall_core & veg & (cls != 1)
        k2 = tall_core & ~veg & np.isin(cls, [2, 3, 5])
        k3 = low_sure & (cls == 6)
        k4 = low_sure & (cls == 1) & ~veg
        if year == 2010:
            k4 = low_sure & (cls == 1)                       # LiDAR yılı: alçak "ağaç" her durumda düzeltilir
        fused[k1] = 1; fused[k2] = 6
        for k in (k3, k4):
            fused[k & veg] = 2; fused[k & ~veg] = ground[k & ~veg]
        rules = {n: round(float(k[inside].mean()) * 100, 2) for n, k in
                 [("K1 tall+veg->tree", k1), ("K2 tall+not veg+ground->building", k2),
                  ("K3 low+building->grass/ground", k3), ("K4 low+tree->grass/ground", k4)]}
        print("  füzyon:", hsrc, "| değişen (% site):", rules)
    else:
        print("  füzyon atlandı (yükseklik dosyası yok) – sadece görüntü")

    for name, arr in [(f"{year}_classes_image_only.tif", cls), (f"{year}_classes.tif", fused)]:
        with rasterio.open(os.path.join(AI_DIR, name), "w", driver="GTiff", height=H, width=W, count=1, dtype="uint8",
                           crs=CRS, transform=T, compress="deflate") as d:
            d.write(arr, 1); d.write_colormap(1, {0: (0, 0, 0, 255), **{k: v + (255,) for k, v in COLORS.items()}})
    lc = {NAMES[k]: round(float((fused[inside] == k).mean()) * 100, 1) for k in NAMES}
    lc_img = {NAMES[k]: round(float((cls[inside] == k).mean()) * 100, 1) for k in NAMES}
    val = VALIDATION.get((SLUG, year))
    OUT["years"][str(year)] = {
        "land_cover_pct": lc, "land_cover_pct_image_only": lc_img,
        "fusion": {"height": hsrc, "ndvi": "ICGC IRC (NDVI > 0)", "rules_changed_pct_of_site": rules} if hsrc else None,
        "images": {"rgb": rgb_p, "irc": irc_p}, "raster": os.path.join(AI_DIR, f"{year}_classes.tif"),
        "provenance": "ai_verified" if val else "ai_detected",
        "validation": val or ("not validated for this year; model trained on ICGC 2025 imagery" if year != 2025
                              else "not validated for this site")}
    print("  land_cover_pct:", lc)

with open(os.path.join(SITE_DIR, "ai_landcover.json"), "w", encoding="utf-8") as f:
    json.dump(OUT, f, ensure_ascii=False, indent=2)
print("\nKaydedildi:", os.path.join(SITE_DIR, "ai_landcover.json"))
print("Şimdi QGIS Python konsolunda: önce auto_case.py, hemen ardından auto_case_12b_ai.py")
