# =============================================================
# egitim_finetune.py – SegFormer'ı Ece'nin düzelttiği etiketlerle 6 malzeme sınıfına eğitir (fine-tuning)
# ve Can Batlló'da (TEST sitesi, eğitime girmez) aynı 52 noktayla puanlar.
# ÖNCE: QGIS'te düzenlemeleri kaydet ve QGIS'i kapat.
# Çalıştırma (Anaconda Prompt):
#   conda activate thesis-ai
#   python "C:\Users\eceus\Claude\Projects\Thesis Iaac\ai-sam3\egitim_finetune.py"
# Adımlar (sırayla; tek adım için:  ... egitim_finetune.py veri | egit | test):
#   1. veri : düzeltilmiş karoları (128 x 128 m) etiket resmine çevirir -> C:\gis\egitim\veri\
#             Bir karo "düzeltilmiş" sayılır: içinde en az bir poligonun sinif'i değiştiyse, yeni çizildiyse
#             ya da kontrol = 1 ise. Üst üste binen poligonlarda EN SON ÇİZİLEN kazanır.
#             sinif 0 (emin değilim) ve hiçbir poligonun olmadığı yerler eğitimde YOK SAYILIR.
#   2. egit : C:\gis\models\oem_segformer_b2 modelinden başlar, 6 sınıflı yeni model eğitir (GPU, ~5-15 dk)
#             -> C:\gis\models\mat6_<tarih_saat>\
#   3. test : yeni modelle Can Batlló 2025'i okur, 52 noktada senin cevaplarınla karşılaştırır,
#             eski sonuçla (SegFormer OEM + LiDAR füzyonu, %54.9) yan yana yazar -> C:\gis\auto\mat6_2025_<tarih_saat>\
# Sınıflar: 1 ağaç · 2 çim/bitki · 3 toprak/kum · 4 su · 5 geçirimsiz · 6 bina   (labelling guide v1.1)
# =============================================================
import os, sys, glob, json, csv, time, random
from datetime import datetime
import numpy as np

GIS_DIR = r"C:\gis"
EG = os.path.join(GIS_DIR, "egitim")
VERI = os.path.join(EG, "veri")
BASE_MODEL = os.path.join(GIS_DIR, "models", "oem_segformer_b2")
HARIC = []                              # eğitime alınmayacak siteler (ör. henüz düzeltilmemiş olanlar)
KARO = 512
CLASSES = ["agac", "cim_bitki", "toprak_kum", "su", "gecirimsiz", "bina"]      # kod 1..6 -> indeks 0..5
OEM_INIT = ["tree", "rangeland", "bareland", "water", "developed_space", "building"]  # yeni sınıfın başlangıç ağırlığı
COLORS = {1: (34, 97, 38), 2: (120, 220, 90), 3: (205, 160, 100), 4: (0, 69, 255), 5: (148, 148, 148), 6: (222, 31, 7)}
IGNORE = 255
EPOCHS, BATCH, LR_ENC, LR_HEAD, SEED = 60, 4, 3e-5, 3e-4, 42
MEAN = np.array([0.485, 0.456, 0.406], "float32")[:, None, None]
STD = np.array([0.229, 0.224, 0.225], "float32")[:, None, None]
# Can Batlló testi
CB_RGB = os.path.join(GIS_DIR, "can_batllo_RGB_2025.tif")
CB_BOUNDARY = os.path.join(GIS_DIR, "can_batllo_boundary_25831.gpkg")
CB_KEY = os.path.join(GIS_DIR, "auto", "validation_2025", "_answers_do_not_open.csv")
CB_ECE = [r"C:\Users\eceus\Claude\Projects\Thesis Iaac\ai-sam3\validation_2025.csv",
          os.path.join(GIS_DIR, "auto", "validation_2025", "validation_2025.csv")]
