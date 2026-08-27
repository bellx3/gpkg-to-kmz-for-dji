"""inspector 의 지리 대조 검증 — roadmap Task 4 에서 코드로 확정한 사실의 그물.

이 도구가 만드는 KMZ 는 폴리곤을 template.kml 에만 주입하고, waylines.wpml 의
실행 웨이포인트는 원 템플릿 현장 것이 그대로 실린다. inspector 가 그 간극을
실제로 재고 경고하는지를 본다.
"""
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from pyproj import CRS, Transformer
from shapely.geometry import Polygon

from src.core import inspector
from src.core.generator import batch_process_inputs

TEMPLATES = Path(__file__).resolve().parent.parent / 'src' / 'templates'

# 원 템플릿 현장(제주 서부, 33.4717N 126.3910E)에서 충분히 먼 임무 지점
JEJU_CITY = (126.531, 33.499)


@pytest.fixture
def kmz(tmp_path, make_gpkg):
    fwd = Transformer.from_crs(CRS.from_epsg(4326), CRS.from_epsg(5186), always_xy=True)
    cx, cy = fwd.transform(*JEJU_CITY)
    src = tmp_path / 'in'
    src.mkdir()
    make_gpkg(src / 'p.gpkg', [
        ('시험필지', 'r0', Polygon([(cx, cy), (cx + 200, cy), (cx + 200, cy + 100), (cx, cy + 100)])),
    ])
    out = tmp_path / 'out'
    batch_process_inputs(src, TEMPLATES / 'template.kml', TEMPLATES / 'waylines.wpml',
                         out_dir=out, input_format='gpkg', naming_field='name',
                         set_times=False, pack_kmz=True,
                         overrides={'altitude': 90.0, 'drone_model': 'mavic3e'})
    return next(out.glob('*.kmz'))


def test_geo_check_measures_the_gap(kmz):
    kml_root, wpml_root, names = inspector.load_kmz(kmz)
    assert names == ['template.kml', 'waylines.wpml']

    geo = inspector.geo_check(kml_root, wpml_root)
    # 웨이포인트는 원 템플릿의 26개가 그대로 실린다
    assert geo['waypoints'] == 26
    # 폴리곤 중심은 우리가 넣은 임무 지점 근처
    pc = geo['polygon_centroid']
    assert abs(pc[0] - JEJU_CITY[0]) < 0.01 and abs(pc[1] - JEJU_CITY[1]) < 0.01
    # 웨이포인트 중심은 원 현장 근처 — 즉 폴리곤과 킬로미터 단위로 떨어져 있다
    wc = geo['waypoint_centroid']
    assert abs(wc[0] - 126.392) < 0.01 and abs(wc[1] - 33.473) < 0.01
    assert geo['distance_m'] > 5000


def test_inspect_prints_values_and_warns(kmz, capsys):
    geo = inspector.inspect(kmz)
    out = capsys.readouterr().out
    # 기존 역할: KML/WPML 값 나란히
    assert 'KML ellipsoidHeight: 90.0' in out
    assert 'WPML executeHeight count: 26' in out
    # 새 역할: 지리 간극 경고
    assert '경고' in out and 'Pilot 2' in out
    assert geo['distance_m'] > inspector.GEO_WARN_DISTANCE_M


def test_distance_m_sanity():
    # 제주에서 경도 0.01도 ≈ 928m (위도 33.5 기준) — 근사식이 그 수준을 재는가
    d = inspector.distance_m((126.50, 33.50), (126.51, 33.50))
    assert 900 < d < 960


def test_no_warning_when_mission_is_at_template_site(tmp_path):
    # 폴리곤이 원 현장 그 자리라면 간극이 작아야 한다 — 경고 문턱의 반대편 검증
    kml_root, wpml_root, _ = inspector.load_kmz(_kmz_at_template_site(tmp_path))
    geo = inspector.geo_check(kml_root, wpml_root)
    assert geo['distance_m'] < inspector.GEO_WARN_DISTANCE_M


def _kmz_at_template_site(tmp_path):
    """원 템플릿 웨이포인트 자리에 폴리곤을 놓은 KMZ."""
    from src.core.generator import generate_kml_bytes, make_kmz_from_bytes
    wps_root = ET.parse(TEMPLATES / 'waylines.wpml').getroot()
    pts = inspector.waypoint_points(wps_root)
    lons = [p[0] for p in pts]; lats = [p[1] for p in pts]
    ring = [(min(lons), min(lats)), (max(lons), min(lats)),
            (max(lons), max(lats)), (min(lons), max(lats)), (min(lons), min(lats))]
    lonlat = [(f'{x:.9f}', f'{y:.9f}') for x, y in ring]
    kml_bytes = generate_kml_bytes(TEMPLATES / 'template.kml', lonlat, set_times=False)
    out = tmp_path / 'site.kmz'
    make_kmz_from_bytes(kml_bytes, TEMPLATES / 'waylines.wpml', out)
    return out
