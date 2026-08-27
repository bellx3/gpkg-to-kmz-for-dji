"""생성된 KMZ 의 내부 값을 검증하는 CLI.

같은 설정이 template.kml 과 waylines.wpml 에 따로 주입되므로(한쪽만 고치면 기체가
서로 다른 값을 읽는다) 두 파일의 같은 필드를 나란히 출력해 불일치를 눈으로 잡는다.

지리 대조도 함께 한다: 이 도구가 만드는 KMZ 에서 폴리곤은 template.kml 에만
주입되고, waylines.wpml 의 실행 웨이포인트는 **원 템플릿 현장의 것이 그대로**
실린다. 그래서 웨이포인트가 임무 폴리곤에서 멀면 여기서 크게 경고한다 —
이 KMZ 는 DJI Pilot 2 로 불러와 경로를 재생성해 쓰는 물건이며(templateType
mapping2d), 웨이라인을 직접 실행하면 원 현장을 비행한다. docs/roadmap.md Task 4.

사용:  python src/core/inspector.py output/미션.kmz
"""
import math
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

NS = {'kml': 'http://www.opengis.net/kml/2.2', 'wpml': 'http://www.dji.com/wpmz/1.0.6'}

# (표시 이름, XPath) — KML/WPML 나란히 비교할 필드들
KML_FIELDS = [
    ('KML ellipsoidHeight', './/kml:Folder/kml:Placemark/wpml:ellipsoidHeight'),
    ('KML height', './/kml:Folder/kml:Placemark/wpml:height'),
    ('KML globalShootHeight', './/kml:Folder/wpml:waylineCoordinateSysParam/wpml:globalShootHeight'),
    ('KML surfaceRelativeHeight', './/kml:Folder/wpml:waylineCoordinateSysParam/wpml:surfaceRelativeHeight'),
    ('KML margin', './/kml:Folder/kml:Placemark/wpml:margin'),
    ('KML overlap camera H', './/kml:Folder/kml:Placemark/wpml:overlap/wpml:orthoCameraOverlapH'),
    ('KML overlap camera W', './/kml:Folder/kml:Placemark/wpml:overlap/wpml:orthoCameraOverlapW'),
    ('KML overlap lidar H', './/kml:Folder/kml:Placemark/wpml:overlap/wpml:orthoLidarOverlapH'),
    ('KML overlap lidar W', './/kml:Folder/kml:Placemark/wpml:overlap/wpml:orthoLidarOverlapW'),
    ('KML autoFlightSpeed', './/kml:Folder/wpml:autoFlightSpeed'),
    ('KML globalTransitionalSpeed', './/wpml:missionConfig/wpml:globalTransitionalSpeed'),
    ('KML takeOffSecurityHeight', './/wpml:missionConfig/wpml:takeOffSecurityHeight'),
]
WPML_FIELDS = [
    ('WPML globalShootHeight', './/wpml:waylineCoordinateSysParam/wpml:globalShootHeight'),
    ('WPML surfaceRelativeHeight', './/wpml:waylineCoordinateSysParam/wpml:surfaceRelativeHeight'),
    ('WPML autoFlightSpeed', './/wpml:autoFlightSpeed'),
    ('WPML globalTransitionalSpeed', './/wpml:missionConfig/wpml:globalTransitionalSpeed'),
    ('WPML takeOffSecurityHeight', './/wpml:missionConfig/wpml:takeOffSecurityHeight'),
]

# 이보다 멀면 "웨이라인이 임무를 가리키지 않는다"로 판정한다.
GEO_WARN_DISTANCE_M = 200.0


def load_kmz(path):
    """KMZ 에서 (kml_root, wpml_root, 내부 파일명들) 을 꺼낸다."""
    with zipfile.ZipFile(path, 'r') as z:
        names = z.namelist()
        kml_root = ET.fromstring(z.read('template.kml'))
        wpml_root = ET.fromstring(z.read('waylines.wpml'))
    return kml_root, wpml_root, names


