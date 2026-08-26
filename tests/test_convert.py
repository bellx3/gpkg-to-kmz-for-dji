"""GPKG 하나가 KMZ 가 되기까지 — 전체 경로 검증.

단위 테스트가 함수의 정확성은 보증해도 **그 함수가 실제로 불린다는 것**은 보증하지
않는다. 이 파일은 배치 진입점(`batch_process_inputs`)만 부르고 나온 KMZ 를 뜯어본다.
"""
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest
from pyproj import CRS, Transformer
from shapely.geometry import Point, Polygon

from src.core.generator import NS, batch_process_inputs

TEMPLATES = Path(__file__).resolve().parent.parent / 'src' / 'templates'

# 제주시청 부근. 좌표가 엉뚱한 데로 가면 눈으로 바로 걸린다.
JEJU_LON, JEJU_LAT = 126.531, 33.499

# KML 과 WPML **양쪽에 같은 이름으로** 들어가는 값들. 한쪽만 고치면 기체가 다른 값을 읽는다.
#
# 고도는 여기 없다. WPML 1.0.6 에서 waylineCoordinateSysParam(globalShootHeight ·
# surfaceRelativeHeight)은 template.kml 전용이고 waylines.wpml 에는 아예 없다.
# WPML 쪽 고도는 웨이포인트마다 executeHeight 로 들어간다
# (test_waypoint_heights_follow_the_override 가 본다).
SHARED_FIELDS = {
    'autoFlightSpeed': './/kml:Folder/wpml:autoFlightSpeed',
    'globalTransitionalSpeed': './/wpml:missionConfig/wpml:globalTransitionalSpeed',
    'takeOffSecurityHeight': './/wpml:missionConfig/wpml:takeOffSecurityHeight',
}

OVERRIDES = {
    'altitude': 95.0,
    'auto_flight_speed': 12,
    'global_transitional_speed': 14,
    'takeoff_security_height': 25,
    'overlap_camera_h': 75,
    'overlap_camera_w': 65,
    'drone_model': 'mavic3e',
}


@pytest.fixture
def converted(tmp_path, make_gpkg):
    """제주 부근 폴리곤 둘과 점 하나를 EPSG:5186 으로 넣고 변환한다."""
    fwd = Transformer.from_crs(CRS.from_epsg(4326), CRS.from_epsg(5186), always_xy=True)
    cx, cy = fwd.transform(JEJU_LON, JEJU_LAT)
    rows = []
    for k in range(2):
        ox, oy = cx + k * 300, cy + k * 200
        rows.append((f'제주필지_{k + 1}', f'r{k}',
                     Polygon([(ox, oy), (ox + 200, oy), (ox + 200, oy + 100), (ox, oy + 100)])))
    rows.append(('점형은건너뛴다', 'pt', Point(cx, cy)))

    src = tmp_path / 'in'
    src.mkdir()
    make_gpkg(src / 'parcels.gpkg', rows)

    out = tmp_path / 'out'
    batch_process_inputs(src, TEMPLATES / 'template.kml', TEMPLATES / 'waylines.wpml',
                         out_dir=out, input_format='gpkg', naming_field='name',
                         set_times=False, pack_kmz=True, overrides=OVERRIDES)
    return out


def read_kmz(path):
    with zipfile.ZipFile(path) as z:
        names = sorted(z.namelist())
        return names, ET.fromstring(z.read('template.kml')), ET.fromstring(z.read('waylines.wpml'))


def test_one_kmz_per_polygon_named_by_field(converted):
    # 점형은 임무가 될 수 없으므로 건너뛴다 — 폴리곤 둘만 나와야 한다.
    assert sorted(p.name for p in converted.glob('*.kmz')) == ['제주필지_1.kmz', '제주필지_2.kmz']


def test_kmz_holds_exactly_the_two_files_dji_expects(converted):
    # 이름이나 위치가 어긋나면 DJI 가 파일을 거부한다. 루트에 정확히 이 둘이어야 한다.
    for kmz in converted.glob('*.kmz'):
        names, _, _ = read_kmz(kmz)
        assert names == ['template.kml', 'waylines.wpml']


