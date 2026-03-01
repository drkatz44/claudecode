"""RIGIS parcel download, caching, and residential classification."""

import json
import os
import time
from pathlib import Path
from zipfile import ZipFile

import geopandas as gpd
import requests

_base = Path(os.environ.get("LIDAR_CACHE_DIR", Path.home() / ".cache" / "lidar"))
CACHE_DIR = _base / "parcels"
CACHE_TTL = 7 * 24 * 3600  # 7 days (parcel data is stable)

# RIGIS REST endpoints for parcel shapefiles
# South Kingstown: ftp or RIGIS ArcGIS rest
RIGIS_PARCELS = {
    "south_kingstown": "https://www.rigis.org/datasets/south-kingstown-parcels/explore",
    "charlestown": "https://www.rigis.org/datasets/charlestown-parcels/explore",
}

# Alternative: RI GIS REST service (statewide parcels)
# RIGIS statewide parcel layer via ArcGIS REST
RIGIS_REST_URL = (
    "https://gis.ri.gov/server/rest/services/Parcels/RI_Statewide_Parcels/MapServer/0/query"
)

# RI assessor use codes: 100-199 = residential
RESIDENTIAL_MIN = 100
RESIDENTIAL_MAX = 199

# Field name aliases across towns (RI assessor varies by municipality)
USE_CODE_FIELDS = ["USE_CODE", "PROP_CLASS", "LAND_USE", "USECD", "USE_CD", "USECODE"]


def _cache_path(name: str) -> Path:
    return CACHE_DIR / f"{name}.gpkg"


def _is_cached(path: Path) -> bool:
    if not path.exists():
        return False
    return time.time() - path.stat().st_mtime < CACHE_TTL


def _normalize_use_code(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Standardize use code field to 'use_code' (integer)."""
    gdf = gdf.copy()
    for field in USE_CODE_FIELDS:
        if field in gdf.columns:
            gdf["use_code"] = gdf[field]
            break
    else:
        gdf["use_code"] = None

    if gdf["use_code"] is not None:
        gdf["use_code"] = gdf["use_code"].astype(str).str.extract(r"(\d+)")[0]
        gdf["use_code"] = gdf["use_code"].astype(float).astype("Int64")

    return gdf


def fetch_parcels_rest(
    bbox: tuple[float, float, float, float],
    out_crs: str = "EPSG:4326",
    max_records: int = 2000,
) -> gpd.GeoDataFrame:
    """Fetch parcels from RIGIS REST API within a bounding box.

    Args:
        bbox: (xmin, ymin, xmax, ymax) in WGS84.
        out_crs: Output CRS.
        max_records: Max records per REST page.

    Returns:
        GeoDataFrame of parcels with normalized use_code field.
    """
    xmin, ymin, xmax, ymax = bbox
    params = {
        "geometry": f"{xmin},{ymin},{xmax},{ymax}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "f": "geojson",
        "resultRecordCount": max_records,
    }

    resp = requests.get(RIGIS_REST_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if not data.get("features"):
        return gpd.GeoDataFrame(columns=["geometry", "use_code"], crs=out_crs)

    gdf = gpd.GeoDataFrame.from_features(data["features"], crs="EPSG:4326")
    gdf = _normalize_use_code(gdf)

    if gdf.crs and str(gdf.crs) != out_crs:
        gdf = gdf.to_crs(out_crs)

    return gdf


def load_parcels(
    bbox: tuple[float, float, float, float],
    cache_name: str = "green_hill_parcels",
    use_cache: bool = True,
) -> gpd.GeoDataFrame:
    """Load parcels for the given bounding box, with disk cache.

    Args:
        bbox: (xmin, ymin, xmax, ymax) in WGS84.
        cache_name: Cache file stem.
        use_cache: Whether to use disk cache.

    Returns:
        GeoDataFrame with 'use_code' and 'is_residential' columns.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _cache_path(cache_name)

    if use_cache and _is_cached(cache_path):
        return gpd.read_file(cache_path)

    gdf = fetch_parcels_rest(bbox)
    gdf = flag_residential(gdf)

    if use_cache:
        gdf.to_file(cache_path, driver="GPKG")

    return gdf


def flag_residential(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Add 'is_residential' boolean column based on use_code range 100-199."""
    gdf = gdf.copy()
    if "use_code" not in gdf.columns or gdf["use_code"].isna().all():
        gdf["is_residential"] = None
        return gdf

    code = gdf["use_code"]
    gdf["is_residential"] = (code >= RESIDENTIAL_MIN) & (code <= RESIDENTIAL_MAX)
    return gdf


def join_buildings_parcels(
    buildings: gpd.GeoDataFrame,
    parcels: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Spatial join buildings to parcels; adds 'is_residential' to buildings.

    Args:
        buildings: GeoDataFrame of building centroids (EPSG:4326).
        parcels: GeoDataFrame of parcels with 'is_residential' (EPSG:4326).

    Returns:
        Buildings GeoDataFrame with 'is_residential' column.
    """
    if buildings.empty or parcels.empty:
        buildings = buildings.copy()
        buildings["is_residential"] = None
        return buildings

    # Ensure both in same CRS
    if parcels.crs != buildings.crs:
        parcels = parcels.to_crs(buildings.crs)

    keep_cols = ["geometry", "use_code", "is_residential"]
    parcel_slim = parcels[[c for c in keep_cols if c in parcels.columns]].copy()

    joined = gpd.sjoin(buildings, parcel_slim, how="left", predicate="within")

    # Drop duplicate rows from one-to-many joins (take first match)
    joined = joined[~joined.index.duplicated(keep="first")]

    # Restore original index alignment
    buildings = buildings.copy()
    buildings["use_code"] = joined.get("use_code")
    buildings["is_residential"] = joined.get("is_residential")

    return buildings
