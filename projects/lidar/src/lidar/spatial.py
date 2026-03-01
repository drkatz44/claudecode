"""Radius-based and watershed-bounded building counts + elevation stats."""

import json
from pathlib import Path
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import Point, shape


def load_query_points(geojson_path: Path) -> gpd.GeoDataFrame:
    """Load query points GeoJSON → GeoDataFrame (EPSG:4326)."""
    gdf = gpd.read_file(geojson_path)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    elif str(gdf.crs) != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")
    if "label" not in gdf.columns:
        gdf["label"] = [f"point_{i}" for i in range(len(gdf))]
    return gdf


def count_buildings_in_radius(
    query_point: Point,
    buildings: gpd.GeoDataFrame,
    radius_m: float,
    crs_utm: str = "EPSG:32619",
) -> dict[str, int]:
    """Count total and residential buildings within radius_m of query_point.

    Args:
        query_point: Shapely Point in WGS84.
        buildings: GeoDataFrame of building centroids (EPSG:4326).
        radius_m: Radius in meters.
        crs_utm: UTM CRS for accurate metric buffering.

    Returns:
        Dict with 'total' and 'residential' counts.
    """
    if buildings.empty:
        return {"total": 0, "residential": 0}

    # Project to UTM for metric buffer
    transformer_fwd = Transformer.from_crs("EPSG:4326", crs_utm, always_xy=True)
    transformer_rev = Transformer.from_crs(crs_utm, "EPSG:4326", always_xy=True)

    cx, cy = transformer_fwd.transform(query_point.x, query_point.y)
    buffer_utm = Point(cx, cy).buffer(radius_m)

    # Project buildings to UTM for intersection test
    buildings_utm = buildings.to_crs(crs_utm)
    within = buildings_utm[buildings_utm.geometry.within(buffer_utm)]

    total = len(within)
    if "is_residential" in within.columns:
        residential = int(within["is_residential"].fillna(False).sum())
    else:
        residential = 0

    return {"total": total, "residential": residential}


def count_buildings_in_watershed(
    buildings: gpd.GeoDataFrame,
    watershed: gpd.GeoDataFrame,
) -> dict[str, int]:
    """Count buildings within the HUC12 watershed polygon.

    Returns:
        Dict with 'total' and 'residential' counts.
    """
    if buildings.empty or watershed.empty:
        return {"total": 0, "residential": 0}

    ws_geom = watershed.geometry.union_all() if hasattr(watershed.geometry, "union_all") \
        else watershed.geometry.unary_union

    within = buildings[buildings.geometry.within(ws_geom)]
    total = len(within)
    if "is_residential" in within.columns:
        residential = int(within["is_residential"].fillna(False).sum())
    else:
        residential = 0

    return {"total": total, "residential": residential}


def analyze(
    query_points_path: Path,
    buildings: gpd.GeoDataFrame,
    watershed: Optional[gpd.GeoDataFrame],
    dem_path: Optional[Path],
    slope_path: Optional[Path],
    flow_acc_path: Optional[Path],
    radii: list[int] = (500, 1000),
) -> pd.DataFrame:
    """Full spatial analysis: radius counts + elevation stats per query point.

    Returns:
        DataFrame with columns:
        point_id, label, lat, lon,
        res_500m, total_500m, res_1000m, total_1000m,
        res_huc12, total_huc12,
        mean_elev_m, mean_slope_pct, upslope_area_m2
    """
    from .terrain import extract_elevation_stats

    query_points = load_query_points(query_points_path)

    # HUC12 totals (same for all query points)
    ws_counts = {"total": 0, "residential": 0}
    if watershed is not None and not watershed.empty:
        ws_counts = count_buildings_in_watershed(buildings, watershed)

    records = []
    for idx, row in query_points.iterrows():
        geom = row.geometry
        lat = geom.y
        lon = geom.x
        label = row.get("label", f"point_{idx}")

        record = {
            "point_id": idx,
            "label": label,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
        }

        # Radius counts
        for r in radii:
            counts = count_buildings_in_radius(geom, buildings, radius_m=r)
            record[f"res_{r}m"] = counts["residential"]
            record[f"total_{r}m"] = counts["total"]

        # HUC12 totals
        record["res_huc12"] = ws_counts["residential"]
        record["total_huc12"] = ws_counts["total"]

        # Elevation + slope stats
        if dem_path and dem_path.exists() and slope_path and slope_path.exists():
            stats = extract_elevation_stats(
                dem_path, slope_path, flow_acc_path,
                lat=lat, lon=lon, radius_m=max(radii),
            )
            record.update(stats)
        else:
            record.update({"mean_elev_m": None, "mean_slope_pct": None, "upslope_area_m2": None})

        records.append(record)

    return pd.DataFrame(records)
