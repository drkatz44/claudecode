# Project: lidar

## Purpose
LIDAR-based residential density analysis for Green Hill Pond, RI.
Subproject 1 of a groundwater/water-quality study — residential structures near the pond proxy for septic/fertilizer loading contributing to groundwater discharge.

Reads USGS LIDAR point clouds directly from S3 (bypassing USGS portal) via PDAL EPT protocol.

## Status
🟢 Active — Phase 1 (local Mac analysis)

## Stack
- Python 3.11+ via uv
- `pdal` (PyPI binary wheels, v3.x) — EPT S3 reader, writers.gdal rasterizer
- `numpy`, `scipy`, `scikit-learn` (DBSCAN) — point cloud processing
- `geopandas`, `shapely`, `pyproj` — geometry + CRS transforms
- `rasterio` — DEM/DSM/CHM raster I/O
- `pysheds` — flow direction, accumulation, watershed delineation
- `folium` — interactive HTML map
- `requests` — RIGIS parcel download
- `typer`, `rich` — CLI

## Data Sources
| Source | URL/Endpoint |
|--------|-------------|
| USGS LIDAR EPT | `s3://usgs-lidar-public/RI_Statewide_1_D22/ept.json` |
| RIGIS Parcels | REST: `https://gis.ri.gov/server/rest/services/Parcels/RI_Statewide_Parcels/MapServer/0/query` |
| USGS WBD HUC12 | `https://hydro.nationalmap.gov/arcgis/rest/services/wbd/MapServer/6/query` |

## Key Files
```
src/lidar/
  fetch.py       # PDAL EPT reader → structured numpy array (Z converted ft→m)
  buildings.py   # DBSCAN clustering class-6 points → building centroids GeoDataFrame
  terrain.py     # DEM/DSM/CHM/slope rasters via PDAL writers.gdal + pysheds flow
  parcels.py     # RIGIS parcel download, use-code normalization, residential flag
  watershed.py   # USGS WBD HUC12 REST API fetch
  spatial.py     # Radius buffer counts + watershed counts + elevation stats
  viz.py         # Folium HTML map with toggleable layers
  cli.py         # Typer CLI: analyze, terrain, map, export

data/
  green_hill_query_points.geojson  # 10 points around pond (edit to add/remove)

output/                            # Generated (gitignored)
  dem_bare_earth.tif               # Class-2 ground DEM (0.3m, EPSG:32619, NAVD88 meters)
  dsm_with_trees.tif               # Class 2-5 DSM
  chm.tif                          # Canopy Height Model (CHM > 2m = canopy)
  slope.tif                        # Slope percent
  flow_dir.tif / flow_acc.tif      # D8 flow direction/accumulation (pysheds)
  buildings.geojson                # Detected building centroids + residential flag
  results.csv                      # Point × radius residential/total counts
  green_hill_map.html              # Folium interactive map
```

## Setup Prerequisites
```bash
# PDAL has no PyPI wheels — must install system library first
brew install pdal  # installs libpdal (~500MB)
```

## Usage
```bash
cd projects/lidar
uv sync

# Step 1: Build terrain rasters (DEM, DSM, CHM, slope, flow)
uv run lidar terrain

# Step 2: Count residences + elevation stats per query point
uv run lidar analyze

# Step 3: Generate interactive HTML map
uv run lidar map
open output/green_hill_map.html

# Step 4: Export buildings.geojson + results.csv
uv run lidar export

# Run tests
uv run pytest

# Options
uv run lidar analyze --no-parcels   # Skip RIGIS parcel join
uv run lidar terrain --no-flow      # Skip flow direction (faster)
uv run lidar --help                 # All commands/options
```

## Coordinate System Strategy
- **Fetch**: EPSG:3857 (EPT native)
- **Rasters**: EPSG:32619 (UTM Zone 19N, 0.3m cells)
- **Analysis distances**: EPSG:32619 (accurate metric distances)
- **Output / GeoJSON**: EPSG:4326 (WGS84 standard)

## Current State (2026-03)

### Working
- All source modules written (fetch, buildings, terrain, parcels, watershed, spatial, viz, cli)
- Full test suite (28/28 passing): test_fetch, test_buildings, test_terrain, test_spatial
- Query points GeoJSON with 10 pond shoreline/neighborhood locations
- `brew install pdal` + `uv sync` verified working (pdal 3.5.3, Python 3.12)

### Pending
- First live S3 fetch run (requires network)
- RIGIS parcel REST endpoint validation (field names vary by town)
- Terrain raster generation + flow analysis
- Folium map output verification

### Gotchas
- EPT Z values are in **US Survey Feet (NAVD88)** — `× 0.3048006` before writing rasters (done in fetch.py and terrain.py)
- EPT bounds must be in **EPSG:3857** (not 4326)
- **PDAL has no PyPI wheels** — `brew install pdal` required first, then `uv sync` builds Python bindings
- `pysheds<0.3` required (0.3+ needs numba/llvmlite which fails to build on Python 3.12)
- RIGIS parcel field names vary by town: `USE_CODE` / `PROP_CLASS` / `LAND_USE` — normalized in parcels.py
- DBSCAN eps=3m works for detached houses; may split large structures (adjust per results)
- Green Hill Pond straddles South Kingstown AND Charlestown — parcels from both towns needed
- At 0.3m resolution, 1.5km radius = ~100M cells = ~400MB per raster; Mac handles fine
- pysheds requires DEM as rasterio-format GeoTIFF (PDAL writes compatible format)
- HUC12 API needs internet; mocked in tests

## Notes
- Phase 1 (this): Google Colab + Google Drive (primary path); local Mac also works
- Phase 2 (future): Full HUC12 watershed — just increase FETCH_RADIUS_M in the notebook
- Code is AOI-parameterized: same notebook, bigger radius for Phase 2
- S3 egress from USGS public bucket is free
- `LIDAR_CACHE_DIR` env var controls cache location (set by Colab notebook to Drive path)

## Colab Workflow
```
notebooks/green_hill_analysis.ipynb  ← open in Colab
  Cell 1: Mount Drive → /content/drive/MyDrive/lidar-analysis/
  Cell 2: pip install pdal + deps (Linux wheels work directly, no brew)
  Cell 3: Config (radius, resolution, query points)
  Cells 4–10: Fetch → buildings → parcels → HUC12 → terrain → analysis → map
  All output saved to Drive (cache survives between Colab sessions)
```
