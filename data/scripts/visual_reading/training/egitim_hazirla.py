# =============================================================
# egitim_hazirla.py – fine-tuning için eğitim sitelerini hazırlar (Barcelona, ICGC 2025, 25 cm)
# Nasıl çalıştırılır (Anaconda Prompt'ta):
#   conda activate thesis-ai
#   python "C:\Users\eceus\Claude\Projects\Thesis Iaac\ai-sam3\egitim_hazirla.py"
# Script 3 adımı sırayla yapar; daha önce yapılmış işi tekrar yapmaz (tekrar çalıştırmak güvenli):
#   1. indir     : her site için 512 x 512 m kutu -> RGB + kızılötesi (IRC) ortofoto 2025
#                  + C:\gis\egitim\genel_bakis.png  (sitelerin yeri doğru mu, buradan kontrol et)
#   2. onetiket  : mevcut model (SegFormer OEM) + NDVI -> 6 malzeme sınıfında ön etiket,
#                  her siteyi 16 karoya (128 x 128 m) böler, her siteden 6 karoyu otomatik seçer
#                  -> C:\gis\egitim\karolar.gpkg  (secili = 1 olanlar etiketlenecek; QGIS'te değiştirebilirsin)
#   3. poligon   : seçili karoların ön etiketini poligona çevirir -> C:\gis\egitim\<site>\etiket_<site>.gpkg
#                  QGIS'te sen sadece yanlış olan poligonların 'sinif' değerini düzeltirsin.
#                  DİKKAT: düzelttiğin dosyanın üzerine asla yazmaz; sadece yeni seçilen karoları ekler.
# Tek adım çalıştırmak için:  python egitim_hazirla.py indir | onetiket | poligon
# Ön etiketi baştan üretmek için: python egitim_hazirla.py sifirla  (düzeltilmiş etiketlere dokunmaz)
#
# Sınıflar (labelling guide, malzeme bazlı): 1 ağaç, 2 çim/otsu bitki, 3 açık toprak/kum/sauló,
#   4 su, 5 geçirimsiz yüzey, 6 bina, 0 emin değilim
# Can Batlló TEST sitesidir, eğitime girmez (script yakın bir kutu görürse uyarır).
# Kaynak: ICGC WMS Territorial Orthophoto, CC BY 4.0.  Ön etiket provenance = "ai_detected".
# =============================================================
import os, io, re, sys, json, time
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont


def font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()

GIS_DIR = r"C:\gis"
OUT_ROOT = os.path.join(GIS_DIR, "egitim")
MODEL_DIR = os.path.join(GIS_DIR, "models", "oem_segformer_b2")   # segformer_oem_test.py ile oluşmuştu
CANBATLLO = os.path.join(GIS_DIR, "can_batllo_boundary_25831.gpkg")
YEAR = "2025"