# Füzyon (fusion.py ile aynı eşikler): yükseklik = DSM 2024 - DTM 2010, bitki = NDVI > 0
CB_IRC = os.path.join(GIS_DIR, "can_batllo_IRC_2025.tif")
DTM_2010 = os.path.join(GIS_DIR, "buffer500_dtm.tif")
DSM_2024 = r"C:\Users\eceus\Downloads\FME_46302427_1794751361827_32788\superficies-correlacio-Catalunya-1mtif1794751361724.tif"
H_MIN, NDVI_MIN = 2.5, 0.0
MANUAL_2025 = {"trees_shrubs": 4.6, "grass_herbaceous": 13.7, "buildings": 45.6, "impervious_surface": 36.1}
JSON_NAMES = ["trees_shrubs", "grass_herbaceous", "bare_earth", "water", "impervious_surface", "buildings"]


# =============================================================
# 1. VERİ
# =============================================================
def etiket_dosyasi(site):
    d = os.path.join(EG, site)
    for n in [f"etiket_{site}_v2.gpkg", f"etiket_{site}.gpkg"]:
        if os.path.exists(os.path.join(d, n)):
            return os.path.join(d, n)
    return None


def step_veri():
    print("\n=== 1. VERİ ===")
    import geopandas as gpd, rasterio
    from rasterio import features
    from rasterio.windows import Window
    os.makedirs(VERI, exist_ok=True)
    for f in glob.glob(os.path.join(VERI, "*.npz")):      # her seferinde güncel etiketlerden baştan üretilir
        os.remove(f)
    kar = gpd.read_file(os.path.join(EG, "karolar.gpkg"))
    ozet = []
    for site in sorted(kar["site"].unique()):
        if site in HARIC:
            print(f"  {site}: HARIC listesinde, atlandı"); continue
        path = etiket_dosyasi(site)
        if path is None:
            print(f"  {site}: etiket dosyası yok"); continue
        try:
            et = gpd.read_file(path, layer="etiket", fid_as_index=True).sort_index()
        except Exception:
            et = gpd.read_file(path, layer="etiket")
        et = et[et.geometry.notna() & ~et.geometry.is_empty]
        degisti = (et["sinif"] != et["on_etiket"]) | et["on_etiket"].isna() | (et["kontrol"] == 1)
        with rasterio.open(os.path.join(EG, site, "rgb_2025.tif")) as src:
            for _, k in kar[kar["site"] == site].iterrows():
                in_k = et[et.intersects(k.geometry)]
                if in_k.empty or not degisti[in_k.index].any():
                    continue                                   # düzeltilmemiş karo -> eğitime girmez
                minx, miny, maxx, maxy = k.geometry.bounds
                r0, c0 = src.index(minx + 0.01, maxy - 0.01)
                win = Window(c0, r0, KARO, KARO)                 # her karo tam 512 x 512 piksel
                rgb = src.read([1, 2, 3], window=win, boundless=True)
                T = src.window_transform(win)
                shapes = [(g, int(s)) for g, s in zip(in_k.geometry, in_k["sinif"]) if s == s]
                lab = features.rasterize(shapes, out_shape=rgb.shape[1:], transform=T, fill=IGNORE, dtype="uint8")
                lab = np.where((lab >= 1) & (lab <= 6), lab - 1, IGNORE).astype(np.uint8)
                if (lab != IGNORE).mean() < 0.2:
                    print(f"  {k['karo']}: %80'den fazlası etiketsiz, atlandı"); continue
                np.savez_compressed(os.path.join(VERI, k["karo"] + ".npz"), rgb=rgb.astype(np.uint8), lab=lab)
                pay = {CLASSES[i]: round(float((lab == i).mean()) * 100, 1) for i in range(6)}
                ozet.append({"karo": k["karo"], **pay, "yok_sayilan": round(float((lab == IGNORE).mean()) * 100, 1)})
    if not ozet:
        raise SystemExit("Düzeltilmiş karo bulunamadı. QGIS'te kaydettiğinden emin ol.")
    with open(os.path.join(VERI, "veri_ozeti.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(ozet[0])); w.writeheader(); w.writerows(ozet)
    print(f"  {len(ozet)} karo hazır ({', '.join(sorted({o['karo'].rsplit('_', 1)[0] for o in ozet}))})")
    tot = {c: round(np.mean([o[c] for o in ozet]), 1) for c in CLASSES}
    print("  Ortalama sınıf payları (%):", tot)


# =============================================================
# 2. EĞİT
# =============================================================
def load_tiles():
    files = sorted(glob.glob(os.path.join(VERI, "*.npz")))
    if not files:
        raise SystemExit("Veri yok, önce 'veri' adımı.")
    return [(os.path.basename(f)[:-4], np.load(f)["rgb"], np.load(f)["lab"]) for f in files]


def augment(rgb, lab, rng):
    k = rng.integers(4)
    rgb, lab = np.rot90(rgb, k, (1, 2)), np.rot90(lab, k)
    if rng.random() < 0.5:
        rgb, lab = rgb[:, :, ::-1], lab[:, ::-1]
    x = rgb.astype("float32") / 255.0
    x = (x - x.mean()) * rng.uniform(0.9, 1.1) + x.mean() * rng.uniform(0.9, 1.1)   # kontrast + parlaklık
    return np.clip(x, 0, 1), lab.copy()


def step_egit():
    print("\n=== 2. EĞİT ===")
    import torch, torch.nn.functional as F
    from transformers import SegformerForSemanticSegmentation
    torch.manual_seed(SEED); rng = np.random.default_rng(SEED); random.seed(SEED)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tiles = load_tiles()
    val_idx = set(range(2, len(tiles), 6)) if len(tiles) >= 10 else set()      # her 6 karodan biri kontrol için
    tr = [t for i, t in enumerate(tiles) if i not in val_idx]
    va = [t for i, t in enumerate(tiles) if i in val_idx]
    print(f"  Eğitim karosu: {len(tr)} | kontrol karosu: {len(va)} ({', '.join(t[0] for t in va)}) | cihaz: {dev}")

    # başlangıç: OEM modeli; yeni 6 sınıflı başlığın ağırlıkları benzer OEM sınıflarından kopyalanır
    old = SegformerForSemanticSegmentation.from_pretrained(BASE_MODEL)
    oname = [old.config.id2label[i] for i in range(old.config.num_labels)]
    W, b = old.decode_head.classifier.weight.data, old.decode_head.classifier.bias.data
    model = SegformerForSemanticSegmentation.from_pretrained(
        BASE_MODEL, num_labels=6, id2label={i: c for i, c in enumerate(CLASSES)},
        label2id={c: i for i, c in enumerate(CLASSES)}, ignore_mismatched_sizes=True)
    idx = [oname.index(n) for n in OEM_INIT]
    model.decode_head.classifier.weight.data = W[idx].clone()
    model.decode_head.classifier.bias.data = b[idx].clone()
    del old
    model.to(dev)

    # sınıf ağırlıkları: az olan sınıf biraz daha önemli (karekök, 0.5-3 arası)
    cnt = np.array([sum(int((t[2] == i).sum()) for t in tr) for i in range(6)], "float64")
    freq = cnt / max(cnt.sum(), 1)
    wts = np.where(freq > 0, np.sqrt(np.median(freq[freq > 0]) / np.maximum(freq, 1e-9)), 0)
    wts = np.clip(wts, 0.5, 3.0) * (freq > 0)
    print("  Sınıf pikseli (%):", {c: round(f * 100, 1) for c, f in zip(CLASSES, freq)})
    print("  Sınıf ağırlığı   :", {c: round(float(w), 2) for c, w in zip(CLASSES, wts)})
    crit = torch.nn.CrossEntropyLoss(weight=torch.tensor(wts, dtype=torch.float32, device=dev), ignore_index=IGNORE)

    head = [p for n, p in model.named_parameters() if n.startswith("decode_head")]
    enc = [p for n, p in model.named_parameters() if not n.startswith("decode_head")]
    opt = torch.optim.AdamW([{"params": enc, "lr": LR_ENC}, {"params": head, "lr": LR_HEAD}], weight_decay=0.01)
    steps = EPOCHS * max(1, (len(tr) + BATCH - 1) // BATCH)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: (1 - s / steps) ** 0.9)
    use_amp = dev == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    mt, sd = torch.tensor(MEAN, device=dev), torch.tensor(STD, device=dev)

    def evaluate(data):
        model.eval(); conf = np.zeros((6, 6), np.int64)
        with torch.inference_mode():
            for _, rgb, lab in data:
                x = (torch.from_numpy(rgb.astype("float32") / 255.0).to(dev) - mt) / sd
                lg = model(pixel_values=x[None]).logits
                p = F.interpolate(lg, size=lab.shape, mode="bilinear", align_corners=False).argmax(1)[0].cpu().numpy()
                m = lab != IGNORE
                conf += np.bincount(lab[m].astype(int) * 6 + p[m], minlength=36).reshape(6, 6)
        iou = [conf[i, i] / (conf[i].sum() + conf[:, i].sum() - conf[i, i]) if conf[i].sum() else np.nan for i in range(6)]
        return float(np.trace(conf) / max(conf.sum(), 1)), iou

    run = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(GIS_DIR, "models", f"mat6_{run}")
    os.makedirs(out, exist_ok=True)
    best, log, t0 = -1, [], time.time()
    for ep in range(1, EPOCHS + 1):
        model.train(); order = rng.permutation(len(tr)); losses = []
        for i in range(0, len(order), BATCH):
            xs, ys = zip(*[augment(tr[j][1], tr[j][2], rng) for j in order[i:i + BATCH]])
            x = (torch.from_numpy(np.stack(xs)).to(dev) - mt) / sd
            y = torch.from_numpy(np.stack(ys).astype(np.int64)).to(dev)
            with torch.autocast("cuda", dtype=torch.float16, enabled=use_amp):
                lg = model(pixel_values=x).logits
                lg = F.interpolate(lg, size=y.shape[1:], mode="bilinear", align_corners=False)
                loss = crit(lg.float(), y)
            opt.zero_grad(); scaler.scale(loss).backward(); scaler.step(opt); scaler.update(); sched.step()
            losses.append(loss.item())
        row = {"epoch": ep, "loss": round(float(np.mean(losses)), 4)}
        if va and (ep % 5 == 0 or ep == EPOCHS):
            acc, iou = evaluate(va)
            miou = float(np.nanmean(iou))
            row.update({"val_acc": round(acc * 100, 1), "val_miou": round(miou * 100, 1),
                        **{f"iou_{c}": (round(v * 100, 1) if v == v else None) for c, v in zip(CLASSES, iou)}})
            if miou > best:
                best = miou; model.save_pretrained(out); row["kaydedildi"] = 1
        log.append(row)
        print(f"  epoch {ep:3d}/{EPOCHS}  kayıp {row['loss']:.3f}" +
              (f"  | kontrol doğruluk %{row['val_acc']}  mIoU %{row['val_miou']}" if "val_acc" in row else "") +
              ("  * en iyi" if row.get("kaydedildi") else "") + f"  ({time.time() - t0:.0f} s)")
    if not va:
        model.save_pretrained(out)
    with open(os.path.join(out, "egitim_log.json"), "w", encoding="utf-8") as f:
        json.dump({"base_model": BASE_MODEL, "classes": CLASSES, "tiles_train": [t[0] for t in tr],
                   "tiles_val": [t[0] for t in va], "excluded_sites": HARIC, "epochs": EPOCHS, "batch": BATCH,
                   "lr_encoder": LR_ENC, "lr_head": LR_HEAD, "class_weights": [round(float(w), 3) for w in wts],
                   "labelling_guide": "v1.1 (19 Nov 2026)", "log": log}, f, ensure_ascii=False, indent=2)
    with open(os.path.join(GIS_DIR, "models", "mat6_son.txt"), "w") as f:
        f.write(out)
    print("  Model kaydedildi:", out)


# =============================================================
# 3. TEST – Can Batlló
# =============================================================
def step_test():
    print("\n=== 3. TEST: Can Batlló 2025 ===")
    import torch, torch.nn.functional as F, rasterio
    from rasterio import features
    import geopandas as gpd
    from PIL import Image
    from transformers import SegformerForSemanticSegmentation
    mp = open(os.path.join(GIS_DIR, "models", "mat6_son.txt")).read().strip()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = SegformerForSemanticSegmentation.from_pretrained(mp).eval().to(dev)
    print("  Model:", mp)
    with rasterio.open(CB_RGB) as s:
        rgb = s.read([1, 2, 3]).astype("float32") / 255.0; T, crs, H, W = s.transform, s.crs, s.height, s.width
    x_all = (rgb - MEAN) / STD
    TILE, STRIDE = 512, 384
    def starts(n):
        s = list(range(0, max(n - TILE, 0) + 1, STRIDE))
        if s[-1] + TILE < n: s.append(n - TILE)
        return s
    wy = np.hanning(TILE + 2)[1:-1].astype("float32"); wwin = np.outer(wy, wy) + 1e-3
    acc = np.zeros((6, H, W), np.float32); wsum = np.zeros((H, W), np.float32)
    with torch.inference_mode():
        for r0 in starts(H):
            for c0 in starts(W):
                t = torch.from_numpy(x_all[:, r0:r0 + TILE, c0:c0 + TILE].copy())[None].to(dev)
                h, w = t.shape[2:]
                p = F.interpolate(model(pixel_values=t).logits, size=(h, w), mode="bilinear",
                                  align_corners=False).softmax(1)[0].cpu().numpy()
                acc[:, r0:r0 + h, c0:c0 + w] += p * wwin[:h, :w]; wsum[r0:r0 + h, c0:c0 + w] += wwin[:h, :w]
    prob = acc / wsum
    cls = (prob.argmax(0) + 1).astype(np.uint8)                     # kod 1..6

    # --- füzyon: yükseklik + NDVI kuralları (fusion.py'nin malzeme sınıflı hali) ---
    from rasterio.warp import reproject, Resampling
    from scipy import ndimage
    def onto_grid(path, band=1):
        o = np.full((H, W), np.nan, np.float32)
        with rasterio.open(path) as s2:
            reproject(rasterio.band(s2, band), o, src_transform=s2.transform, src_crs=s2.crs, src_nodata=s2.nodata,
                      dst_transform=T, dst_crs=crs, resampling=Resampling.bilinear, dst_nodata=np.nan)
        return o
    dsm = next(iter(glob.glob(os.path.join(GIS_DIR, "dsm_2024", "superficies-correlacio*.tif"))), DSM_2024)
    fused, rules = None, {}
    if all(os.path.exists(p) for p in [dsm, DTM_2010, CB_IRC]):
        hgt = onto_grid(dsm) - onto_grid(DTM_2010)
        nir, red = onto_grid(CB_IRC, 1), onto_grid(CB_IRC, 2)
        ndvi = np.where((nir + red) > 0, (nir - red) / np.maximum(nir + red, 1e-6), np.nan)
        valid = ~np.isnan(hgt) & ~np.isnan(ndvi)
        tall = (hgt > H_MIN) & valid
        cell = max(1, int(round(2.0 / abs(T.a))))
        tall_core = ndimage.binary_erosion(tall, iterations=cell)
        low_sure = ~ndimage.binary_dilation(tall, iterations=cell) & valid
        veg = (ndvi > NDVI_MIN) & valid
        ground = np.where(prob[2] >= prob[4], 3, 5).astype(np.uint8)   # alçak + bitki değil: toprak mı geçirimsiz mi (model karar verir)
        fused = cls.copy()
        k1 = tall_core & veg & (cls != 1)
        k2 = tall_core & ~veg & np.isin(cls, [2, 3, 5])
        k3 = low_sure & (cls == 6)
        k4 = low_sure & (cls == 1) & ~veg                              # fotogrametrik DSM: bitkili ağaç korunur
        fused[k1] = 1; fused[k2] = 6
        for k in (k3, k4):
            fused[k & veg] = 2; fused[k & ~veg] = ground[k & ~veg]
        rules = {n: round(float(k.mean()) * 100, 2) for n, k in
                 [("K1 tall+veg->tree", k1), ("K2 tall+not veg+ground->building", k2),
                  ("K3 low+building->grass/ground", k3), ("K4 low+tree not veg->ground", k4)]}
        print("  Füzyon: yükseklik =", os.path.basename(dsm), "- DTM 2010 | kuralların değiştirdiği (% görüntü):", rules)
    else:
        print("  Füzyon atlandı: DSM 2024 / DTM 2010 / IRC 2025 dosyalarından biri bulunamadı.")
    out = os.path.join(GIS_DIR, "auto", "mat6_2025_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(out, exist_ok=True)
    with rasterio.open(os.path.join(out, "mat6_classes.tif"), "w", driver="GTiff", height=H, width=W, count=1,
                       dtype="uint8", crs=crs, transform=T, compress="deflate") as d:
        d.write(cls, 1); d.write_colormap(1, {0: (0, 0, 0, 255), **{k: v + (255,) for k, v in COLORS.items()}})
    if fused is not None:
        with rasterio.open(os.path.join(out, "mat6_fused_classes.tif"), "w", driver="GTiff", height=H, width=W, count=1,
                           dtype="uint8", crs=crs, transform=T, compress="deflate") as d:
            d.write(fused, 1); d.write_colormap(1, {0: (0, 0, 0, 255), **{k: v + (255,) for k, v in COLORS.items()}})
    site = gpd.read_file(CB_BOUNDARY).to_crs(crs)
    inside = features.geometry_mask(site.geometry, out_shape=(H, W), transform=T, invert=True)
    lc = {JSON_NAMES[i]: round(float((cls[inside] == i + 1).mean()) * 100, 1) for i in range(6)}
    lcf = {JSON_NAMES[i]: round(float((fused[inside] == i + 1).mean()) * 100, 1) for i in range(6)} if fused is not None else {}
    print("\n  Site içi paylar (%):")
    print(f"    {'alan':20s} {'yeni':>6s} {'+füzyon':>8s} {'elle':>6s}")
    for k, v in lc.items():
        m = MANUAL_2025.get(k)
        print(f"    {k:20s} {v:6.1f} {lcf.get(k, float('nan')):8.1f} " + (f"{m:6.1f}" if m is not None else "     -"))

    # 52 nokta: senin cevapların (kör kontrol) – yeni model ve eski füzyon sonucu
    ece_path = next((p for p in CB_ECE if os.path.exists(p)), None)
    if ece_path is None or not os.path.exists(CB_KEY):
        print("  Nokta dosyaları bulunamadı, puanlama atlandı."); return
    txt = open(ece_path, encoding="utf-8-sig").read()
    delim = ";" if txt.count(";") >= txt.count(",") else ","
    ece = {r["point_id"]: (r.get("ece_code") or "").strip() for r in csv.DictReader(txt.splitlines(), delimiter=delim)}
    pts = list(csv.DictReader(open(CB_KEY, encoding="utf-8")))
    rows = []
    for p in pts:
        e = ece.get(p["point_id"], "")
        if not e.isdigit() or int(e) not in range(1, 7):
            continue
        r, c = rasterio.transform.rowcol(T, float(p["x"]), float(p["y"]))
        rows.append((int(e), int(cls[r, c]), int(p["ai_code"]), int(fused[r, c]) if fused is not None else int(cls[r, c])))
    def report(name, k):
        n = len(rows); ok = sum(1 for r in rows if r[0] == r[k])
        merged = sum(1 for r in rows if r[0] == r[k] or ({r[0], r[k]} <= {3, 5}))
        print(f"\n  {name}: genel doğruluk %{ok / n * 100:.1f}  ({ok}/{n})  | toprak+geçirimsiz birleşik %{merged / n * 100:.1f}")
        per = {}
        for g in range(1, 7):
            ref = sum(1 for r in rows if r[0] == g); pred = sum(1 for r in rows if r[k] == g)
            hit = sum(1 for r in rows if r[0] == g and r[k] == g)
            per[JSON_NAMES[g - 1]] = {"n_ece": ref, "n_ai": pred,
                                       "producer_accuracy": round(hit / ref * 100, 1) if ref else None,
                                       "user_accuracy": round(hit / pred * 100, 1) if pred else None}
            if ref or pred:
                print(f"    {JSON_NAMES[g - 1]:20s} Ece {ref:3d}  AI {pred:3d}  üretici %{per[JSON_NAMES[g-1]]['producer_accuracy']}"
                      f"  kullanıcı %{per[JSON_NAMES[g-1]]['user_accuracy']}")
        return {"overall_accuracy_pct": round(ok / n * 100, 1), "merged_bare_impervious_pct": round(merged / n * 100, 1),
                "per_class": per}
    old = report("ESKİ (OEM + LiDAR füzyonu)", 2)
    new = report("YENİ (fine-tuned, sadece görüntü)", 1)
    newf = report("YENİ + FÜZYON (yükseklik + NDVI)", 3) if fused is not None else None
    print("\n  Karışıklık (satır = Ece, sütun = yeni model + füzyon):")
    print("    " + " " * 18 + "".join(f"{n[:6]:>8s}" for n in JSON_NAMES))
    for g in range(1, 7):
        print(f"    {JSON_NAMES[g - 1]:18s}" + "".join(f"{sum(1 for r in rows if r[0] == g and r[3] == q):8d}" for q in range(1, 7)))
    rgb8 = (rgb.transpose(1, 2, 0) * 255).astype(np.uint8)
    col = np.zeros((H, W, 3), np.uint8)
    colf = np.zeros((H, W, 3), np.uint8)
    for k, v in COLORS.items():
        col[cls == k] = v; colf[(fused if fused is not None else cls) == k] = v
    prev = Image.new("RGB", (W * 3 + 40, H), "white")       # ortofoto | yeni model | yeni + füzyon
    prev.paste(Image.fromarray(rgb8), (0, 0)); prev.paste(Image.fromarray(col), (W + 20, 0))
    prev.paste(Image.fromarray(colf), (2 * W + 40, 0))
    prev.thumbnail((2400, 2400)); prev.save(os.path.join(out, "mat6_preview.png"))
    with open(os.path.join(out, "mat6_result.json"), "w", encoding="utf-8") as f:
        json.dump({"site": "Can Batlló", "year": "2025", "model": mp, "land_cover_pct": lc, "manual_2025": MANUAL_2025,
                   "land_cover_pct_fused": lcf, "fusion_rules_pct_of_image": rules,
                   "n_points": len(rows), "old_fusion": old, "new_finetuned": new, "new_finetuned_fused": newf,
                   "note": "test site excluded from training; same 52-point blind check as 18 Nov 2026",
                   "provenance": "ai_detected"}, f, ensure_ascii=False, indent=2)
    print("\n  Sonuçlar:", out, "(mat6_classes.tif QGIS'te aç, mat6_preview.png hızlı bakış)")


if __name__ == "__main__":
    steps = sys.argv[1:] or ["veri", "egit", "test"]
    for s in steps:
        {"veri": step_veri, "egit": step_egit, "test": step_test}[s]()
    print("\nBitti.")
