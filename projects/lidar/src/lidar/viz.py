"""Folium interactive map with toggleable layers."""

from pathlib import Path
from typing import Optional

import folium
from folium import plugins
import geopandas as gpd
import pandas as pd
import numpy as np

# Green Hill Pond approximate centroid
POND_CENTER = (41.3707, -71.6156)
DEFAULT_ZOOM = 14


def make_map(
    query_points: gpd.GeoDataFrame,
    buildings: gpd.GeoDataFrame,
    watershed: Optional[gpd.GeoDataFrame],
    results_df: pd.DataFrame,
    out_path: Path,
    pond_geojson: Optional[dict] = None,
    radii: list[int] = (500, 1000),
) -> Path:
    """Build Folium HTML map with all analysis layers.

    Args:
        query_points: GeoDataFrame of query points.
        buildings: GeoDataFrame of building centroids with is_residential.
        watershed: GeoDataFrame of HUC12 polygon(s).
        results_df: DataFrame output from spatial.analyze().
        out_path: Output HTML path.
        pond_geojson: Optional GeoJSON dict of pond boundary.
        radii: Buffer radii to draw circles for.

    Returns:
        Path to generated HTML file.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    m = folium.Map(location=POND_CENTER, zoom_start=DEFAULT_ZOOM, tiles="OpenStreetMap")

    # --- Pond outline ---
    if pond_geojson:
        pond_layer = folium.FeatureGroup(name="Green Hill Pond", show=True)
        folium.GeoJson(
            pond_geojson,
            style_function=lambda _: {
                "fillColor": "#4fc3f7",
                "color": "#0277bd",
                "weight": 2,
                "fillOpacity": 0.3,
            },
            tooltip="Green Hill Pond",
        ).add_to(pond_layer)
        pond_layer.add_to(m)

    # --- HUC12 watershed boundary ---
    if watershed is not None and not watershed.empty:
        ws_layer = folium.FeatureGroup(name="HUC12 Watershed", show=True)
        name = watershed.iloc[0].get("name", "HUC12 Watershed")
        folium.GeoJson(
            watershed.__geo_interface__,
            style_function=lambda _: {
                "fillColor": "none",
                "color": "#2e7d32",
                "weight": 3,
                "dashArray": "8 4",
            },
            tooltip=name,
        ).add_to(ws_layer)
        ws_layer.add_to(m)

    # --- Building footprints ---
    res_layer = folium.FeatureGroup(name="Residential Buildings", show=True)
    other_layer = folium.FeatureGroup(name="Non-Residential Buildings", show=False)

    for _, bldg in buildings.iterrows():
        geom = bldg.geometry
        lat, lon = geom.y, geom.x
        is_res = bldg.get("is_residential")

        area = bldg.get("area_m2", 0)
        tooltip = (
            f"{'Residential' if is_res else 'Other'} | "
            f"Area: {area:.0f} m²"
        )

        if is_res:
            folium.CircleMarker(
                [lat, lon], radius=4, color="#c62828", fill=True,
                fill_color="#ef5350", fill_opacity=0.7, tooltip=tooltip,
            ).add_to(res_layer)
        else:
            folium.CircleMarker(
                [lat, lon], radius=3, color="#546e7a", fill=True,
                fill_color="#90a4ae", fill_opacity=0.5, tooltip=tooltip,
            ).add_to(other_layer)

    res_layer.add_to(m)
    other_layer.add_to(m)

    # --- Query points with buffer circles and popups ---
    for _, row in results_df.iterrows():
        lat = row["lat"]
        lon = row["lon"]
        label = row.get("label", "")

        # Popup content
        popup_lines = [
            f"<b>{label}</b>",
            f"Lat: {lat:.5f}, Lon: {lon:.5f}",
        ]
        for r in radii:
            popup_lines.append(
                f"{r}m: {row.get(f'res_{r}m', '?')} residential / "
                f"{row.get(f'total_{r}m', '?')} total"
            )
        popup_lines.append(f"Watershed: {row.get('res_huc12', '?')} res / {row.get('total_huc12', '?')} total")
        if row.get("mean_elev_m") is not None:
            popup_lines.append(f"Mean elev: {row['mean_elev_m']:.1f} m NAVD88")
            popup_lines.append(f"Mean slope: {row['mean_slope_pct']:.1f}%")
        popup_html = "<br>".join(popup_lines)

        # Buffer circles (500m outer, 1000m translucent)
        circle_layer = folium.FeatureGroup(name=f"Buffers — {label}", show=False)
        for r, opacity in zip(sorted(radii), [0.15, 0.08]):
            folium.Circle(
                [lat, lon], radius=r, color="#e65100", fill=True,
                fill_color="#ff6d00", fill_opacity=opacity,
                weight=1, tooltip=f"{r}m buffer",
            ).add_to(circle_layer)
        circle_layer.add_to(m)

        # Query point marker
        points_layer = folium.FeatureGroup(name="Query Points", show=True)
        folium.Marker(
            [lat, lon],
            popup=folium.Popup(popup_html, max_width=280),
            tooltip=label,
            icon=folium.Icon(color="blue", icon="info-sign"),
        ).add_to(points_layer)

    points_layer.add_to(m)

    # --- Layer control ---
    folium.LayerControl(collapsed=False).add_to(m)

    m.save(str(out_path))
    return out_path