# --- SİTELER: (enlem, boylam) = kutunun merkezi -------------------------------------------
# Google Maps'te bir noktaya sağ tıkla -> en üstteki iki sayı (ör. 41.38810, 2.18730). Yanlışsa
# buradaki sayıyı değiştir, C:\gis\egitim\<site> klasörünü sil ve scripti yeniden çalıştır.
SITES = {
    "ciutadella":       (41.3881, 2.1873),   # Parc de la Ciutadella
    "joan_miro":        (41.3778, 2.1489),   # Parc de Joan Miró
    "diagonal_mar":     (41.4083, 2.2140),   # Parc del Diagonal Mar
    "montjuic_mirador": (41.3685, 2.1700),   # Montjuïc, Mirador çevresi  (YAKLAŞIK – kontrol et)
    "torrassa":         (41.36856, 2.12028), # Parc de la Torrassa, L'Hospitalet (Ece, 18 Nov)
    "tres_xemeneies":   (41.42834, 2.23534), # Tres Xemeneies, Sant Adrià de Besòs (Ece, 18 Nov)
    "can_ricart":       (41.40852, 2.19714), # Can Ricart, Poblenou (Ece, 18 Nov)
    # 2. tur (19 Nov): gri, sıkıştırılmış zemin / şantiye / boş sanayi arsası
    "la_sagrera":       (41.42145, 2.19416), # La Sagrera tren istasyonu inşaatı (Ece, 19 Nov)
    "zona_franca":      (41.31803, 2.14334), # Zona Franca çevresi (Ece, 19 Nov)
    "el_prat":          (41.29884, 2.07969), # El Prat (Ece, 19 Nov)
}
BOX_M = 512            # kutu kenarı (m)
RES = 0.25             # m / piksel
KARO = 512             # karo = 512 piksel = 128 m (modelin eğitileceği parça boyutu)
N_SECILI = 6           # her siteden otomatik seçilen karo sayısı
# Elle seçilen karolar (otomatik seçimin yerine geçer). Numara = önizlemedeki karo numarası.
MANUEL_SECIM = {
    "can_ricart":       [4, 8, 9, 10, 14, 16],   # eski sanayi çatıları + kum oyun alanı / bahçe
    "diagonal_mar":     [5, 6, 7, 9, 11, 12],    # boş arsa (05), kum meydan (09), göl
    "joan_miro":        [2, 6, 7, 9, 10, 11],    # sauló park, kuru çim
    "montjuic_mirador": [4, 8, 9, 11, 12, 14],   # açık toprak yamaçlar, taş ocağı (14)
    "tres_xemeneies":   [7, 10, 11, 12, 15, 16], # büyük boş arsa, santral çatıları, kumsal + deniz
    "la_sagrera":       [2, 3, 6, 10, 13, 15],   # kazı toprağı, sıkıştırılmış şantiye zemini, beton döşeme
    "zona_franca":      [2, 6, 7, 8, 11, 14],    # kum/toprak yamaçlar, gri sıkıştırılmış arsa (14)
    "el_prat":          [6, 9, 10, 15],          # havalimanı: pist arası kuru çim + açık toprak, beton
    # ciutadella ve torrassa: otomatik seçim iyi, elle seçim yok
}
SIEVE_PX = 32          # 2 m²'den küçük lekeler komşusuna katılır (poligon sayısı azalsın)

CLASSES = {0: "emin_degil", 1: "agac", 2: "cim_bitki", 3: "toprak_kum", 4: "su", 5: "gecirimsiz", 6: "bina"}
COLORS = {0: (255, 0, 255), 1: (34, 97, 38), 2: (120, 220, 90), 3: (205, 160, 100), 4: (0, 69, 255),
          5: (148, 148, 148), 6: (222, 31, 7)}
OEM_TO_MAT = {"unknown": 0, "tree": 1, "rangeland": 2, "agriculture": 2, "bareland": 3, "water": 4,
              "developed_space": 5, "road": 5, "building": 6}
WMS = "https://geoserveis.icgc.cat/servei/catalunya/orto-territorial/wms"
NPX = int(BOX_M / RES)                      # 2048
NK = NPX // KARO                            # 4 x 4 karo


def site_box(lat, lon):
    from pyproj import Transformer
    x, y = Transformer.from_crs("EPSG:4326", "EPSG:25831", always_xy=True).transform(lon, lat)
    minx, maxy = np.floor(x - BOX_M / 2), np.floor(y + BOX_M / 2)
    return minx, maxy - BOX_M, minx + BOX_M, maxy


def save_tif(path, arr, minx, maxy, colormap=None):
    import rasterio
    from rasterio.transform import from_origin
    arr = arr if arr.ndim == 3 else arr[None]
    with rasterio.open(path, "w", driver="GTiff", height=arr.shape[1], width=arr.shape[2], count=arr.shape[0],
                       dtype=arr.dtype, crs="EPSG:25831", transform=from_origin(minx, maxy, RES, RES),
                       compress="deflate") as dst:
        dst.write(arr)
        if colormap:
            dst.write_colormap(1, colormap)


