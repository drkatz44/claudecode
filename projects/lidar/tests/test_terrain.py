"""Tests for terrain.py — DEM interpolation and slope from synthetic data."""

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds
from pathlib import Path
import tempfile

from lidar.terrain import build_chm, compute_slope, NODATA


def write_test_raster(path: Path, data: np.ndarray, crs: str = "EPSG:32619") -> None:
    """Write a float32 GeoTIFF for testing."""
    height, width = data.shape
    transform = from_bounds(300000, 4589900, 300100, 4590000, width, height)
    profile = {
        "driver": "GTiff",
        "dtype": "float32",
        "width": width,
        "height": height,
        "count": 1,
        "crs": crs,
        "transform": transform,
        "nodata": NODATA,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data.astype("float32"), 1)


def test_chm_is_dsm_minus_dem():
    """CHM = DSM - DEM for valid pixels."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dem_data = np.full((10, 10), 3.0)
        dsm_data = np.full((10, 10), 8.0)

        dem_path = Path(tmpdir) / "dem.tif"
        dsm_path = Path(tmpdir) / "dsm.tif"
        chm_path = Path(tmpdir) / "chm.tif"

        write_test_raster(dem_path, dem_data)
        write_test_raster(dsm_path, dsm_data)

        build_chm(dem_path, dsm_path, chm_path)

        with rasterio.open(chm_path) as src:
            chm = src.read(1)

        assert np.allclose(chm, 5.0), f"Expected CHM=5.0, got {chm.mean()}"


def test_chm_clamps_negative_to_zero():
    """CHM should never be negative (DSM < DEM artifacts → 0)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dem_data = np.full((10, 10), 8.0)
        dsm_data = np.full((10, 10), 3.0)  # DSM < DEM (unusual but possible)

        dem_path = Path(tmpdir) / "dem.tif"
        dsm_path = Path(tmpdir) / "dsm.tif"
        chm_path = Path(tmpdir) / "chm.tif"

        write_test_raster(dem_path, dem_data)
        write_test_raster(dsm_path, dsm_data)
        build_chm(dem_path, dsm_path, chm_path)

        with rasterio.open(chm_path) as src:
            chm = src.read(1)
        valid = chm[chm != NODATA]
        assert (valid >= 0).all(), "CHM has negative values"


def test_chm_nodata_propagation():
    """Nodata in DEM or DSM → nodata in CHM."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dem_data = np.full((10, 10), 3.0)
        dem_data[0, 0] = NODATA  # nodata pixel in DEM

        dsm_data = np.full((10, 10), 8.0)

        dem_path = Path(tmpdir) / "dem.tif"
        dsm_path = Path(tmpdir) / "dsm.tif"
        chm_path = Path(tmpdir) / "chm.tif"

        write_test_raster(dem_path, dem_data)
        write_test_raster(dsm_path, dsm_data)
        build_chm(dem_path, dsm_path, chm_path)

        with rasterio.open(chm_path) as src:
            chm = src.read(1)
        assert chm[0, 0] == NODATA


def test_slope_flat_terrain_is_zero():
    """A perfectly flat DEM should produce near-zero slope."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dem_data = np.full((20, 20), 5.0)
        dem_path = Path(tmpdir) / "dem.tif"
        slope_path = Path(tmpdir) / "slope.tif"

        write_test_raster(dem_path, dem_data)
        compute_slope(dem_path, slope_path)

        with rasterio.open(slope_path) as src:
            slope = src.read(1)
        valid = slope[slope != NODATA]
        assert np.allclose(valid, 0.0, atol=1e-4), f"Expected ~0 slope, got max={valid.max()}"


def test_slope_inclined_plane():
    """A linear ramp should produce consistent nonzero slope."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Ramp: 1m rise per 10m run (pixel size=10m in our test raster = 1m/cell in data)
        # We'll create a steep ramp: z increases by 1 per cell
        rows, cols = 20, 20
        dem_data = np.tile(np.arange(cols, dtype="float32"), (rows, 1))  # 1m/cell rise

        dem_path = Path(tmpdir) / "dem.tif"
        slope_path = Path(tmpdir) / "slope.tif"

        write_test_raster(dem_path, dem_data)
        compute_slope(dem_path, slope_path)

        with rasterio.open(slope_path) as src:
            slope = src.read(1)
        valid = slope[slope != NODATA]
        assert valid.mean() > 0, "Inclined plane should produce positive slope"


def test_compute_slope_output_dtype():
    with tempfile.TemporaryDirectory() as tmpdir:
        dem_path = Path(tmpdir) / "dem.tif"
        slope_path = Path(tmpdir) / "slope.tif"
        write_test_raster(dem_path, np.full((10, 10), 5.0))
        compute_slope(dem_path, slope_path)
        with rasterio.open(slope_path) as src:
            assert src.dtypes[0] == "float32"
