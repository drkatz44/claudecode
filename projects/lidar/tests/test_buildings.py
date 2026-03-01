"""Tests for buildings.py — DBSCAN clustering with synthetic point clouds."""

import numpy as np
import pytest
import geopandas as gpd

from lidar.buildings import detect_buildings, MIN_AREA_M2, MAX_AREA_M2


def make_building_points(
    center_x: float,
    center_y: float,
    count: int = 50,
    spread: float = 5.0,
) -> np.ndarray:
    """Generate a tight cluster of class-6 points simulating a building."""
    dtype = np.dtype([
        ("X", "float64"), ("Y", "float64"), ("Z", "float64"),
        ("Classification", "uint8"),
    ])
    arr = np.zeros(count, dtype=dtype)
    rng = np.random.default_rng(42)
    arr["X"] = center_x + rng.uniform(-spread, spread, count)
    arr["Y"] = center_y + rng.uniform(-spread, spread, count)
    arr["Z"] = 5.0
    arr["Classification"] = 6
    return arr


def make_sparse_noise(n: int = 5) -> np.ndarray:
    """Generate sparse class-6 points that should be filtered as noise."""
    dtype = np.dtype([
        ("X", "float64"), ("Y", "float64"), ("Z", "float64"),
        ("Classification", "uint8"),
    ])
    arr = np.zeros(n, dtype=dtype)
    rng = np.random.default_rng(99)
    arr["X"] = rng.uniform(0, 10000, n)
    arr["Y"] = rng.uniform(0, 10000, n)
    arr["Z"] = 5.0
    arr["Classification"] = 6
    return arr


def test_detects_single_building():
    pts = make_building_points(center_x=300000, center_y=4590000, count=50)
    gdf = detect_buildings(pts, input_crs="EPSG:32619")
    assert len(gdf) == 1
    assert gdf.crs.to_epsg() == 4326


def test_detects_multiple_buildings():
    """Two well-separated clusters → two buildings."""
    b1 = make_building_points(300000, 4590000, count=50)
    b2 = make_building_points(300100, 4590100, count=50)  # 141m away
    pts = np.concatenate([b1, b2])
    gdf = detect_buildings(pts, input_crs="EPSG:32619")
    assert len(gdf) == 2


def test_filters_noise_points():
    """Sparse isolated points should not become buildings."""
    noise = make_sparse_noise(5)
    gdf = detect_buildings(noise, input_crs="EPSG:32619")
    assert len(gdf) == 0


def test_empty_input_returns_empty_geodataframe():
    dtype = np.dtype([
        ("X", "float64"), ("Y", "float64"), ("Z", "float64"),
        ("Classification", "uint8"),
    ])
    empty = np.zeros(0, dtype=dtype)
    gdf = detect_buildings(empty, input_crs="EPSG:32619")
    assert isinstance(gdf, gpd.GeoDataFrame)
    assert len(gdf) == 0
    assert gdf.crs.to_epsg() == 4326


def test_output_columns():
    pts = make_building_points(300000, 4590000, count=50)
    gdf = detect_buildings(pts, input_crs="EPSG:32619")
    assert len(gdf) > 0
    for col in ["area_m2", "point_count", "cluster_id"]:
        assert col in gdf.columns, f"Missing column: {col}"


def test_area_filter_min():
    """A single-point cluster (area ≈ 0) should be excluded."""
    dtype = np.dtype([
        ("X", "float64"), ("Y", "float64"), ("Z", "float64"),
        ("Classification", "uint8"),
    ])
    # 15 points in a 0.1m radius (area << 10 m²)
    arr = np.zeros(15, dtype=dtype)
    arr["X"] = 300000 + np.random.uniform(-0.05, 0.05, 15)
    arr["Y"] = 4590000 + np.random.uniform(-0.05, 0.05, 15)
    arr["Classification"] = 6
    gdf = detect_buildings(arr, input_crs="EPSG:32619", min_area_m2=10.0)
    # All points within 0.1m radius → convex hull area ≈ 0 → filtered
    for _, row in gdf.iterrows():
        assert row["area_m2"] >= 10.0


def test_building_centroid_in_expected_location():
    """Centroid of detected building should be near input center."""
    from pyproj import Transformer
    cx, cy = 300000.0, 4590000.0
    pts = make_building_points(cx, cy, count=100, spread=3.0)
    gdf = detect_buildings(pts, input_crs="EPSG:32619")
    assert len(gdf) == 1

    # Convert expected centroid to WGS84 for comparison
    t = Transformer.from_crs("EPSG:32619", "EPSG:4326", always_xy=True)
    exp_lon, exp_lat = t.transform(cx, cy)

    result_geom = gdf.iloc[0].geometry
    assert abs(result_geom.x - exp_lon) < 0.001
    assert abs(result_geom.y - exp_lat) < 0.001