# =============================================================
# 1. İNDİR
# =============================================================
def wms_layers():
    cap = requests.get(WMS, params={"SERVICE": "WMS", "REQUEST": "GetCapabilities", "VERSION": "1.3.0"},
                       timeout=60).text
    names = re.findall(r"<Name>([^<]+)</Name>", cap)
    rgb = "ortofoto_color_serie_anual"
    irc = [n for n in names if "infraroig" in n.lower()]
    irc_layer = next((n for n in irc if "serie_anual" in n), None) or next((n for n in irc if YEAR in n), None)
    if rgb not in names or irc_layer is None:
        raise SystemExit("ICGC katmanları bulunamadı. Bu listeyi Claude'a gönder:\n" + str(names[:80]))
    return rgb, irc_layer


def wms_get(layer, minx, miny, maxx, maxy, use_time):
    img = np.zeros((NPX, NPX, 3), np.uint8)
    T = 1000
    for row in range(0, NPX, T):
        for col in range(0, NPX, T):
            h, w = min(T, NPX - row), min(T, NPX - col)
            x0, y1 = minx + col * RES, maxy - row * RES
            r = requests.get(WMS, params={
                "SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.3.0", "LAYERS": layer, "STYLES": "",
                "CRS": "EPSG:25831", "BBOX": f"{x0},{y1 - h * RES},{x0 + w * RES},{y1}", "WIDTH": w, "HEIGHT": h,
                "FORMAT": "image/jpeg", **({"TIME": YEAR} if use_time else {})}, timeout=120)
            if "image" not in r.headers.get("Content-Type", ""):
                raise SystemExit(f"ICGC hata döndürdü ({layer}):\n" + r.text[:500])
            img[row:row + h, col:col + w] = np.array(Image.open(io.BytesIO(r.content)).convert("RGB"))
    return img


