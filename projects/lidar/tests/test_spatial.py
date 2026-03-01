"""Tests for spatial.py — radius counts and watershed analysis with known geometry."""

import json
import tempfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Point, Polygon

from lidar.spatial import count_buildings_in_radius, count_buildings_in_watershed, load_query_points


def make_buildings(points_wgs84: list[tuple[float, float]], is_residential: list[bool | None]) -> gpd.GeoDataFrame:
    """Create a building GeoDataFrame at given lon/lat coordinates."""
    geoms = [Point(lon, lat) for lon, lat in points_wgs84]
    return gpd.GeoDataFrame(
        {"is_residential": is_residential, "area_m2": [50.0] * len(geoms)},
        geometry=geoms,
        crs="EPSG:4326",
    )


def test_count_buildings_within_radius():
    """Buildings within radius should be counted; outside should not."""
    # Query point at pond center (approx)
    query = Point(-71.6156, 41.3707)

    # Two buildings very close (~100m), one far away (~2000m)
    close_lon, close_lat = -71.6150, 41.3710   # ~60m away
    far_lon, far_lat = -71.5900, 41.3707        # ~2200m away

    buildings = make_buildings(
        [(close_lon, close_lat), (far_lon, far_lat)],
        [True, True],
    )

    counts_500 = count_buildings_in_radius(query, buildings, radius_m=500)
    counts_1000 = count_buildings_in_radius(query, buildings, radius_m=1000)

    assert counts_500["total"] == 1, f"Expected 1 within 500m, got {counts_500['total']}"
    assert counts_1000["total"] == 1, f"Expected 1 within 1000m, got {counts_1000['total']}"


def test_residential_vs_nonresidential_count():
    query = Point(-71.6156, 41.3707)
    buildings = make_buildings(
        [(-71.6150, 41.3710), (-71.6145, 41.3705), (-71.6155, 41.3708)],
        [True, False, None],  # residential, non-res, unknown
    )
    counts = count_buildings_in_radius(query, buildings, radius_m=500)
    assert counts["total"] == 3
    assert counts["residential"] == 1  # only the True one


def test_empty_buildings():
    query = Point(-71.6156, 41.3707)
    buildings = gpd.GeoDataFrame(
        columns=["geometry", "is_residential"], crs="EPSG:4326"
    )
    buildings = buildings.set_geometry("geometry")
    counts = count_buildings_in_radius(query, buildings, radius_m=500)
    assert counts["total"] == 0
    assert counts["residential"] == 0


def test_count_in_watershed():
    """Buildings inside watershed polygon should be counted."""
    # Simple square watershed around pond center
    watershed_poly = Polygon([
        (-71.65, 41.35), (-71.58, 41.35),
        (-71.58, 41.40), (-71.65, 41.40),
        (-71.65, 41.35),
    ])
    watershed = gpd.GeoDataFrame(
        {"name": ["test_huc12"], "huc12": ["010900030601"]},
        geometry=[watershed_poly],
        crs="EPSG:4326",
    )

    inside = [(-71.62, 41.37), (-71.61, 41.38)]
    outside = [(-71.70, 41.37)]  # west of watershed

    buildings = make_buildings(inside + outside, [True, True, False])

    counts = count_buildings_in_watershed(buildings, watershed)
    assert counts["total"] == 2
    assert counts["residential"] == 2


def test_load_query_points_from_file():
    """load_query_points should parse GeoJSON and add label column."""
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"label": "test_point"},
                "geometry": {"type": "Point", "coordinates": [-71.6156, 41.3707]},
            }
        ],
    }
    with tempfile.NamedTemporaryFile(suffix=".geojson", mode="w", delete=False) as f:
        json.dump(geojson, f)
        tmp_path = Path(f.name)

    gdf = load_query_points(tmp_path)
    assert len(gdf) == 1
    assert gdf.crs.to_epsg() == 4326
    assert "label" in gdf.columns
    assert gdf.iloc[0]["label"] == "test_point"

    tmp_path.unlink()


def test_load_query_points_adds_default_labels():
    """If no label field, numeric labels are auto-generated."""
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "Point", "coordinates": [-71.6, 41.37]},
            }
        ],
    }
    with tempfile.NamedTemporaryFile(suffix=".geojson", mode="w", delete=False) as f:
        json.dump(geojson, f)
        tmp_path = Path(f.name)

    gdf = load_query_points(tmp_path)
    assert "label" in gdf.columns
    assert "point_" in str(gdf.iloc[0]["label"])
    tmp_path.unlink()


def test_radius_exactly_on_boundary():
    """Points exactly at radius distance — implementation may include/exclude edge cases."""
    query = Point(-71.6156, 41.3707)
    # Use the same UTM projection logic to find a point exactly 500m away
    from pyproj import Transformer
    t_fwd = Transformer.from_crs("EPSG:4326", "EPSG:32619", always_xy=True)
    t_rev = Transformer.from_crs("EPSG:32619", "EPSG:4326", always_xy=True)

    cx, cy = t_fwd.transform(query.x, query.y)
    # Point 499m to the east (well inside)
    near_lon, near_lat = t_rev.transform(cx + 499, cy)
    # Point 501m to the east (just outside)
    far_lon, far_lat = t_rev.transform(cx + 501, cy)

    buildings = make_buildings([(near_lon, near_lat), (far_lon, far_lat)], [True, True])

    counts = count_buildings_in_radius(query, buildings, radius_m=500)
    assert counts["total"] == 1, f"Expected 1 (only near point), got {counts['total']}"
