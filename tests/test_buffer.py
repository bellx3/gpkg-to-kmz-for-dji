import pytest
from shapely.geometry import Polygon
from src.core.generator import polygon_coords_from_geoms

# Square polygon (approx 1.1km) around (127, 36) in WGS84.
# 1 degree approx 111111m, so 0.001 degree approx 111m.
SQUARE = Polygon([(127.0, 36.0), (127.01, 36.0), (127.01, 36.01), (127.0, 36.01), (127.0, 36.0)])


def test_geometry_buffer_expansion():
    # Buffer by 111m (approx 0.001 degree)
    lonlat_buffered = polygon_coords_from_geoms([SQUARE], 4326, geometry_buffer_m=111.0)

    lons = [float(lon) for lon, lat in lonlat_buffered]
    lats = [float(lat) for lon, lat in lonlat_buffered]

    assert min(lons) < 127.0
    assert max(lons) > 127.01
    assert min(lats) < 36.0
    assert max(lats) > 36.01


def test_geometry_buffer_reduction():
    # Shrink by 111m
    lonlat_shrunk = polygon_coords_from_geoms([SQUARE], 4326, geometry_buffer_m=-111.0)

    lons = [float(lon) for lon, lat in lonlat_shrunk]
    lats = [float(lat) for lon, lat in lonlat_shrunk]

    assert min(lons) > 127.0
    assert max(lons) < 127.01
    assert min(lats) > 36.0
    assert max(lats) < 36.01


def test_projected_crs_buffer_is_metres_not_degrees():
    # In a projected CRS the buffer must be used as-is. Dividing by 111111 here
    # would shrink a 50m buffer to under a millimetre.
    utm52n = Polygon([(300000, 3700000), (300100, 3700000), (300100, 3700100), (300000, 3700100)])
    plain = polygon_coords_from_geoms([utm52n], 32652)
    grown = polygon_coords_from_geoms([utm52n], 32652, geometry_buffer_m=50.0)

    span = lambda c: max(float(x) for x, _ in c) - min(float(x) for x, _ in c)
    # 100m square grown by 50m each side is 200m - about twice as wide.
    assert span(grown) / span(plain) == pytest.approx(2.0, abs=0.05)


def test_closes_the_ring():
    coords = polygon_coords_from_geoms([SQUARE], 4326)
    assert coords[0] == coords[-1]


def test_largest_polygon_wins():
    small = Polygon([(127.0, 36.0), (127.001, 36.0), (127.001, 36.001), (127.0, 36.001)])
    big = Polygon([(128.0, 36.0), (128.05, 36.0), (128.05, 36.05), (128.0, 36.05)])
    coords = polygon_coords_from_geoms([small, big], 4326)
    lons = [float(lon) for lon, _ in coords]
    assert min(lons) >= 128.0


def test_rejects_non_polygon_only_input():
    from shapely.geometry import Point
    with pytest.raises(ValueError):
        polygon_coords_from_geoms([Point(127, 36)], 4326)
