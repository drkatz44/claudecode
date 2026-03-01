"""Tests for fetch.py — mock PDAL pipeline, validate array handling."""

import json
import numpy as np
import pytest
from unittest.mock import patch, MagicMock

from lidar.fetch import (
    _bounds_3857,
    _format_bounds,
    get_class,
    get_classes,
    to_utm19n,
    FT_TO_M,
)


def make_structured_array(n: int, classification: int = 2) -> np.ndarray:
    """Create a structured numpy array matching PDAL output format."""
    dtype = np.dtype([
        ("X", "float64"),
        ("Y", "float64"),
        ("Z", "float64"),
        ("Classification", "uint8"),
        ("Intensity", "uint16"),
    ])
    arr = np.zeros(n, dtype=dtype)
    arr["X"] = np.linspace(-8000000, -7999900, n)
    arr["Y"] = np.linspace(5100000, 5100100, n)
    arr["Z"] = np.linspace(10.0, 20.0, n)  # in feet
    arr["Classification"] = classification
    return arr


def test_bounds_3857_returns_4_values():
    bounds = _bounds_3857(41.3707, -71.6156, 1000)
    assert len(bounds) == 4
    xmin, ymin, xmax, ymax = bounds
    assert xmax > xmin
    assert ymax > ymin


def test_bounds_3857_radius_symmetric():
    """Buffer should be symmetric around center."""
    bounds = _bounds_3857(41.3707, -71.6156, 1000)
    xmin, ymin, xmax, ymax = bounds
    width = xmax - xmin
    height = ymax - ymin
    # Both should be ~2000m in EPSG:3857 units (at this latitude, x may differ slightly)
    assert abs(height - 2000) < 10, f"Expected ~2000m height, got {height}"


def test_format_bounds():
    bounds = (-100.0, -200.0, 100.0, 200.0)
    result = _format_bounds(bounds)
    assert result == "([-100.0,100.0],[-200.0,200.0])"


def test_get_class_filters_correctly():
    arr = np.concatenate([
        make_structured_array(50, classification=2),
        make_structured_array(30, classification=6),
        make_structured_array(20, classification=3),
    ])
    class2 = get_class(arr, 2)
    assert len(class2) == 50
    assert (class2["Classification"] == 2).all()

    class6 = get_class(arr, 6)
    assert len(class6) == 30


def test_get_classes_multiple():
    arr = np.concatenate([
        make_structured_array(10, classification=2),
        make_structured_array(10, classification=3),
        make_structured_array(10, classification=4),
        make_structured_array(10, classification=5),
        make_structured_array(10, classification=6),
    ])
    veg_and_ground = get_classes(arr, 2, 3, 4, 5)
    assert len(veg_and_ground) == 40
    assert (veg_and_ground["Classification"] != 6).all()


def test_get_class_empty_array():
    arr = make_structured_array(20, classification=2)
    result = get_class(arr, 6)
    assert len(result) == 0


def test_fetch_point_cloud_z_conversion():
    """Ensure Z is converted from feet to meters during fetch."""
    import numpy as np
    from unittest.mock import patch, MagicMock

    # Create mock array with Z in feet
    dtype = np.dtype([
        ("X", "float64"), ("Y", "float64"), ("Z", "float64"),
        ("Classification", "uint8"), ("Intensity", "uint16"),
    ])
    mock_arr = np.zeros(10, dtype=dtype)
    mock_arr["Z"] = 10.0  # 10 US survey feet
    mock_arr["Classification"] = 2

    mock_pipeline = MagicMock()
    mock_pipeline.arrays = [mock_arr.copy()]
    mock_pipeline.execute.return_value = None

    with patch("pdal.Pipeline", return_value=mock_pipeline):
        with patch("lidar.fetch._load_cache", return_value=None):
            with patch("lidar.fetch._save_cache"):
                from lidar.fetch import fetch_point_cloud
                result = fetch_point_cloud(41.3707, -71.6156, radius_m=100, use_cache=False)

    # Z should be converted to meters
    expected_z = 10.0 * FT_TO_M
    assert abs(result["Z"][0] - expected_z) < 0.001, f"Expected {expected_z}, got {result['Z'][0]}"


def test_to_utm19n_shape_preserved():
    arr = make_structured_array(50, classification=2)
    # Set X/Y to valid EPSG:3857 coords near Rhode Island
    arr["X"] = -7975000.0
    arr["Y"] = 5080000.0

    result = to_utm19n(arr)
    assert result.shape == arr.shape
    assert result.dtype == arr.dtype
    # UTM 19N easting for RI should be around 300000-400000
    assert 250000 < result["X"][0] < 450000, f"UTM easting out of range: {result['X'][0]}"
