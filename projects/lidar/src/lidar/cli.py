"""Typer CLI for LIDAR residence analysis."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="LIDAR residential density analysis for Green Hill Pond, RI")
console = Console()

# Default file paths
PROJECT_DIR = Path(__file__).parent.parent.parent.parent  # projects/lidar/
DATA_DIR = PROJECT_DIR / "data"
OUTPUT_DIR = PROJECT_DIR / "output"
QUERY_POINTS = DATA_DIR / "green_hill_query_points.geojson"

# Green Hill Pond centroid
POND_LAT = 41.3707
POND_LON = -71.6156

EPT_URL = "s3://usgs-lidar-public/RI_Statewide_1_D22/ept.json"


@app.command()
def analyze(
    query_points: Path = typer.Option(QUERY_POINTS, help="Query points GeoJSON"),
    radius_m: str = typer.Option("500,1000", help="Comma-separated buffer radii in meters"),
    lat: float = typer.Option(POND_LAT, help="Center latitude for LIDAR fetch"),
    lon: float = typer.Option(POND_LON, help="Center longitude for LIDAR fetch"),
    fetch_radius: float = typer.Option(1500, help="Radius (m) to fetch LIDAR points"),
    no_parcels: bool = typer.Option(False, "--no-parcels", help="Skip parcel cross-reference"),
    no_terrain: bool = typer.Option(False, "--no-terrain", help="Skip elevation/slope stats"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass disk cache"),
    export_csv: bool = typer.Option(True, help="Write results to output/results.csv"),
):
    """Analyze residential density around Green Hill Pond.

    Fetches LIDAR, detects buildings, cross-references parcels,
    and counts residences within each radius of each query point.
    """
    from .fetch import fetch_point_cloud, get_class
    from .buildings import detect_buildings
    from .parcels import load_parcels, join_buildings_parcels
    from .watershed import fetch_huc, huc12_bbox
    from .spatial import analyze as run_analysis

    radii = [int(r.strip()) for r in radius_m.split(",")]

    console.print(f"[bold cyan]Fetching LIDAR point cloud[/] (radius={fetch_radius}m)...")
    arr = fetch_point_cloud(lat, lon, radius_m=fetch_radius, ept_url=EPT_URL, use_cache=not no_cache)
    console.print(f"  Retrieved [green]{len(arr):,}[/] points")

    class6 = get_class(arr, 6)
    console.print(f"  Class 6 (buildings): [green]{len(class6):,}[/] points")

    console.print("[bold cyan]Detecting buildings...[/]")
    buildings = detect_buildings(class6)
    console.print(f"  Detected [green]{len(buildings)}[/] building clusters")

    # HUC12 watershed
    watershed = None
    console.print("[bold cyan]Fetching HUC12 watershed...[/]")
    try:
        watershed = fetch_huc(lat, lon, use_cache=not no_cache)
        name = watershed.iloc[0].get("name", "unknown") if not watershed.empty else "none"
        area = watershed.iloc[0].get("areasqkm", 0) if not watershed.empty else 0
        console.print(f"  Watershed: [green]{name}[/] ({area:.1f} km²)")
    except Exception as e:
        console.print(f"  [yellow]Warning:[/] Could not fetch HUC12: {e}")

    # Parcel join
    if not no_parcels:
        console.print("[bold cyan]Loading parcel data...[/]")
        # Derive bbox from fetch radius
        from pyproj import Transformer
        t = Transformer.from_crs("EPSG:4326", "EPSG:4326", always_xy=True)
        deg_per_m = 1 / 111_320
        bbox = (
            lon - fetch_radius * deg_per_m,
            lat - fetch_radius * deg_per_m,
            lon + fetch_radius * deg_per_m,
            lat + fetch_radius * deg_per_m,
        )
        try:
            parcels = load_parcels(bbox, use_cache=not no_cache)
            buildings = join_buildings_parcels(buildings, parcels)
            n_res = buildings.get("is_residential", None)
            if n_res is not None:
                console.print(f"  Residential buildings: [green]{n_res.sum()}[/] / {len(buildings)}")
        except Exception as e:
            console.print(f"  [yellow]Warning:[/] Parcel load failed: {e}")

    # Terrain stats
    dem_path = OUTPUT_DIR / "dem_bare_earth.tif"
    slope_path = OUTPUT_DIR / "slope.tif"
    flow_acc_path = OUTPUT_DIR / "flow_acc.tif"
    if no_terrain or not dem_path.exists():
        dem_path = slope_path = flow_acc_path = None

    console.print("[bold cyan]Running spatial analysis...[/]")
    df = run_analysis(
        query_points_path=query_points,
        buildings=buildings,
        watershed=watershed,
        dem_path=dem_path,
        slope_path=slope_path,
        flow_acc_path=flow_acc_path,
        radii=radii,
    )

    # Print results table
    table = Table(title="Green Hill Pond — Residential Density", show_lines=True)
    table.add_column("Point", style="bold")
    for r in radii:
        table.add_column(f"Res {r}m", justify="right")
        table.add_column(f"Total {r}m", justify="right")
    table.add_column("Res HUC12", justify="right")
    table.add_column("Elev (m)", justify="right")
    table.add_column("Slope (%)", justify="right")

    for _, row in df.iterrows():
        cols = [str(row["label"])]
        for r in radii:
            cols += [str(row.get(f"res_{r}m", "-")), str(row.get(f"total_{r}m", "-"))]
        cols.append(str(row.get("res_huc12", "-")))
        elev = row.get("mean_elev_m")
        slope = row.get("mean_slope_pct")
        cols.append(f"{elev:.1f}" if elev is not None else "-")
        cols.append(f"{slope:.1f}" if slope is not None else "-")
        table.add_row(*cols)

    console.print(table)

    if export_csv:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_csv = OUTPUT_DIR / "results.csv"
        df.to_csv(out_csv, index=False)
        console.print(f"\n[dim]Results saved to {out_csv}[/]")


@app.command()
def terrain(
    lat: float = typer.Option(POND_LAT, help="Center latitude"),
    lon: float = typer.Option(POND_LON, help="Center longitude"),
    radius_m: float = typer.Option(1500, help="Fetch radius in meters"),
    resolution: float = typer.Option(0.3, help="Raster resolution in meters"),
    no_flow: bool = typer.Option(False, "--no-flow", help="Skip flow direction/accumulation"),
):
    """Build DEM, DSM, CHM, slope, and flow direction rasters.

    Outputs to projects/lidar/output/
    """
    from .terrain import build_dem, build_dsm, build_chm, compute_slope, compute_flow, fill_nodata

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    console.print(f"[bold cyan]Building DEM[/] (class 2, {resolution}m resolution)...")
    dem_path = build_dem(lat, lon, radius_m, OUTPUT_DIR / "dem_bare_earth.tif",
                         ept_url=EPT_URL, resolution=resolution)
    fill_nodata(dem_path)
    console.print(f"  [green]✓[/] {dem_path}")

    console.print("[bold cyan]Building DSM[/] (class 2–5)...")
    dsm_path = build_dsm(lat, lon, radius_m, OUTPUT_DIR / "dsm_with_trees.tif",
                         ept_url=EPT_URL, resolution=resolution)
    fill_nodata(dsm_path)
    console.print(f"  [green]✓[/] {dsm_path}")

    console.print("[bold cyan]Computing CHM[/] (DSM - DEM)...")
    chm_path = build_chm(dem_path, dsm_path, OUTPUT_DIR / "chm.tif")
    console.print(f"  [green]✓[/] {chm_path}")

    console.print("[bold cyan]Computing slope[/]...")
    slope_path = compute_slope(dem_path, OUTPUT_DIR / "slope.tif")
    console.print(f"  [green]✓[/] {slope_path}")

    if not no_flow:
        console.print("[bold cyan]Computing flow direction + accumulation[/]...")
        flow_paths = compute_flow(dem_path, OUTPUT_DIR)
        for name, path in flow_paths.items():
            console.print(f"  [green]✓[/] {name}: {path}")

    console.print("\n[bold green]Terrain analysis complete.[/]")


@app.command()
def map(
    query_points: Path = typer.Option(QUERY_POINTS, help="Query points GeoJSON"),
    lat: float = typer.Option(POND_LAT, help="Center latitude for LIDAR fetch"),
    lon: float = typer.Option(POND_LON, help="Center longitude for LIDAR fetch"),
    fetch_radius: float = typer.Option(1500, help="Radius (m) to fetch LIDAR points"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass disk cache"),
):
    """Generate Folium interactive HTML map.

    Requires buildings + analysis results (run 'analyze' first).
    """
    from .fetch import fetch_point_cloud, get_class
    from .buildings import detect_buildings
    from .parcels import load_parcels, join_buildings_parcels
    from .watershed import fetch_huc
    from .spatial import analyze as run_analysis, load_query_points
    from .viz import make_map

    console.print("[bold cyan]Loading data for map...[/]")
    arr = fetch_point_cloud(lat, lon, radius_m=fetch_radius, ept_url=EPT_URL, use_cache=not no_cache)
    buildings = detect_buildings(get_class(arr, 6))

    watershed = None
    try:
        watershed = fetch_huc(lat, lon, use_cache=not no_cache)
    except Exception:
        pass

    try:
        deg_per_m = 1 / 111_320
        bbox = (
            lon - fetch_radius * deg_per_m, lat - fetch_radius * deg_per_m,
            lon + fetch_radius * deg_per_m, lat + fetch_radius * deg_per_m,
        )
        parcels = load_parcels(bbox, use_cache=not no_cache)
        buildings = join_buildings_parcels(buildings, parcels)
    except Exception as e:
        console.print(f"  [yellow]Warning:[/] Parcel load failed: {e}")

    dem_path = OUTPUT_DIR / "dem_bare_earth.tif"
    slope_path = OUTPUT_DIR / "slope.tif"
    flow_acc_path = OUTPUT_DIR / "flow_acc.tif"
    if not dem_path.exists():
        dem_path = slope_path = flow_acc_path = None

    df = run_analysis(
        query_points_path=query_points,
        buildings=buildings,
        watershed=watershed,
        dem_path=dem_path,
        slope_path=slope_path,
        flow_acc_path=flow_acc_path,
    )

    qp_gdf = load_query_points(query_points)
    out_html = OUTPUT_DIR / "green_hill_map.html"

    console.print("[bold cyan]Generating map...[/]")
    make_map(qp_gdf, buildings, watershed, df, out_html)
    console.print(f"  [green]✓[/] {out_html}")


@app.command()
def export(
    query_points: Path = typer.Option(QUERY_POINTS, help="Query points GeoJSON"),
    lat: float = typer.Option(POND_LAT, help="Center latitude"),
    lon: float = typer.Option(POND_LON, help="Center longitude"),
    fetch_radius: float = typer.Option(1500, help="Fetch radius in meters"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass disk cache"),
):
    """Export buildings GeoJSON + results CSV to output/."""
    from .fetch import fetch_point_cloud, get_class
    from .buildings import detect_buildings
    from .parcels import load_parcels, join_buildings_parcels
    from .watershed import fetch_huc
    from .spatial import analyze as run_analysis

    arr = fetch_point_cloud(lat, lon, radius_m=fetch_radius, ept_url=EPT_URL, use_cache=not no_cache)
    buildings = detect_buildings(get_class(arr, 6))

    watershed = None
    try:
        watershed = fetch_huc(lat, lon, use_cache=not no_cache)
    except Exception:
        pass

    try:
        deg_per_m = 1 / 111_320
        bbox = (
            lon - fetch_radius * deg_per_m, lat - fetch_radius * deg_per_m,
            lon + fetch_radius * deg_per_m, lat + fetch_radius * deg_per_m,
        )
        parcels = load_parcels(bbox, use_cache=not no_cache)
        buildings = join_buildings_parcels(buildings, parcels)
    except Exception as e:
        console.print(f"[yellow]Warning:[/] {e}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    buildings_out = OUTPUT_DIR / "buildings.geojson"
    buildings.to_file(buildings_out, driver="GeoJSON")
    console.print(f"[green]✓[/] Buildings: {buildings_out} ({len(buildings)} records)")

    dem_path = OUTPUT_DIR / "dem_bare_earth.tif"
    slope_path = OUTPUT_DIR / "slope.tif"
    flow_acc_path = OUTPUT_DIR / "flow_acc.tif"
    for p in [dem_path, slope_path, flow_acc_path]:
        if not p.exists():
            p = None

    df = run_analysis(
        query_points_path=query_points,
        buildings=buildings,
        watershed=watershed,
        dem_path=dem_path,
        slope_path=slope_path,
        flow_acc_path=flow_acc_path,
    )

    results_out = OUTPUT_DIR / "results.csv"
    df.to_csv(results_out, index=False)
    console.print(f"[green]✓[/] Results: {results_out}")


if __name__ == "__main__":
    app()
