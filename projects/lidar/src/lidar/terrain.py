"""DEM/DSM/CHM raster generation and flow direction analysis."""

import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.fill import fillnodata
from pyproj import Transformer

RESOLUTION = 0.3  # meters — matches native LIDAR pulse spacing
EPT_URL = "s3://usgs-lidar-public/RI_Statewide_1_D22/ept.json"
NODATA = -9999.0


def _bounds_3857_from_latlon(lat: float, lon: float, radius_m: float) -> str:
    """Return PDAL bounds string in EPSG:3857."""
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    cx, cy = transformer.transform(lon, lat)
    xmin, ymin, xmax, ymax = cx - radius_m, cy - radius_m, cx + radius_m, cy + radius_m
    return f"([{xmin},{xmax}],[{ymin},{ymax}])"


def build_dem(
    lat: float,
    lon: float,
    radius_m: float,
    out_path: Path,
    ept_url: str = EPT_URL,
    resolution: float = RESOLUTION,
) -> Path:
    """Build bare-earth DEM from class-2 (ground) points.

    Uses PDAL writers.gdal for native C++ rasterization.
    Output: GeoTIFF, EPSG:32619, float32, Z in meters NAVD88.
    """
    import pdal  # deferred

    bounds = _bounds_3857_from_latlon(lat, lon, radius_m)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pipeline_def = {
        "pipeline": [
            {
                "type": "readers.ept",
                "filename": ept_url,
                "bounds": bounds,
            },
            {
                "type": "filters.range",
                "limits": "Classification[2:2]",
            },
            {
                "type": "filters.reprojection",
                "in_srs": "EPSG:3857",
                "out_srs": "EPSG:32619",
            },
            # Scale Z from US Survey Feet to meters
            {
                "type": "filters.assign",
                "assignment": "Z[:]=Z*0.3048006",
            },
            {
                "type": "writers.gdal",
                "filename": str(out_path),
                "resolution": resolution,
                "output_type": "mean",
                "data_type": "float32",
                "nodata": NODATA,
                "gdalopts": "COMPRESS=LZW",
                "override_srs": "EPSG:32619",
            },
        ]
    }

    pipeline = pdal.Pipeline(json.dumps(pipeline_def))
    pipeline.execute()
    return out_path


def build_dsm(
    lat: float,
    lon: float,
    radius_m: float,
    out_path: Path,
    ept_url: str = EPT_URL,
    resolution: float = RESOLUTION,
) -> Path:
    """Build surface model (DSM) from class 2–5 (ground + vegetation).

    Output: GeoTIFF, EPSG:32619, float32, Z in meters.
    """
    import pdal  # deferred

    bounds = _bounds_3857_from_latlon(lat, lon, radius_m)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pipeline_def = {
        "pipeline": [
            {
                "type": "readers.ept",
                "filename": ept_url,
                "bounds": bounds,
            },
            {
                "type": "filters.range",
                "limits": "Classification[2:5]",
            },
            {
                "type": "filters.reprojection",
                "in_srs": "EPSG:3857",
                "out_srs": "EPSG:32619",
            },
            {
                "type": "filters.assign",
                "assignment": "Z[:]=Z*0.3048006",
            },
            {
                "type": "writers.gdal",
                "filename": str(out_path),
                "resolution": resolution,
                "output_type": "max",  # max Z gives surface height
                "data_type": "float32",
                "nodata": NODATA,
                "gdalopts": "COMPRESS=LZW",
                "override_srs": "EPSG:32619",
            },
        ]
    }

    pipeline = pdal.Pipeline(json.dumps(pipeline_def))
    pipeline.execute()
    return out_path


def build_chm(dem_path: Path, dsm_path: Path, out_path: Path) -> Path:
    """Build Canopy Height Model: CHM = DSM - DEM.

    Values > 2m indicate tree canopy.
    Output: GeoTIFF, same projection/resolution as inputs.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(dem_path) as dem_src, rasterio.open(dsm_path) as dsm_src:
        dem = dem_src.read(1).astype("float32")
        dsm = dsm_src.read(1).astype("float32")
        profile = dem_src.profile.copy()

        dem_nodata = dem_src.nodata or NODATA
        dsm_nodata = dsm_src.nodata or NODATA

        valid = (dem != dem_nodata) & (dsm != dsm_nodata)
        chm = np.where(valid, np.maximum(dsm - dem, 0.0), NODATA)

        profile.update(nodata=NODATA)

        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(chm, 1)

    return out_path


def compute_slope(dem_path: Path, out_path: Path) -> Path:
    """Compute slope in percent from DEM using numpy gradient.

    Output: GeoTIFF, same projection as DEM.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(dem_path) as src:
        dem = src.read(1).astype("float32")
        res = src.res  # (pixel_height, pixel_width) in meters
        profile = src.profile.copy()
        nodata = src.nodata or NODATA

    valid = dem != nodata

    # Replace nodata with local mean for gradient calc (avoid edge artifacts)
    dem_filled = dem.copy()
    dem_filled[~valid] = np.nanmean(dem[valid]) if valid.any() else 0.0

    # numpy gradient returns [dz/dy, dz/dx] for row-major array
    dy, dx = np.gradient(dem_filled, res[0], res[1])
    slope_rad = np.arctan(np.sqrt(dx**2 + dy**2))
    slope_pct = np.tan(slope_rad) * 100.0
    slope_pct[~valid] = NODATA

    profile.update(dtype="float32", nodata=NODATA)

    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(slope_pct.astype("float32"), 1)

    return out_path


