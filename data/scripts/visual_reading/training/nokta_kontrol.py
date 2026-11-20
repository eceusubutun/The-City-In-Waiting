# =============================================================
# nokta_kontrol.py – Can Batlló 2025 doğrulama noktalarında (1) kör tekrar, (2) hakemlik
# Çalıştırma (Anaconda Prompt, conda activate thesis-ai):
#   1) python "C:\Users\eceus\Claude\Projects\Thesis Iaac\ai-sam3\nokta_kontrol.py" kor
#        -> C:\gis\auto\validation_2025_tekrar\kor_sayfa.png + kor_tekrar.csv
#        Aynı 52 nokta, YENİ sıra ve YENİ numaralar (T01...). Eski cevapların ve model YOK.
#        DİKKAT: doldururken eski validation_2025.csv dosyasını AÇMA.
#   2) kor_tekrar.csv'de ece_code sütununu doldur (1 ağaç · 2 çim · 3 toprak · 4 su · 5 geçirimsiz · 6 bina · 0 emin değilim)
#   3) python "...\nokta_kontrol.py" kor_puan        -> kendinle tutarlılık + modelle uyuşma
#   4) python "...\nokta_kontrol.py" hakem           -> sadece modelle anlaşamadığın noktalar: 120 m görüntü + model haritası
#        hakem.csv'de karar sütununu doldur (son kararın) + not
#   5) python "...\nokta_kontrol.py" hakem_puan      -> üç rakamlı rapor
# Dosya Google Sheets'te doldurulursa: Dosya > İndir > CSV, aynı adla aynı klasöre kaydet.
# =============================================================
import os, sys, csv, glob, json
import numpy as np

GIS_DIR = r"C:\gis"
RGB = os.path.join(GIS_DIR, "can_batllo_RGB_2025.tif")
KEY = os.path.join(GIS_DIR, "auto", "validation_2025", "_answers_do_not_open.csv")
ECE_OLD = [r"C:\Users\eceus\Claude\Projects\Thesis Iaac\ai-sam3\validation_2025.csv",
           os.path.join(GIS_DIR, "auto", "validation_2025", "validation_2025.csv")]
OUT = os.path.join(GIS_DIR, "auto", "validation_2025_tekrar")
KOR_CSV = os.path.join(OUT, "kor_tekrar.csv")
ESLESME = os.path.join(OUT, "_eslesme_acma.csv")          # T-numarası -> eski nokta numarası (açma)
HAKEM_CSV = os.path.join(OUT, "hakem.csv")
# Doldurulmuş kör tekrar: Claude'un Excel'den çevirdiği dosya (ai-sam3 klasöründe) varsa o okunur
KOR_DOLU = r"C:\Users\eceus\Claude\Projects\Thesis Iaac\ai-sam3\kor_tekrar_dolu.csv"
NAMES = {1: "agac", 2: "cim", 3: "toprak", 4: "su", 5: "gecirimsiz", 6: "bina"}
COLORS = {1: (34, 97, 38), 2: (120, 220, 90), 3: (205, 160, 100), 4: (0, 69, 255), 5: (148, 148, 148), 6: (222, 31, 7)}
SEED = 7                                                   # ilk kontrol 42'ydi; farklı sıra
MODE = sys.argv[1] if len(sys.argv) > 1 else "kor"


def read_codes(path, id_col, code_col):
    txt = open(path, encoding="utf-8-sig").read()
    delim = ";" if txt.count(";") >= txt.count(",") else ","
    return {r[id_col]: (r.get(code_col) or "").strip() for r in csv.DictReader(txt.splitlines(), delimiter=delim)}


def key_points():
    return list(csv.DictReader(open(KEY, encoding="utf-8")))


def model_raster():
    runs = sorted(glob.glob(os.path.join(GIS_DIR, "auto", "mat6_2025_*")))
    for r in reversed(runs):
        for n in ["mat6_fused_classes.tif", "mat6_classes.tif"]:
            if os.path.exists(os.path.join(r, n)):
                return os.path.join(r, n)
    raise SystemExit("Model sonucu bulunamadı (C:\\gis\\auto\\mat6_2025_*). Önce egitim_finetune.py test.")


def chip(img, r, c, half):
    """Kenara yakınsa beyazla doldurarak kare kesit."""
    H, W = img.shape[:2]
    out = np.full((2 * half, 2 * half) + img.shape[2:], 255, img.dtype)
    r0, c0 = r - half, c - half
    rs, cs = max(r0, 0), max(c0, 0)
    re, ce = min(r0 + 2 * half, H), min(c0 + 2 * half, W)
    out[rs - r0:re - r0, cs - c0:ce - c0] = img[rs:re, cs:ce]
    return out


def target(im, m):
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    d.ellipse([m - 10, m - 10, m + 10, m + 10], outline=(255, 0, 0), width=2)
    d.line([m - 18, m, m - 12, m], fill=(255, 0, 0), width=2); d.line([m + 12, m, m + 18, m], fill=(255, 0, 0), width=2)
    return im


