# SAS Manhole GUI

Ortofotolarda menhol / rögar / dikdörtgen kapak tespiti için YOLO (SAS-geliştirilmiş) modelleriyle çalışan,
QGIS/ArcGIS benzeri masaüstü inceleme ve düzenleme arayüzü.

## Özellikler

- `.tif` / `.tiff` ortofotoları tekli, çoklu veya klasör olarak açma; sol panelde küçük önizlemeler.
- Herhangi bir Ultralytics YOLO `.pt` modelini yükleme; sınıflar model içinden veya `data.yaml`'dan otomatik,
  istenirse elle düzenlenebilir.
- Büyük görüntüleri arka planda 640×640 (ayarlanabilir, örtüşmeli) kesitlere bölüp tespit çalıştırma,
  ilerleme çubuğu ile takip.
- Tespit kutularını görüntü üzerinde seçme, taşıma, yeniden boyutlandırma, silme, sınıf değiştirme veya
  sıfırdan çizme; serbest zoom in/out.
- Export: görsel sonuçlar (tam görüntü ya da kesit kesit) ve/veya CBS formatları (`.shp`, `.csv`, `.geojson`, `.gpkg`).

## Kurulum

```bash
pip install sas-manhole-gui
manhole-gui
```

Geliştirme için:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
manhole-gui
```

## Bağımsız .exe

```powershell
pip install pyinstaller
pyinstaller build_exe.spec
# dist\manhole-gui\manhole-gui.exe
```

## Kullanım

1. **Aç** → `.tif/.tiff` dosyası, çoklu dosya ya da klasör seç.
2. **Model Yükle** → bir `.pt` dosyası seç; sınıflar otomatik okunur, istersen `data.yaml` kullan veya elle düzenle.
3. **Çalıştır** → seçili görüntülerde tespiti başlat, ilerleme çubuğunu izle.
4. Sonuçları görüntü üzerinde düzenle (taşı / sil / sınıf değiştir / yeni kutu çiz).
5. **Export** → görsel ve/veya CBS formatlarında dışa aktar.