def test_no_ns0_prefix_anywhere(converted):
    # 네임스페이스 등록이 빠지면 ns0: 접두사가 붙고 기체가 받지 않는다.
    for kmz in converted.glob('*.kmz'):
        with zipfile.ZipFile(kmz) as z:
            for n in z.namelist():
                assert b'ns0:' not in z.read(n), f'{kmz.name}/{n}'


def test_coordinates_land_in_jeju_as_wgs84(converted):
    _, kml, _ = read_kmz(sorted(converted.glob('*.kmz'))[0])
    text = kml.find('.//kml:coordinates', NS).text
    pts = [p.split(',') for p in text.split() if p.strip()]
    assert len(pts) >= 4
    lons = [float(p[0]) for p in pts]
    lats = [float(p[1]) for p in pts]
    assert all(abs(x - JEJU_LON) < 0.02 for x in lons), lons[:3]
    assert all(abs(y - JEJU_LAT) < 0.02 for y in lats), lats[:3]
    # 폴리곤이 닫혀 있어야 한다
    assert pts[0] == pts[-1]


def test_overrides_reach_the_kml(converted):
    _, kml, _ = read_kmz(sorted(converted.glob('*.kmz'))[0])
    assert kml.find('.//kml:Folder/kml:Placemark/wpml:ellipsoidHeight', NS).text == '95.0'
    assert kml.find('.//kml:Folder/kml:Placemark/wpml:overlap/wpml:orthoCameraOverlapH', NS).text == '75'
    # 기체는 모델명이 아니라 DJI 정수 enum 을 읽는다
    assert kml.find('.//wpml:missionConfig/wpml:droneInfo/wpml:droneEnumValue', NS).text == '77'


@pytest.mark.parametrize('field', sorted(SHARED_FIELDS))
def test_kml_and_wpml_agree_on_shared_settings(converted, field):
    """같은 설정이 두 파일에 따로 주입된다 — 한쪽만 고치면 기체가 다른 값을 읽는다."""
    xpath = SHARED_FIELDS[field]
    _, kml, wpml = read_kmz(sorted(converted.glob('*.kmz'))[0])
    a = kml.find(xpath, NS)
    b = wpml.find(xpath, NS)
    assert a is not None, f'{field} 가 KML 에 없다'
    assert b is not None, f'{field} 가 WPML 에 없다'
    assert a.text == b.text, f'{field}: KML={a.text} WPML={b.text}'


def test_shoot_height_is_kml_only(converted):
    """고도가 KML 의 좌표계 파라미터에 들어가고, WPML 에는 그 마디가 없음을 못박는다.

    generator 는 WPML 에도 globalShootHeight 를 넣으려 시도하지만 set_text 가
    없는 마디를 조용히 넘기므로 아무 일도 일어나지 않는다. 그래서 고도가 WPML 에
    닿는 유일한 길은 executeHeight 다 — 그 길이 끊기면 여기가 아니라
    test_waypoint_heights_follow_the_override 가 잡는다.
    """
    _, kml, wpml = read_kmz(sorted(converted.glob('*.kmz'))[0])
    param = './/wpml:waylineCoordinateSysParam/wpml:globalShootHeight'
    assert kml.find(param, NS).text == '95.0'
    assert wpml.find('.//wpml:waylineCoordinateSysParam', NS) is None


def test_waypoint_heights_follow_the_override(converted):
    _, _, wpml = read_kmz(sorted(converted.glob('*.kmz'))[0])
    heights = [e.text for e in wpml.findall('.//kml:Folder/kml:Placemark/wpml:executeHeight', NS)]
    speeds = [e.text for e in wpml.findall('.//kml:Folder/kml:Placemark/wpml:waypointSpeed', NS)]
    assert heights and set(heights) == {'95.0'}
    assert speeds and set(speeds) == {'12'}
