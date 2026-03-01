"""PDAL EPT reader — fetch point cloud from USGS S3, split by classification."""

import hashlib
import json
import time
from pathlib import Path

import numpy as np
from pyproj import Transformer

import os
CACHE_DIR = Path(os.environ.get("LIDAR_CACHE_DIR", Path.home() / ".cache" / "lidar"))
CACHE_TTL = 4 * 3600  # 4 hours
EPT_URL = "s3://usgs-lidar-public/RI_Statewide_1_D22/ept.json"

# US Survey Feet to meters conversion factor (NAVD88 Z values in EPT)
FT_TO_M = 0.3048006


def _bounds_3857(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    """Convert lat/lon center + radius to EPSG:3857 bounding box."""
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    cx, cy = transformer.transform(lon, lat)
    return (cx - radius_m, cy - radius_m, cx + radius_m, cy + radius_m)


def _format_bounds(bounds: tuple) -> str:
    """Format bounds tuple as PDAL bounds string '([xmin,xmax],[ymin,ymax])'."""
    xmin, ymin, xmax, ymax = bounds
    return f"([{xmin},{xmax}],[{ymin},{ymax}])"


def _cache_key(bounds: tuple, classes: tuple) -> Path:
    key = hashlib.md5(f"{bounds}{classes}".encode()).hexdigest()
    return CACHE_DIR / f"{key}.npy"


def _load_cache(path: Path) -> np.ndarray | None:
    meta_path = path.with_suffix(".json")
    if not path.exists() or not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text())
    if time.time() - meta["cached_at"] > CACHE_TTL:
        return None
    return np.load(str(path))


def _save_cache(path: Path, arr: np.ndarray) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.save(str(path), arr)
    path.with_suffix(".json").write_text(json.dumps({"cached_at": time.time()}))


def fetch_point_cloud(
    lat: float,
    lon: float,
    radius_m: float = 1500,
    ept_url: str = EPT_URL,
    classes: tuple = (2, 3, 4, 5, 6),
    use_cache: bool = True,
) -> np.ndarray:
    """Fetch LIDAR points from USGS EPT (S3) for the given area.

    Returns a structured numpy array with fields: X, Y, Z, Classification, ...
    Z values are converted from US Survey Feet to meters in-place.

    Args:
        lat: Center latitude (WGS84).
        lon: Center longitude (WGS84).
        radius_m: Radius around center to fetch (meters).
        ept_url: EPT endpoint URL.
        classes: LIDAR classification codes to fetch.
        use_cache: Whether to use disk cache.

    Returns:
        Structured numpy array of point records.
    """
    import pdal  # deferred — heavy import

    bounds = _bounds_3857(lat, lon, radius_m)
    cache_path = _cache_key(bounds, classes)

    if use_cache:
        cached = _load_cache(cache_path)
        if cached is not None:
            return cached

    class_filter = "|".join(f"Classification[{c}:{c}]" for c in classes)

    pipeline_def = {
        "pipeline": [
            {
                "type": "readers.ept",
                "filename": ept_url,
                "bounds": _format_bounds(bounds),
            },
            {
                "type": "filters.range",
                "limits": class_filter,
            },
        ]
    }

    pipeline = pdal.Pipeline(json.dumps(pipeline_def))
    pipeline.execute()

    arr = pipeline.arrays[0].copy()

    # Convert Z from US Survey Feet (NAVD88) to meters
    arr["Z"] = arr["Z"] * FT_TO_M

    if use_cache:
        _save_cache(cache_path, arr)

    return arr


def get_class(arr: np.ndarray, cls: int) -> np.ndarray:
    """Filter structured array to a single LIDAR classification code."""
    return arr[arr["Classification"] == cls]


def get_classes(arr: np.ndarray, *cls: int) -> np.ndarray:
    """Filter structured array to multiple LIDAR classification codes."""
    mask = np.zeros(len(arr), dtype=bool)
    for c in cls:
        mask |= arr["Classification"] == c
    return arr[mask]


def to_utm19n(arr: np.ndarray) -> np.ndarray:
    """Reproject X/Y from EPSG:3857 to EPSG:32619 (UTM Zone 19N) in-place copy."""
    transformer = Transformer.from_crs("EPSG:3857", "EPSG:32619", always_xy=True)
    out = arr.copy()
    x, y = transformer.transform(arr["X"], arr["Y"])
    out["X"] = x
    out["Y"] = y
    return out