def step_indir():
    print("\n=== 1. İNDİR ===")
    rgb_layer = irc_layer = None
    # Can Batlló'ya yakınlık kontrolü (test sitesi eğitime karışmasın)
    cb = None
    if os.path.exists(CANBATLLO):
        import geopandas as gpd
        cb = gpd.read_file(CANBATLLO).to_crs("EPSG:25831").geometry.unary_union.buffer(300)
    thumbs = []
    for name, (lat, lon) in SITES.items():
        d = os.path.join(OUT_ROOT, name); os.makedirs(d, exist_ok=True)
        minx, miny, maxx, maxy = site_box(lat, lon)
        if cb is not None:
            from shapely.geometry import box
            if box(minx, miny, maxx, maxy).intersects(cb):
                print(f"  UYARI: {name} kutusu Can Batlló'ya 300 m'den yakın! Test sitesi eğitime karışabilir.")
        rgb_p, irc_p = os.path.join(d, f"rgb_{YEAR}.tif"), os.path.join(d, f"irc_{YEAR}.tif")
        if os.path.exists(rgb_p) and os.path.exists(irc_p):
            print(f"  {name}: zaten indirilmiş, atlanıyor")
            import rasterio
            with rasterio.open(rgb_p) as s:
                rgb = s.read().transpose(1, 2, 0)
        else:
            if rgb_layer is None:
                rgb_layer, irc_layer = wms_layers()
                print("  Katmanlar:", rgb_layer, "|", irc_layer)
            print(f"  {name}: indiriliyor ...")
            rgb = wms_get(rgb_layer, minx, miny, maxx, maxy, True)
            irc = wms_get(irc_layer, minx, miny, maxx, maxy, "serie_anual" in irc_layer)
            save_tif(rgb_p, rgb.transpose(2, 0, 1), minx, maxy)
            save_tif(irc_p, irc.transpose(2, 0, 1), minx, maxy)
            with open(os.path.join(d, "kaynak.json"), "w", encoding="utf-8") as f:
                json.dump({"site": name, "center_wgs84": [lat, lon], "bbox_25831": [minx, miny, maxx, maxy],
                           "source": "ICGC WMS orto-territorial", "url": WMS, "layers": [rgb_layer, irc_layer],
                           "year": YEAR, "resolution_m": RES, "license": "CC BY 4.0",
                           "irc_bands": "1 = NIR, 2 = red, 3 = green"}, f, indent=2)
            print(f"  {name}: tamam")
        th = Image.fromarray(rgb).resize((512, 512))
        dr = ImageDraw.Draw(th)
        for i in range(1, NK):
            dr.line([(i * 128, 0), (i * 128, 512)], fill="yellow"); dr.line([(0, i * 128), (512, i * 128)], fill="yellow")
        dr.rectangle([0, 0, 512, 22], fill="black"); dr.text((6, 3), name, fill="white", font=font(16))
        thumbs.append(th)
    cols = 4
    sheet = Image.new("RGB", (cols * 522, ((len(thumbs) + cols - 1) // cols) * 522), "white")
    for i, th in enumerate(thumbs):
        sheet.paste(th, ((i % cols) * 522, (i // cols) * 522))
    sheet.save(os.path.join(OUT_ROOT, "genel_bakis.png"))
    print("  Kontrol görseli:", os.path.join(OUT_ROOT, "genel_bakis.png"))


# =============================================================
# 2. ÖN ETİKET
# =============================================================
def step_onetiket():
    print("\n=== 2. ÖN ETİKET ===")
    import torch, torch.nn.functional as F, rasterio
    import geopandas as gpd
    from shapely.geometry import box
    from transformers import SegformerForSemanticSegmentation
    # Varsa Ece'nin eğittiği en son 6 sınıflı model (egitim_finetune.py) kullanılır, yoksa OEM modeli
    son = os.path.join(GIS_DIR, "models", "mat6_son.txt")
    mdir = MODEL_DIR
    if os.path.exists(son) and os.path.exists(os.path.join(open(son).read().strip(), "config.json")):
        mdir = open(son).read().strip()
    if not os.path.exists(os.path.join(mdir, "config.json")):
        raise SystemExit("Model klasörü yok: " + mdir + "\nÖnce bir kez segformer_oem_test.py 2025 çalıştır.")
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = SegformerForSemanticSegmentation.from_pretrained(mdir).eval().to(dev)
    names = [model.config.id2label[i] for i in range(model.config.num_labels)]
    if model.config.num_labels == 6:                       # 6 malzeme sınıfı: indeks 0..5 -> kod 1..6
        lut = np.arange(1, 7, dtype=np.uint8)
    else:
        lut = np.array([OEM_TO_MAT.get(n, 0) for n in names], np.uint8)
    print("  Ön etiket modeli:", mdir, "| sınıflar:", names, "| cihaz:", dev)

    TILE, STRIDE = 1000, 600
    def starts(n):
        s = list(range(0, max(n - TILE, 0) + 1, STRIDE))
        if s[-1] + TILE < n: s.append(n - TILE)
        return s
    wy = np.hanning(TILE + 2)[1:-1].astype("float32"); wwin = np.outer(wy, wy) + 1e-3
    mean = np.array([0.485, 0.456, 0.406], "float32")[:, None, None]
    std = np.array([0.229, 0.224, 0.225], "float32")[:, None, None]

    karo_path = os.path.join(OUT_ROOT, "karolar.gpkg")
    eski = {}
    if os.path.exists(karo_path):                       # senin QGIS'te yaptığın seçimler korunur
        old = gpd.read_file(karo_path)
        eski = dict(zip(old["karo"], old["secili"]))
    rows = []
    for name, (lat, lon) in SITES.items():
        d = os.path.join(OUT_ROOT, name)
        rgb_p, irc_p, pre_p = (os.path.join(d, f) for f in (f"rgb_{YEAR}.tif", f"irc_{YEAR}.tif", "on_etiket.tif"))
        if not os.path.exists(rgb_p):
            print(f"  {name}: ortofoto yok, önce 'indir' adımı"); continue
        with rasterio.open(rgb_p) as s:
            rgb = s.read().astype("float32") / 255.0
            minx, maxy = s.transform.c, s.transform.f
        if os.path.exists(pre_p):
            print(f"  {name}: ön etiket zaten var, atlanıyor")
            with rasterio.open(pre_p) as s:
                mat = s.read(1)
        else:
            t0 = time.time()
            x_all = (rgb - mean) / std
            H, W = x_all.shape[1:]
            acc = np.zeros((len(names), H, W), np.float32); wsum = np.zeros((H, W), np.float32)
            with torch.inference_mode():
                for r0 in starts(H):
                    for c0 in starts(W):
                        t = torch.from_numpy(x_all[:, r0:r0 + TILE, c0:c0 + TILE].copy())[None].to(dev)
                        h, w = t.shape[2:]
                        p = F.interpolate(model(pixel_values=t).logits, size=(h, w), mode="bilinear",
                                          align_corners=False).softmax(1)[0].cpu().numpy()
                        acc[:, r0:r0 + h, c0:c0 + w] += p * wwin[:h, :w]; wsum[r0:r0 + h, c0:c0 + w] += wwin[:h, :w]
            mat = lut[(acc / wsum).argmax(0)]
            # NDVI ile iki basit düzeltme (yükseklik verisi yok, bu yüzden bina/ağaç kontrol edilemiyor):
            with rasterio.open(irc_p) as s:
                nir, red = s.read(1).astype("float32"), s.read(2).astype("float32")
            ndvi = (nir - red) / (nir + red + 1e-6)
            fix_veg = np.isin(mat, [3, 5]) & (ndvi > 0.2)    # model toprak/geçirimsiz dedi ama bitki var -> 2
            fix_unsure = np.isin(mat, [1, 2]) & (ndvi < 0.0) # model bitki dedi ama NDVI bitki değil (suni çim?) -> 0
            # RGB ile IRC birkaç piksel kayık: ağaç kenarlarındaki ince şeritler atılır, sadece gerçek alanlar kalır
            from scipy import ndimage
            fix_unsure = ndimage.binary_opening(fix_unsure, iterations=3)
            mat[fix_veg] = 2; mat[fix_unsure] = 0
            save_tif(pre_p, mat.astype(np.uint8), minx, maxy, {k: v + (255,) for k, v in COLORS.items()})
            with open(os.path.join(d, "on_etiket.json"), "w", encoding="utf-8") as f:
                json.dump({"model": mdir, "rules": {"ndvi>0.2 & model in (3,5) -> 2": int(fix_veg.sum()),
                           "ndvi<0 & model in (1,2) -> 0": int(fix_unsure.sum())},
                           "classes": CLASSES, "provenance": "ai_detected"}, f, ensure_ascii=False, indent=2)
            print(f"  {name}: ön etiket tamam ({time.time() - t0:.0f} s) | bitki düzeltmesi %{fix_veg.mean() * 100:.1f}"
                  f" | emin değil %{fix_unsure.mean() * 100:.1f}")

        # karolar ve otomatik seçim: çeşitlilik + toprak/kum + su + çim olan karolar öne çıkar
        site_rows = []
        for r in range(NK):
            for c in range(NK):
                k = mat[r * KARO:(r + 1) * KARO, c * KARO:(c + 1) * KARO]
                pct = {i: float((k == i).mean()) for i in range(7)}
                score = sum(v >= 0.03 for i, v in pct.items() if i > 0) + 3 * pct[3] + 2 * pct[4] + pct[2] - pct[6]
                x0, y1 = minx + c * KARO * RES, maxy - r * KARO * RES
                site_rows.append({"site": name, "karo": f"{name}_{r * NK + c + 1:02d}", "satir": r, "sutun": c,
                                  "skor": round(score, 3), **{f"pct_{i}": round(v * 100, 1) for i, v in pct.items()},
                                  "geometry": box(x0, y1 - KARO * RES, x0 + KARO * RES, y1)})
        top = {s["karo"] for s in sorted(site_rows, key=lambda s: -s["skor"])[:N_SECILI]}
        if name in MANUEL_SECIM:
            elle = {f"{name}_{n:02d}" for n in MANUEL_SECIM[name]}
            for s in site_rows:
                s["secili"] = int(s["karo"] in elle)
        else:
            for s in site_rows:
                s["secili"] = int(eski.get(s["karo"], 1 if s["karo"] in top else 0))
        rows += site_rows

        # önizleme: solda ortofoto + karo numaraları (sarı = seçili), sağda ön etiket
        rgb8 = Image.fromarray((rgb.transpose(1, 2, 0) * 255).astype(np.uint8))
        colimg = np.zeros(mat.shape + (3,), np.uint8)
        for i, cc in COLORS.items():
            colimg[mat == i] = cc
        prev = Image.new("RGB", (NPX * 2 + 40, NPX + 60), "white")
        prev.paste(rgb8, (0, 0)); prev.paste(Image.fromarray(colimg), (NPX + 40, 0))
        dr = ImageDraw.Draw(prev)
        for s in site_rows:
            x, y = s["sutun"] * KARO, s["satir"] * KARO
            for off in (0, NPX + 40):
                dr.rectangle([x + off, y, x + off + KARO - 1, y + KARO - 1],
                             outline="yellow" if s["secili"] else "white", width=8 if s["secili"] else 2)
            dr.rectangle([x + 10, y + 10, x + 110, y + 80], fill="black")
            dr.text((x + 22, y + 14), s["karo"][-2:], fill="yellow" if s["secili"] else "white", font=font(56))
        for j, (i, cc) in enumerate(COLORS.items()):
            dr.rectangle([20 + j * 280, NPX + 20, 50 + j * 280, NPX + 50], fill=cc, outline="black")
            dr.text((60 + j * 280, NPX + 22), f"{i} {CLASSES[i]}", fill="black", font=font(28))
        prev.thumbnail((2000, 2000)); prev.save(os.path.join(d, "onizleme.png"))

    if rows:
        gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:25831").to_file(karo_path, layer="karolar", driver="GPKG")
        print("  Karolar:", karo_path, "| seçili:", sum(r["secili"] for r in rows), "karo")
        print("  Her sitenin önizlemesi: C:\\gis\\egitim\\<site>\\onizleme.png  (sarı = seçili karo)")


# =============================================================
# 3. POLİGON (QGIS'te düzeltilecek etiket katmanı)
# =============================================================
QML_HEAD = '<!DOCTYPE qgis PUBLIC \'http://mrcc.com/qgis.dtd\' \'SYSTEM\'>\n<qgis version="3.34" styleCategories="Symbology|Labeling">\n' \
           ' <renderer-v2 type="categorizedSymbol" attr="sinif" symbollevels="0" enableorderby="0" forceraster="0">\n  <categories>\n'


def write_qml(path):
    cats = "".join(f'   <category value="{i}" symbol="{j}" label="{i} {CLASSES[i]}" render="true"/>\n'
                   for j, i in enumerate(CLASSES))
    syms = ""
    for j, i in enumerate(CLASSES):
        c = ",".join(map(str, COLORS[i]))
        syms += (f'   <symbol type="fill" name="{j}" alpha="0.55" clip_to_extent="1" force_rhr="0">\n'
                 f'    <layer class="SimpleFill" enabled="1" pass="0" locked="0">\n'
                 f'     <Option type="Map">\n'
                 f'      <Option type="QString" name="color" value="{c},255"/>\n'
                 f'      <Option type="QString" name="outline_color" value="30,30,30,255"/>\n'
                 f'      <Option type="QString" name="outline_width" value="0.15"/>\n'
                 f'      <Option type="QString" name="style" value="solid"/>\n'
                 f'     </Option>\n'
                 f'     <prop k="color" v="{c},255"/><prop k="outline_color" v="30,30,30,255"/>'
                 f'<prop k="outline_width" v="0.15"/><prop k="style" v="solid"/>\n'
                 f'    </layer>\n   </symbol>\n')
    with open(path, "w", encoding="utf-8") as f:
        f.write(QML_HEAD + cats + "  </categories>\n  <symbols>\n" + syms + "  </symbols>\n </renderer-v2>\n</qgis>\n")


def step_poligon():
    print("\n=== 3. POLİGON ===")
    import rasterio
    from rasterio import features
    from rasterio.windows import Window
    import geopandas as gpd
    from shapely.geometry import shape
    karo_path = os.path.join(OUT_ROOT, "karolar.gpkg")
    if not os.path.exists(karo_path):
        raise SystemExit("karolar.gpkg yok, önce 'onetiket' adımı.")
    kar = gpd.read_file(karo_path)
    kar = kar[kar["secili"] == 1]
    for name in SITES:
        sk = kar[kar["site"] == name]
        pre_p = os.path.join(OUT_ROOT, name, "on_etiket.tif")
        if sk.empty or not os.path.exists(pre_p):
            continue
        out = os.path.join(OUT_ROOT, name, f"etiket_{name}.gpkg")
        var_olan = set(gpd.read_file(out)["karo"]) if os.path.exists(out) else set()
        yeni = sk[~sk["karo"].isin(var_olan)]
        if yeni.empty:
            print(f"  {name}: seçili karoların hepsi zaten dosyada, dokunulmadı"); continue
        feats = []
        with rasterio.open(pre_p) as src:
            for _, k in yeni.iterrows():
                win = Window(int(k["sutun"]) * KARO, int(k["satir"]) * KARO, KARO, KARO)
                a = features.sieve(src.read(1, window=win), size=SIEVE_PX, connectivity=8)
                for geom, v in features.shapes(a, transform=src.window_transform(win), connectivity=4):  # 4: köşeden değen geçersiz poligon oluşmaz
                    feats.append({"karo": k["karo"], "sinif": int(v), "on_etiket": int(v),
                                  "kontrol": 0, "geometry": shape(geom)})
        gdf = gpd.GeoDataFrame(feats, geometry="geometry", crs="EPSG:25831")
        gdf.to_file(out, layer="etiket", driver="GPKG", mode="a" if var_olan else "w")
        write_qml(out.replace(".gpkg", ".qml"))
        print(f"  {name}: {len(yeni)} karo, {len(gdf)} poligon -> {out}")
    print("\nQGIS'te: rgb_2025.tif + etiket_<site>.gpkg aç. Renkler otomatik gelmezse:"
          "\n  katmana sağ tık > Properties > Symbology > Style (alt) > Load Style > etiket_<site>.qml")


def step_sifirla():
    """Ön etiketi, karoları ve (henüz DÜZELTİLMEMİŞ) etiket dosyalarını siler; indirilen ortofotolar kalır."""
    print("\n=== SIFIRLA ===")
    import geopandas as gpd
    for name in SITES:
        d = os.path.join(OUT_ROOT, name)
        et = os.path.join(d, f"etiket_{name}.gpkg")
        if os.path.exists(et):
            g = gpd.read_file(et)
            if (g["sinif"] != g["on_etiket"]).any() or (g["kontrol"] != 0).any():
                print(f"  {name}: etiket dosyasında düzeltme var, DOKUNULMADI"); continue
        for f in ["on_etiket.tif", "on_etiket.json", "onizleme.png", f"etiket_{name}.gpkg", f"etiket_{name}.qml"]:
            if os.path.exists(os.path.join(d, f)):
                os.remove(os.path.join(d, f))
        print(f"  {name}: ön etiket silindi (ortofotolar duruyor)")
    kp = os.path.join(OUT_ROOT, "karolar.gpkg")
    if os.path.exists(kp):
        os.remove(kp)


if __name__ == "__main__":
    steps = sys.argv[1:] or ["indir", "onetiket", "poligon"]
    os.makedirs(OUT_ROOT, exist_ok=True)
    for s in steps:
        {"indir": step_indir, "onetiket": step_onetiket, "poligon": step_poligon, "sifirla": step_sifirla}[s]()
    print("\nBitti.")
