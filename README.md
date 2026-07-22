# SAS Manhole GUI

Desktop review and editing interface for **manhole / storm-drain / rectangular-cover detection** on
aerial orthophotos, using YOLO-family models (SAS-enhanced) and optional SAM3 text-prompted
semantic segmentation as a pre-filter.

Companion GUI for the SAS-YOLO paper (Bayrak et al., in preparation).

<p align="center">
  <em>Screenshots coming soon — add <code>docs/screenshot-*.png</code> and reference them here.</em>
</p>

---

## Features

- **Multi-image workspace** — open `.tif` / `.tiff` / `.png` / `.jpg` / `.jpeg` files one by one, in bulk, or by folder; thumbnails in the left dock.
- **QGIS-style canvas** — pan, wheel-zoom, high-resolution windowed rendering for huge orthomosaics.
- **YOLO detection** — load any Ultralytics `.pt` (v8 / v11 / SAS variants); class names auto-read from the model or a `data.yaml`, or edited by hand.
- **Background tiling** — configurable 640×640 (or any size) tiling with overlap and NMS merging, run on a background thread with a live progress bar and **Pause / Resume / Stop** controls.
- **Editable predictions** — select boxes, move/resize with handles, change class from the side combo (instant), delete with the `Del` key, or draw new boxes from scratch in a class of your choice. Guide crosshair follows the cursor while drawing.
- **Hover feedback + Undo** — hovered boxes light up before you click; `Ctrl+Z` reverts the last three edits.
- **SAM3 text segmentation** — load a SAM3 checkpoint, type a natural-language prompt (e.g. *road*, *vegetation*, *parking lot*), get polygon regions, and use them to filter the detection run to **inside** or **outside** those regions only.
- **Session memory** — recent folders and files remembered across launches; file dialogs reopen the last used directory.
- **Rich export**
  - Visual: full annotated image *or* per-tile crops with a strict `{stem}_tile_r000_c000_640x640.png` naming.
  - GIS: `.shp` / `.csv` / `.geojson` / `.gpkg`, one row per detection with `col_px, row_px, w_px, h_px, bbox_px, gsd_m, w_m, h_m, area_m2` columns, geometry in the raster's own CRS.

---

## Installation

### Option A — Install from GitHub (recommended)

```bash
pip install git+https://github.com/<your-github-username>/Manhole-GUI.git
manhole-gui
```

That's it. `pip` pulls the source, resolves all dependencies (PySide6, rasterio, ultralytics, geopandas, shapely, pyogrio), builds the package, and installs the `manhole-gui` command.

