# =============================================================
# geometri_onar.py – etiket_<site>.gpkg dosyalarındaki geçersiz poligonları onarır
# (Nesneleri Böl aracı "The geometry is invalid" hatası verdiğinde)
# ÖNCE QGIS'te düzenlemeleri kaydet ve QGIS'i KAPAT (dosya açıkken yazılamaz).
# Çalıştırma (Anaconda Prompt):
#   conda activate thesis-ai
#   python "C:\Users\eceus\Claude\Projects\Thesis Iaac\ai-sam3\geometri_onar.py"
# Ne yapar: her poligonu onarır; köşeden değen parçaları ayrı poligonlara böler
# (hepsi aynı sinif / on_etiket / kontrol / karo değerini korur). Senin düzeltmelerin aynen kalır.
# Önce her dosyanın yedeğini alır: etiket_<site>_yedek_<tarih>.gpkg
# =============================================================
import os, glob, shutil
from datetime import datetime
import geopandas as gpd
try:
    from shapely import make_valid
except ImportError:
    from shapely.validation import make_valid
from shapely.geometry import Polygon, MultiPolygon, GeometryCollection

ROOT = r"C:\gis\egitim"
stamp = datetime.now().strftime("%Y%m%d_%H%M")


def polys(g):
    """Onarılmış geometriden sadece poligon parçalarını çıkarır."""
    if g is None or g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, (MultiPolygon, GeometryCollection)):
        out = []
        for p in g.geoms:
            out += polys(p)
        return out
    return []                                  # çizgi / nokta artıkları atılır


for path in sorted(glob.glob(os.path.join(ROOT, "*", "etiket_*.gpkg"))):
    if "_yedek_" in path:
        continue
    gdf = gpd.read_file(path, layer="etiket")
    bad = int((~gdf.geometry.is_valid).sum())
    if bad == 0:
        print(f"{os.path.basename(path)}: geçersiz poligon yok, dokunulmadı")
        continue
    shutil.copy2(path, path.replace(".gpkg", f"_yedek_{stamp}.gpkg"))
    rows = []
    for _, r in gdf.iterrows():
        g = r.geometry if r.geometry.is_valid else make_valid(r.geometry)
        for p in polys(g):
            if p.area > 0.01:                  # 0.01 m²'den küçük kırıntılar atılır
                d = r.drop(labels="geometry").to_dict(); d["geometry"] = p
                rows.append(d)
    out = gpd.GeoDataFrame(rows, geometry="geometry", crs=gdf.crs)
    tmp = path.replace(".gpkg", "_tmp.gpkg")
    out.to_file(tmp, layer="etiket", driver="GPKG")
    os.replace(tmp, path)
    print(f"{os.path.basename(path)}: {bad} geçersiz poligon onarıldı | {len(gdf)} -> {len(out)} poligon "
          f"| geçersiz kalan: {int((~out.geometry.is_valid).sum())}")
print("\nBitti. QGIS'i açabilirsin.")
