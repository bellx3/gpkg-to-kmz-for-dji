import pytest
from shapely.geometry import Polygon
import geopandas as gpd
from src.core.generator import parse_polygon_coords_from_gpkg_direct

def test_geometry_buffer_expansion():
    # Square polygon (10x10) around (127, 36)
    # WGS84 context: 1 degree approx 111111m
    # 0.001 degree approx 111m
    coords = [(127.0, 36.0), (127.01, 36.0), (127.01, 36.01), (127.0, 36.01), (127.0, 36.0)]
    poly = Polygon(coords)
    gdf = gpd.GeoDataFrame(index=[0], crs="EPSG:4326", geometry=[poly])
    
    # Buffer by 111m (approx 0.001 degree)
    lonlat_buffered, _ = parse_polygon_coords_from_gpkg_direct(gdf, geometry_buffer_m=111.0)
    
    # Original min/max
    # 127.0, 127.01, 36.0, 36.01
    
    lons = [float(lon) for lon, lat in lonlat_buffered]
    lats = [float(lat) for lon, lat in lonlat_buffered]
    
    assert min(lons) < 127.0
    assert max(lons) > 127.01
    assert min(lats) < 36.0
    assert max(lats) > 36.01

def test_geometry_buffer_reduction():
    coords = [(127.0, 36.0), (127.01, 36.0), (127.01, 36.01), (127.0, 36.01), (127.0, 36.0)]
    poly = Polygon(coords)
    gdf = gpd.GeoDataFrame(index=[0], crs="EPSG:4326", geometry=[poly])
    
    # Shrink by 111m
    lonlat_shrunk, _ = parse_polygon_coords_from_gpkg_direct(gdf, geometry_buffer_m=-111.0)
    
    lons = [float(lon) for lon, lat in lonlat_shrunk]
    lats = [float(lat) for lon, lat in lonlat_shrunk]
    
    assert min(lons) > 127.0
    assert max(lons) < 127.01
    assert min(lats) > 36.0
    assert max(lats) < 36.01