Python 3.10, 3.11, 3.12, or 3.13 all work. For a clean install, prefer a virtualenv:

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate        # macOS / Linux
pip install git+https://github.com/<your-github-username>/Manhole-GUI.git
manhole-gui
```

### Option B — Install from source (for development)

```bash
git clone https://github.com/<your-github-username>/Manhole-GUI.git
cd Manhole-GUI
python -m venv .venv
.venv\Scripts\activate
pip install -e .
manhole-gui
```

### Option C — Standalone Windows executable

If you don't want to install Python at all, grab the pre-built `.exe` from the
[Releases page](https://github.com/<your-github-username>/Manhole-GUI/releases),
unzip it, and double-click `manhole-gui.exe`.

To build it yourself:

```powershell
pip install pyinstaller
pyinstaller build_exe.spec
# Result: dist\manhole-gui\manhole-gui.exe
```

---

## Quick start

1. Click **Open Files** or **Open Folder**, pick your `.tif` / `.png` / `.jpg` orthophotos. Thumbnails appear on the left.
2. Click **Load Model**, pick your YOLO `.pt` detection weights. Class names are read from the model or, optionally, from a `data.yaml`; you can also edit them by hand.
3. *(Optional)* Click **Load SAM**, pick a SAM3 `.pt`. Open the **SAM** tab, type a prompt like `road`, hit **Segment**. Purple polygons appear over the detected regions.
4. Click **Run**. In the dialog, choose tile size, overlap, confidence, and — if you drew SAM regions — whether to run **inside**, **outside**, or ignore them. Watch the progress bar; use **Pause / Stop** anytime.
5. Review detections. Green ✓ on a thumbnail means "predicted, has boxes"; blue Ø means "predicted, empty". Edit any box: click → move / resize / change class / delete. `Del` deletes, `Ctrl+Z` undoes.
6. Click **Export**, pick output folder + formats. Visual (full / per-tile) and GIS (`.shp` / `.csv` / `.geojson` / `.gpkg`) all supported side-by-side.

---

## Model files

**Detection weights** (YOLO `.pt`): bring your own. The project's paper uses SAS-enhanced YOLOv11m / YOLOv8s. Any Ultralytics-format `.pt` works. Keep the file wherever you like — it's not part of the repo (`.pt` files are `.gitignore`'d because they're large and specific to your training).

**SAM3 weights** (`sam3.pt`, ~3.4 GB): optional. Download from the model provider and place anywhere; the app remembers the last-used path.

For distribution, consider [Hugging Face Model Hub](https://huggingface.co/) or [Zenodo](https://zenodo.org/) for the weights, and link to them from this README once the paper is out.

---

## Keyboard shortcuts

| Key | Action |
|---|---|
| `Del` / `Backspace` | Delete the selected detection or SAM region |
| `Ctrl+Z` | Undo the last edit (up to 3 steps) |
| Mouse wheel | Zoom in / out under the cursor |
| Middle-drag | Pan |
| `Ctrl+click` (thumbnails) | Add to multi-selection without switching the active image |

---

## Export columns

Each row of the vector export is one detection.

| Column | Meaning |
|---|---|
| `id` | Session-local detection id |
| `image` | Source image file name |
| `class_id`, `class_name` | Predicted class |
| `confidence` | Model confidence, or `1.0` for manually drawn boxes |
| `col_px`, `row_px` | Top-left of bounding box in image pixel coordinates (origin = image top-left) |
| `w_px`, `h_px` | Bounding-box dimensions in pixels |
| `bbox_px` | `w_px × h_px` |
| `gsd_m` | Ground sample distance (m/pixel) computed from the raster CRS |
| `w_m`, `h_m` | Real-world bounding-box dimensions (metres) = `w_px × gsd_m`, etc. |
| `area_m2` | `w_m × h_m` |
| `edited` | `True` if you moved / resized / relabelled after prediction |
| `source` | `"model"` or `"manual"` |
| `geometry` | Bounding-box polygon in the raster's CRS |

For non-georeferenced PNG/JPEG inputs, `gsd_m`, `w_m`, `h_m`, `area_m2` are empty; everything else is still populated.

---

## Requirements

- Python ≥ 3.10
- Works on Windows, macOS, and Linux. GPU (CUDA) is optional but strongly recommended for inference.
- The `pyproject.toml` pins PySide6 to `<6.10` because 6.11's Windows wheels ship a broken Qt DLL that fails to import in some environments.

---

## Troubleshooting

- **`ImportError: DLL load failed while importing QtCore`** — you're on PySide6 ≥ 6.11 in a mixed environment. `pip install "PySide6<6.10"` inside your venv.
- **Inference is very slow** — you're on CPU. Install a CUDA-enabled PyTorch build and ultralytics will pick it up automatically.
- **SAM text prompt fails with "model did not accept a text prompt"** — the `.pt` you loaded is a mask-only SAM checkpoint. Use one that supports text prompts (SAM3-style).
- **Export shapefile column names are truncated** — this is a shapefile format limitation (10 chars max). Use `.gpkg` or `.geojson` if you need long names.

---

## Citation

If you use this tool in academic work, please cite the SAS-YOLO paper:

```bibtex
@article{Bayrak2026SAS,
  title   = {SAS-YOLO: ...},
  author  = {Bayrak, Onur Can and ...},
  journal = {...},
  year    = {2026}
}
```

(Fill in once published.)

---

## License

MIT — see [LICENSE](LICENSE).