def load_rgb():
    import rasterio
    with rasterio.open(RGB) as s:
        return np.transpose(s.read([1, 2, 3]), (1, 2, 0)).astype(np.uint8), s.transform


def kappa(pairs):
    labs = sorted({x for p in pairs for x in p})
    n = len(pairs); po = sum(a == b for a, b in pairs) / n
    pe = sum((sum(a == l for a, _ in pairs) / n) * (sum(b == l for _, b in pairs) / n) for l in labs)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


# ------------------------------------------------------------------
if MODE == "kor":
    from PIL import Image, ImageDraw
    os.makedirs(OUT, exist_ok=True)
    if os.path.exists(KOR_CSV):
        raise SystemExit(f"{KOR_CSV} zaten var (doldurduysan silme). Baştan istersen klasörü sil.")
    pts = key_points()
    rng = np.random.default_rng(SEED); order = rng.permutation(len(pts))
    rows = [{"tekrar_id": f"T{k + 1:02d}", "point_id": pts[i]["point_id"], "r": int(pts[i]["r"]), "c": int(pts[i]["c"])}
            for k, i in enumerate(order)]
    with open(KOR_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";"); w.writerow(["tekrar_id", "ece_code", "note"])
        for r in rows:
            w.writerow([r["tekrar_id"], "", ""])
    with open(ESLESME, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["tekrar_id", "point_id"])
        w.writeheader(); w.writerows({"tekrar_id": r["tekrar_id"], "point_id": r["point_id"]} for r in rows)
    rgb, T = load_rgb()
    half = int(40 / 2 / abs(T.a)); cols = 10; size = 2 * half
    sheet = Image.new("RGB", (cols * (size + 10) + 10, ((len(rows) + cols - 1) // cols) * (size + 34) + 10), "white")
    d = ImageDraw.Draw(sheet)
    for k, r in enumerate(rows):
        im = target(Image.fromarray(chip(rgb, r["r"], r["c"], half)), half)
        x0, y0 = 10 + (k % cols) * (size + 10), 10 + (k // cols) * (size + 34)
        sheet.paste(im, (x0, y0)); d.text((x0, y0 + size + 6), r["tekrar_id"], fill="black")
    sheet.save(os.path.join(OUT, "kor_sayfa.png"))
    print(f"{len(rows)} nokta hazır (40 x 40 m, ilk kontrolle aynı görünüm, yeni sıra).")
    print("Aç   :", os.path.join(OUT, "kor_sayfa.png"))
    print("Doldur:", KOR_CSV, " (ece_code: 1 ağaç · 2 çim · 3 toprak · 4 su · 5 geçirimsiz · 6 bina · 0 emin değilim)")
    print("Eski validation_2025.csv dosyasını doldururken AÇMA.")

# ------------------------------------------------------------------
elif MODE in ("kor_puan", "hakem", "hakem_puan"):
    import rasterio
    pts = {p["point_id"]: p for p in key_points()}
    es = {r["tekrar_id"]: r["point_id"] for r in csv.DictReader(open(ESLESME, encoding="utf-8"))}
    new = read_codes(KOR_DOLU if os.path.exists(KOR_DOLU) else KOR_CSV, "tekrar_id", "ece_code")
    old_path = next(p for p in ECE_OLD if os.path.exists(p))
    old = read_codes(old_path, "point_id", "ece_code")
    mpath = model_raster()
    with rasterio.open(mpath) as s:
        mod = s.read(1); MT = s.transform
    data = []
    for tid, pid in es.items():
        p = pts[pid]
        r, c = rasterio.transform.rowcol(MT, float(p["x"]), float(p["y"]))
        o, n = old.get(pid, ""), new.get(tid, "")
        data.append({"tekrar_id": tid, "point_id": pid, "r": int(p["r"]), "c": int(p["c"]),
                     "eski": int(o) if o.isdigit() else None, "yeni": int(n) if n.isdigit() else None,
                     "model": int(mod[r, c])})
    if all(d["yeni"] is None for d in data):
        raise SystemExit("kor_tekrar.csv boş görünüyor. ece_code sütununu doldurup kaydet.")
    valid = lambda v: v is not None and 1 <= v <= 6

    def acc(a, b):
        pr = [(d[a], d[b]) for d in data if valid(d[a]) and valid(d[b])]
        return (sum(x == y for x, y in pr), len(pr), kappa(pr) if pr else float("nan"))

    if MODE == "kor_puan":
        print("Model:", mpath)
        for name, a, b in [("Kendinle tutarlılık (ilk kontrol vs kör tekrar)", "eski", "yeni"),
                           ("Model vs ilk kontrolün", "model", "eski"),
                           ("Model vs kör tekrarın", "model", "yeni")]:
            ok, n, k = acc(a, b)
            print(f"  {name:48s} %{ok / n * 100:5.1f}  ({ok}/{n})  kappa {k:.2f}")
        print("  'emin değilim' (0): ilk", sum(d["eski"] == 0 for d in data), "| tekrar", sum(d["yeni"] == 0 for d in data))
        ch = [d for d in data if valid(d["eski"]) and valid(d["yeni"]) and d["eski"] != d["yeni"]]
        print(f"\n  Fikrini değiştirdiğin noktalar ({len(ch)}):")
        for d in ch:
            print(f"    {d['tekrar_id']} (eski {d['point_id']}): {NAMES[d['eski']]} -> {NAMES[d['yeni']]}")
        json.dump({"self_agreement": acc("eski", "yeni"), "model_vs_first": acc("model", "eski"),
                   "model_vs_repeat": acc("model", "yeni"), "model_raster": mpath, "points": data},
                  open(os.path.join(OUT, "kor_puan.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("\nKaydedildi:", os.path.join(OUT, "kor_puan.json"), "\nSonraki adım: nokta_kontrol.py hakem")

    elif MODE == "hakem":
        from PIL import Image, ImageDraw
        if os.path.exists(HAKEM_CSV):
            raise SystemExit(f"{HAKEM_CSV} zaten var (doldurduysan silme).")
        dis = [d for d in data if valid(d["yeni"]) and d["model"] != d["yeni"]]
        rgb, T = load_rgb()
        pal = np.zeros((256, 3), np.uint8)
        for k, v in COLORS.items():
            pal[k] = v
        with rasterio.open(mpath) as s:
            full = s.read(1)
        half = int(120 / 2 / abs(T.a)); size = 2 * half; sc = 0.5; ss = int(size * sc)
        sheet = Image.new("RGB", (2 * ss + 30, len(dis) * (ss + 40) + 10), "white"); dr = ImageDraw.Draw(sheet)
        for k, d in enumerate(dis):
            a = target(Image.fromarray(chip(rgb, d["r"], d["c"], half)), half).resize((ss, ss))
            b = target(Image.fromarray(pal[chip(full, d["r"], d["c"], half)]), half).resize((ss, ss))
            y = 10 + k * (ss + 40)
            sheet.paste(a, (10, y + 26)); sheet.paste(b, (ss + 20, y + 26))
            dr.text((10, y + 6), f"{d['tekrar_id']}   senin (kör tekrar): {d['yeni']} {NAMES[d['yeni']]}   |   model: "
                                 f"{d['model']} {NAMES.get(d['model'], '?')}   (120 x 120 m, solda ortofoto, sağda model)", fill="black")
        sheet.save(os.path.join(OUT, "hakem_sayfa.png"))
        with open(HAKEM_CSV, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";"); w.writerow(["tekrar_id", "senin", "model", "karar", "not"])
            for d in dis:
                w.writerow([d["tekrar_id"], d["yeni"], d["model"], "", ""])
        print(f"{len(dis)} anlaşmazlık noktası.\nAç   :", os.path.join(OUT, "hakem_sayfa.png"),
              "\nDoldur:", HAKEM_CSV, "  karar = son kararın (1-6, 0 emin değilim); not = kısa neden")

    elif MODE == "hakem_puan":
        kar = read_codes(HAKEM_CSV, "tekrar_id", "karar")
        for d in data:
            k = kar.get(d["tekrar_id"], "")
            d["son"] = int(k) if k.isdigit() else d["yeni"]
        ok_b, n_b, _ = acc("model", "eski")
        ok_s, n_s, _ = acc("eski", "yeni")
        ok_h, n_h, kh = acc("model", "son")
        changed = sum(1 for d in data if kar.get(d["tekrar_id"], "").isdigit() and int(kar[d["tekrar_id"]]) != d["yeni"])
        print(f"  1. Kör doğruluk (asıl sonuç, model vs ilk kontrol): %{ok_b / n_b * 100:.1f} ({ok_b}/{n_b})")
        print(f"  2. Kendinle tutarlılık (tavan):                     %{ok_s / n_s * 100:.1f} ({ok_s}/{n_s})")
        print(f"  3. Hakemlik sonrası (model çıktısı görülerek):      %{ok_h / n_h * 100:.1f} ({ok_h}/{n_h})  kappa {kh:.2f}")
        print(f"     hakemlikte kararını değiştirdiğin nokta: {changed}")
        json.dump({"blind_accuracy": [ok_b, n_b], "self_agreement": [ok_s, n_s], "adjudicated_accuracy": [ok_h, n_h],
                   "adjudication_changes": changed, "model_raster": mpath,
                   "note": "adjudicated = Ece's final decision after seeing model output (not blind)", "points": data},
                  open(os.path.join(OUT, "hakem_puan.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
else:
    raise SystemExit("Kullanım: nokta_kontrol.py kor | kor_puan | hakem | hakem_puan")