def fill_nodata(raster_path: Path, max_search_distance: int = 10) -> None:
    """Fill small nodata holes in raster using rasterio fillnodata (in-place)."""
    with rasterio.open(raster_path, "r+") as src:
        data = src.read(1)
        nodata = src.nodata or NODATA
        mask = (data != nodata).astype("uint8")
        filled = fillnodata(data, mask=mask, max_search_distance=max_search_distance)
        src.write(filled, 1)


def compute_flow(dem_path: Path, out_dir: Path) -> dict[str, Path]:
    """Compute flow direction and accumulation rasters using pysheds 0.2.x.

    Returns dict with paths: 'flow_dir', 'flow_acc'
    """
    from pysheds.grid import Grid

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # pysheds 0.2.x string-based dataset API
    grid = Grid.from_raster(str(dem_path), data_name="dem")

    # Condition DEM
    grid.fill_pits("dem", out_name="pit_filled")
    grid.fill_depressions("pit_filled", out_name="flooded")
    grid.resolve_flats("flooded", out_name="inflated")

    # D8 flow direction + accumulation
    grid.flowdir(data="inflated", out_name="flow_dir")
    grid.accumulation(data="flow_dir", out_name="flow_acc")

    flow_dir_path = out_dir / "flow_dir.tif"
    flow_acc_path = out_dir / "flow_acc.tif"

    grid.to_raster("flow_dir", filename=str(flow_dir_path))
    grid.to_raster("flow_acc", filename=str(flow_acc_path))

    return {"flow_dir": flow_dir_path, "flow_acc": flow_acc_path}


def extract_elevation_stats(
    dem_path: Path,
    slope_path: Path,
    flow_acc_path: Path,
    lat: float,
    lon: float,
    radius_m: float,
) -> dict:
    """Extract elevation, slope, and upslope area stats within a radius.

    Args:
        dem_path: Bare-earth DEM GeoTIFF (EPSG:32619, meters).
        slope_path: Slope GeoTIFF (percent).
        flow_acc_path: Flow accumulation GeoTIFF.
        lat: Query point latitude (WGS84).
        lon: Query point longitude (WGS84).
        radius_m: Radius in meters.

    Returns:
        Dict with mean_elev_m, mean_slope_pct, upslope_area_m2.
    """
    from shapely.geometry import Point
    from rasterio.mask import mask as rio_mask

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32619", always_xy=True)
    cx, cy = transformer.transform(lon, lat)
    circle = Point(cx, cy).buffer(radius_m)
    geom = [circle.__geo_interface__]

    def _mean_valid(path: Path, nodata_val: float = NODATA) -> float:
        with rasterio.open(path) as src:
            try:
                data, _ = rio_mask(src, geom, crop=True, nodata=nodata_val)
            except Exception:
                return float("nan")
        arr = data[0].astype("float32")
        valid = arr[arr != nodata_val]
        return float(np.nanmean(valid)) if len(valid) > 0 else float("nan")

    mean_elev = _mean_valid(dem_path)
    mean_slope = _mean_valid(slope_path)

    # Upslope area: mean flow accumulation × cell area
    with rasterio.open(flow_acc_path) as src:
        cell_area = abs(src.res[0] * src.res[1])
        try:
            data, _ = rio_mask(src, geom, crop=True, nodata=NODATA)
        except Exception:
            data = np.array([[[NODATA]]])
    acc_arr = data[0].astype("float32")
    valid_acc = acc_arr[acc_arr != NODATA]
    mean_acc = float(np.nanmean(valid_acc)) if len(valid_acc) > 0 else float("nan")
    upslope_area = mean_acc * cell_area

    return {
        "mean_elev_m": round(mean_elev, 2),
        "mean_slope_pct": round(mean_slope, 2),
        "upslope_area_m2": round(upslope_area, 1),
    }
