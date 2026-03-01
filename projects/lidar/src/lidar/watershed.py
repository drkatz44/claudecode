"""HUC12 watershed boundary fetch from USGS WBD REST API."""

import json
import os
import time
from pathlib import Path

import geopandas as gpd
import requests
from shapely.geometry import shape, MultiPolygon

CACHE_DIR = Path(os.environ.get("LIDAR_CACHE_DIR", Path.home() / ".cache" / "lidar"))
CACHE_TTL = 7 * 24 * 3600  # 7 days

WBD_URL = "https://hydro.nationalmap.gov/arcgis/rest/services/wbd/MapServer/6/query"

# HUC layer map (MapServer layer IDs)
HUC_LAYERS = {
    "huc12": 6,
    "huc10": 5,
    "huc8": 4,
}


def _cache_path(huc_level: str, lat: float, lon: float) -> Path:
    return CACHE_DIR / f"{huc_level}_{lat:.4f}_{lon:.4f}.geojson"


def _is_cached(path: Path) -> bool:
    if not path.exists():
        return False
    return time.time() - path.stat().st_mtime < CACHE_TTL


def fetch_huc(
    lat: float,
    lon: float,
    huc_level: str = "huc12",
    use_cache: bool = True,
) -> gpd.GeoDataFrame:
    """Fetch HUC watershed polygon(s) containing the given point.

    Args:
        lat: Latitude (WGS84).
        lon: Longitude (WGS84).
        huc_level: One of 'huc12', 'huc10', 'huc8'.
        use_cache: Whether to use disk cache.

    Returns:
        GeoDataFrame with HUC polygon(s) and metadata fields:
        huc12 (or huc10/huc8), name, areasqkm.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _cache_path(huc_level, lat, lon)

    if use_cache and _is_cached(cache_path):
        return gpd.read_file(cache_path)

    layer_id = HUC_LAYERS.get(huc_level, 6)
    url = f"https://hydro.nationalmap.gov/arcgis/rest/services/wbd/MapServer/{layer_id}/query"

    params = {
        "geometry": json.dumps({"x": lon, "y": lat}),
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": f"{huc_level},name,areasqkm",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
    }

    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    features = data.get("features", [])
    if not features:
        return gpd.GeoDataFrame(columns=["geometry", huc_level, "name", "areasqkm"], crs="EPSG:4326")

    gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")

    # Handle MultiPolygon case (pond straddles HUC boundary)
    gdf = _merge_if_multiple(gdf, huc_level)

    if use_cache:
        gdf.to_file(cache_path, driver="GeoJSON")

    return gdf


def _merge_if_multiple(gdf: gpd.GeoDataFrame, huc_field: str) -> gpd.GeoDataFrame:
    """If multiple HUC12 units returned, union them into a single MultiPolygon row."""
    if len(gdf) <= 1:
        return gdf

    names = ", ".join(gdf["name"].dropna().unique())
    hucs = ", ".join(gdf[huc_field].dropna().unique())
    total_area = gdf["areasqkm"].sum()
    unioned = gdf.union_all() if hasattr(gdf, "union_all") else gdf.geometry.unary_union

    merged = gpd.GeoDataFrame(
        [{huc_field: hucs, "name": names, "areasqkm": total_area, "geometry": unioned}],
        crs=gdf.crs,
    )
    return merged


def huc12_bbox(gdf: gpd.GeoDataFrame) -> tuple[float, float, float, float]:
    """Return (xmin, ymin, xmax, ymax) bounding box of HUC12 polygon(s)."""
    bounds = gdf.total_bounds  # [xmin, ymin, xmax, ymax]
    return tuple(bounds)