def _centroid(points):
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    return (sum(lons) / len(lons), sum(lats) / len(lats))


def polygon_points(kml_root):
    """template.kml 의 임무 폴리곤 꼭짓점 [(lon, lat), ...]"""
    el = kml_root.find('.//kml:coordinates', NS)
    if el is None or not el.text:
        return []
    pts = []
    for tok in el.text.split():
        parts = tok.split(',')
        if len(parts) >= 2:
            pts.append((float(parts[0]), float(parts[1])))
    return pts


def waypoint_points(wpml_root):
    """waylines.wpml 의 실행 웨이포인트 [(lon, lat), ...]"""
    pts = []
    for pm in wpml_root.findall('.//kml:Folder/kml:Placemark', NS):
        el = pm.find('.//kml:Point/kml:coordinates', NS)
        if el is not None and el.text:
            parts = el.text.strip().split(',')
            if len(parts) >= 2:
                pts.append((float(parts[0]), float(parts[1])))
    return pts


def distance_m(a, b):
    """(lon, lat) 두 점의 근사 거리(m). 짧은 거리용 equirectangular."""
    mean_lat = math.radians((a[1] + b[1]) / 2)
    dx = (a[0] - b[0]) * 111_320 * math.cos(mean_lat)
    dy = (a[1] - b[1]) * 111_320
    return math.hypot(dx, dy)


def geo_check(kml_root, wpml_root) -> dict:
    """임무 폴리곤과 실행 웨이포인트의 지리 대조."""
    poly = polygon_points(kml_root)
    wps = waypoint_points(wpml_root)
    out = {'polygon_vertices': len(poly), 'waypoints': len(wps),
           'polygon_centroid': None, 'waypoint_centroid': None, 'distance_m': None}
    if poly and wps:
        pc, wc = _centroid(poly), _centroid(wps)
        out['polygon_centroid'] = pc
        out['waypoint_centroid'] = wc
        out['distance_m'] = distance_m(pc, wc)
    return out


def _find_text(root, xpath):
    el = root.find(xpath, NS)
    return el.text if el is not None else None


def inspect(path, out=print):
    path = Path(path)
    kml_root, wpml_root, names = load_kmz(path)

    out(f'KMZ: {path.name}')
    out(f'KMZ contents: {names}')
    for label, xpath in KML_FIELDS:
        out(f'{label}: {_find_text(kml_root, xpath)}')
    for label, xpath in WPML_FIELDS:
        out(f'{label}: {_find_text(wpml_root, xpath)}')

    ex_vals = [el.text for el in wpml_root.findall('.//kml:Folder/kml:Placemark/wpml:executeHeight', NS)]
    out(f'WPML executeHeight count: {len(ex_vals)}')
    out(f'WPML executeHeight sample: {ex_vals[:5]}')

    geo = geo_check(kml_root, wpml_root)
    out(f"GEO polygon vertices: {geo['polygon_vertices']}  centroid: {geo['polygon_centroid']}")
    out(f"GEO waypoints: {geo['waypoints']}  centroid: {geo['waypoint_centroid']}")
    if geo['distance_m'] is not None:
        out(f"GEO centroid distance: {geo['distance_m']:,.0f} m")
        if geo['distance_m'] > GEO_WARN_DISTANCE_M:
            out('!! 경고: 실행 웨이포인트(waylines.wpml)가 임무 폴리곤에서 '
                f"{geo['distance_m'] / 1000:.1f} km 떨어져 있습니다.")
            out('!!       이 KMZ 는 DJI Pilot 2 로 불러와 경로를 재생성해 쓰는 파일입니다.')
            out('!!       웨이라인을 직접 실행하면 임무 폴리곤이 아니라 원 템플릿 현장을 비행합니다.')
    return geo


if __name__ == '__main__':
    p = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('output/sample.kmz')
    inspect(p)
