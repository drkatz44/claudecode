"""Building detection via DBSCAN on LIDAR class-6 points."""

import numpy as np
import geopandas as gpd
from shapely.geometry import MultiPoint, Point
from pyproj import Transformer
from sklearn.cluster import DBSCAN

MIN_AREA_M2 = 10.0    # smaller = noise (shed, vehicle, etc.)
MAX_AREA_M2 = 5000.0  # larger = commercial/industrial (exclude from residential scan)
DBSCAN_EPS = 3.0      # meters
DBSCAN_MIN_SAMPLES = 10


def detect_buildings(
    class6_arr: np.ndarray,
    input_crs: str = "EPSG:3857",
    eps: float = DBSCAN_EPS,
    min_samples: int = DBSCAN_MIN_SAMPLES,
    min_area_m2: float = MIN_AREA_M2,
    max_area_m2: float = MAX_AREA_M2,
) -> gpd.GeoDataFrame:
    """Cluster class-6 LIDAR points into building footprints.

    Args:
        class6_arr: Structured numpy array of class-6 (building) points.
        input_crs: CRS of X/Y coordinates in the array.
        eps: DBSCAN epsilon (meters). Works in UTM projection.
        min_samples: DBSCAN minimum points per cluster.
        min_area_m2: Minimum convex hull area to keep (noise filter).
        max_area_m2: Maximum convex hull area to keep (warehouse filter).

    Returns:
        GeoDataFrame of building centroids (EPSG:4326) with columns:
        geometry, centroid_x_m, centroid_y_m, area_m2, point_count, cluster_id
    """
    if len(class6_arr) == 0:
        return gpd.GeoDataFrame(
            columns=["geometry", "centroid_x_m", "centroid_y_m", "area_m2", "point_count", "cluster_id"],
            crs="EPSG:4326",
        )

    # Project to UTM 19N for accurate metric distances
    if input_crs != "EPSG:32619":
        transformer = Transformer.from_crs(input_crs, "EPSG:32619", always_xy=True)
        xs, ys = transformer.transform(class6_arr["X"], class6_arr["Y"])
    else:
        xs, ys = class6_arr["X"], class6_arr["Y"]

    coords = np.column_stack([xs, ys])

    # DBSCAN clustering
    db = DBSCAN(eps=eps, min_samples=min_samples, algorithm="ball_tree", metric="euclidean")
    labels = db.fit_predict(coords)

    records = []
    for label in set(labels):
        if label == -1:
            continue  # noise

        mask = labels == label
        cluster_coords = coords[mask]

        hull = MultiPoint(cluster_coords).convex_hull
        area = hull.area

        if area < min_area_m2 or area > max_area_m2:
            continue

        centroid = hull.centroid
        records.append({
            "cluster_id": label,
            "centroid_x_m": centroid.x,
            "centroid_y_m": centroid.y,
            "area_m2": area,
            "point_count": int(mask.sum()),
        })

    if not records:
        return gpd.GeoDataFrame(
            columns=["geometry", "centroid_x_m", "centroid_y_m", "area_m2", "point_count", "cluster_id"],
            crs="EPSG:4326",
        )

    # Build GeoDataFrame in UTM 19N, then reproject to WGS84
    gdf_utm = gpd.GeoDataFrame(
        records,
        geometry=[Point(r["centroid_x_m"], r["centroid_y_m"]) for r in records],
        crs="EPSG:32619",
    )

    return gdf_utm.to_crs("EPSG:4326")
