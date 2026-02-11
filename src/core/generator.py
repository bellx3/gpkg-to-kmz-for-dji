import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import time
import re
from typing import List, Tuple, Optional, Dict
from . import enums as dji_enums

NS = {
    'kml': 'http://www.opengis.net/kml/2.2',
    'wpml': 'http://www.dji.com/wpmz/1.0.6',
}
ET.register_namespace('', NS['kml'])
ET.register_namespace('wpml', NS['wpml'])

# 파일명 안전화 함수 (사용 위치보다 먼저 정의되어야 합니다)
def sanitize_filename(name: str) -> str:
    if name is None:
        return ''
    # Windows 예약문자 제거
    name = re.sub(r'[<>:"/\\|?*]', '_', str(name))
    # 제어문자 제거
    name = re.sub(r'[\r\n\t]+', ' ', name)
    # 앞뒤 공백 제거
    name = name.strip()
    # 끝의 점/공백 제거(Windows 파일명 제약)
    name = name.rstrip('. ')
    if not name:
        return ''
    # 길이 제한(과도한 길이 방지)
    if len(name) > 200:
        name = name[:200]
    return name

# 파일명 안전화 함수 (사용 위치보다 먼저 정의되어야 합니다)


# -----------------------------
# KML 파싱 (폴리곤 좌표)
# -----------------------------

def parse_polygon_coords_from_kml(src_kml_path: Path) -> List[Tuple[str, str]]:
    tree = ET.parse(src_kml_path)
    root = tree.getroot()

    # 가장 일반적인 좌표 경로 탐색
    coords_elem = root.find('.//kml:Polygon/kml:outerBoundaryIs/kml:LinearRing/kml:coordinates', NS)
    if coords_elem is None:
        coords_elem = root.find('.//kml:LinearRing/kml:coordinates', NS)
    if coords_elem is None:
        coords_elem = root.find('.//kml:coordinates', NS)
    if coords_elem is None or (coords_elem.text is None):
        raise ValueError('소스 KML에서 <coordinates>를 찾지 못했습니다.')

    raw = coords_elem.text.strip()
    tokens = [tok for tok in re.split(r'\s+', raw) if tok]
    lonlat = []
    for tok in tokens:
        parts = tok.split(',')
        if len(parts) < 2:
            continue
        lon = parts[0].strip()
        lat = parts[1].strip()
        lonlat.append((lon, lat))

    if not lonlat:
        raise ValueError('좌표 파싱 실패')

    # 폴리곤 폐합 보장 (첫 좌표와 마지막 좌표 동일하게)
    if lonlat[0] != lonlat[-1]:
        lonlat.append(lonlat[0])

    return lonlat


# -----------------------------
# KML에서 이름 필드(DYNM 등) 파싱
# -----------------------------

def parse_name_value_from_kml(src_kml_path: Path, naming_field: Optional[str] = 'DYNM') -> str:
    tree = ET.parse(src_kml_path)
    root = tree.getroot()

    target_field = naming_field or 'DYNM'
    dynm = None

    # 네임스페이스 탐색
    for sd in root.findall('.//kml:SimpleData', NS):
        if sd.get('name') == target_field:
            val = (sd.text or '').strip()
            if val:
                dynm = val
                break

    # 폴백: 네임스페이스 무시 탐색
    if dynm is None:
        for elem in root.iter():
            tag = elem.tag.split('}')[-1]
            if tag == 'SimpleData' and elem.get('name') == target_field:
                val = (elem.text or '').strip()
                if val:
                    dynm = val
                    break

    # 폴백: 파일 이름 사용
    if dynm is None:
        dynm = src_kml_path.stem

    # 파일명 안전화
    dynm_sanitized = sanitize_filename(str(dynm))
    if not dynm_sanitized:
        dynm_sanitized = src_kml_path.stem
    return dynm_sanitized


# -----------------------------
# GPKG 파싱 (GeoPandas/pyogrio 권장)
# -----------------------------
def read_gpkg_to_gdf(src_gpkg_path: Path, layer: Optional[str] = None):
    try:
        import geopandas as gpd
    except ImportError:
        raise ImportError("GeoPackage 파싱을 위해 GeoPandas가 필요합니다. 'pip install geopandas pyogrio shapely' 설치 후 다시 시도하세요.")

    gdf = None
    read_err = None
    try:
        gdf = gpd.read_file(str(src_gpkg_path), layer=layer)
    except Exception as e:
        read_err = e
        try:
            import pyogrio
            gdf = pyogrio.read_dataframe(str(src_gpkg_path), layer=layer)
        except Exception as e2:
            raise RuntimeError(f"GPKG 읽기 실패: {read_err} / pyogrio 실패: {e2}")
    
    if gdf is None or gdf.empty:
        raise ValueError('GPKG 레이어가 비어 있거나 읽을 수 없습니다.')
    return gdf


def parse_polygon_coords_from_gpkg(src_gpkg_path: Path, layer: Optional[str] = None,
                                   to_epsg: int = 4326,
                                   simplify_tolerance: float = 0.0) -> Tuple[List[Tuple[str, str]], 'object']:
    """
    GPKG 파일을 읽어 WGS84 좌표 리스트를 반환하는 래퍼 함수.
    """
    gdf = read_gpkg_to_gdf(src_gpkg_path, layer=layer)
    return parse_polygon_coords_from_gpkg_direct(gdf, to_epsg=to_epsg, simplify_tolerance=simplify_tolerance)


def parse_polygon_coords_from_gpkg_direct(gdf, to_epsg: int = 4326,
                                          simplify_tolerance: float = 0.0) -> Tuple[List[Tuple[str, str]], 'object']:
    """
    이미 로드된 GeoDataFrame에서 폴리곤을 추출하고 변환/단순화 수행.
    """
    # 1. 폴리곤 계열 선택 및 병합
    geom_type = gdf.geometry.geom_type
    gdf = gdf[geom_type.isin(['Polygon', 'MultiPolygon'])].copy()
    if gdf.empty:
        raise ValueError('폴리곤/멀티폴리곤 지오메트리가 없습니다.')

    try:
        from shapely.ops import unary_union as sh_unary_union
        u = sh_unary_union(gdf.geometry)
    except Exception:
        u = gdf.geometry.unary_union

    from shapely.geometry import Polygon, MultiPolygon
    if u.geom_type == 'MultiPolygon':
        poly = max(u.geoms, key=lambda p: p.area)
    elif u.geom_type == 'Polygon':
        poly = u
    else:
        raise ValueError(f'지원하지 않는 지오메트리 타입: {u.geom_type}')

    # 2. 지오메트리 단순화 (Simplify)
    if simplify_tolerance > 0:
        actual_tol = simplify_tolerance
        # 만약 지리 좌표계(도 단위)라면 미터 단위 오차를 도 단위로 대략적 변환
        if gdf.crs and gdf.crs.is_geographic:
            actual_tol = simplify_tolerance / 111111.0
        poly = poly.simplify(actual_tol, preserve_topology=True)

    # 3. 좌표계 변환 (WGS84로 변환하기 위해 임시 GeoSeries 사용)
    import geopandas as gpd
    from shapely.geometry import mapping, shape
    gs = gpd.GeoSeries([poly], crs=gdf.crs)
    if gdf.crs and gdf.crs.to_epsg() != to_epsg:
        gs = gs.to_crs(epsg=to_epsg)
    
    final_poly = gs.iloc[0]
    coords = list(final_poly.exterior.coords)
    lonlat = [(f"{x:.9f}", f"{y:.9f}") for (x, y) in coords]
    
    # 폴리곤 폐합 보장
    if lonlat[0] != lonlat[-1]:
        lonlat.append(lonlat[0])
        
    return lonlat, gdf


def get_naming_value_from_gdf(gdf, naming_field: Optional[str], fallback_stem: str) -> str:
    if naming_field and naming_field in gdf.columns:
        series = gdf[naming_field].dropna()
        if len(series) > 0:
            val = str(series.iloc[0])
            sanitized = sanitize_filename(val)
            if sanitized:
                return sanitized
    return fallback_stem


# -----------------------------
# 템플릿 오버라이드
# -----------------------------

def apply_template_overrides(root: ET.Element, overrides: Optional[Dict] = None):
    if not overrides:
        return

    def set_text(xpath: str, value):
        if value is None:
            return
        elem = root.find(xpath, NS)
        if elem is not None:
            elem.text = str(value)

    altitude = overrides.get('altitude')
    shoot_height = overrides.get('shoot_height', altitude)
    margin = overrides.get('margin')
    oc_h = overrides.get('overlap_camera_h')
    oc_w = overrides.get('overlap_camera_w')
    ol_h = overrides.get('overlap_lidar_h')
    ol_w = overrides.get('overlap_lidar_w')
    auto_speed = overrides.get('auto_flight_speed')
    global_speed = overrides.get('global_transitional_speed')
    takeoff_sec_h = overrides.get('takeoff_security_height')

    # 고도 관련
    set_text('.//kml:Folder/kml:Placemark/wpml:ellipsoidHeight', altitude)
    set_text('.//kml:Folder/kml:Placemark/wpml:height', altitude)
    set_text('.//kml:Folder/wpml:waylineCoordinateSysParam/wpml:globalShootHeight', shoot_height)
    # surfaceRelativeHeight도 동일하게 반영 (일부 뷰어/장비에서 이 값이 참조됨)
    set_text('.//kml:Folder/wpml:waylineCoordinateSysParam/wpml:surfaceRelativeHeight', shoot_height)

    # 마진
    set_text('.//kml:Folder/kml:Placemark/wpml:margin', margin)

    # 중첩도(카메라/라이다)
    set_text('.//kml:Folder/kml:Placemark/wpml:overlap/wpml:orthoCameraOverlapH', oc_h)
    set_text('.//kml:Folder/kml:Placemark/wpml:overlap/wpml:orthoCameraOverlapW', oc_w)
    set_text('.//kml:Folder/kml:Placemark/wpml:overlap/wpml:orthoLidarOverlapH', ol_h)
    set_text('.//kml:Folder/kml:Placemark/wpml:overlap/wpml:orthoLidarOverlapW', ol_w)

    # 속도 관련
    set_text('.//kml:Folder/wpml:autoFlightSpeed', auto_speed)
    set_text('.//wpml:missionConfig/wpml:globalTransitionalSpeed', global_speed)

    # 이륙 보안 고도
    set_text('.//wpml:missionConfig/wpml:takeOffSecurityHeight', takeoff_sec_h)

    # 드론 정보 주입
    drone_model = overrides.get('drone_model')
    if drone_model:
        d_val, d_sub = dji_enums.get_drone_enum_values(drone_model)
        set_text('.//wpml:missionConfig/wpml:droneInfo/wpml:droneEnumValue', d_val)
        set_text('.//wpml:missionConfig/wpml:droneInfo/wpml:droneSubEnumValue', d_sub)
        
        p_val, p_idx = dji_enums.get_payload_enum_values(drone_model)
        # payloadInfo 노드가 여러 개일 수 있으나 기본적으로 첫 번째(0번)를 타겟팅
        set_text('.//wpml:missionConfig/wpml:payloadInfo/wpml:payloadEnumValue', p_val)
        set_text('.//wpml:missionConfig/wpml:payloadInfo/wpml:payloadPositionIndex', p_idx)
    
    # 지점별 상세 비행 설정
    gimbal_pitch = overrides.get('gimbal_pitch')
    set_text('.//kml:Placemark/wpml:smartObliqueGimbalPitch', gimbal_pitch)


# -----------------------------
# 템플릿에 좌표 주입 및 KMZ 생성
# -----------------------------

def inject_coords_to_template(template_kml_path: Path, lonlat: List[Tuple[str, str]], out_kml_path: Path,
                              set_times: bool = False, set_takeoff_ref_point: bool = False,
                              overrides: Optional[Dict] = None):
    tree = ET.parse(template_kml_path)
    root = tree.getroot()
    coords_elem = root.find('.//kml:Folder/kml:Placemark/kml:Polygon/kml:outerBoundaryIs/kml:LinearRing/kml:coordinates', NS)
    if coords_elem is None:
        coords_elem = root.find('.//kml:coordinates', NS)
    if coords_elem is None:
        raise ValueError('템플릿에서 <coordinates>를 찾지 못했습니다.')

    # 템플릿 형태 유지(들여쓰기 포함)
    indent = '\n                '
    coords_text = indent + indent.join([f'{lon},{lat},0' for lon, lat in lonlat]) + indent
    coords_elem.text = coords_text

    # 생성/업데이트 시간 갱신 (밀리초 epoch)
    if set_times:
        now_ms = str(int(time.time() * 1000))
        create_elem = root.find('.//wpml:createTime', NS)
        update_elem = root.find('.//wpml:updateTime', NS)
        if create_elem is not None:
            create_elem.text = now_ms
        if update_elem is not None:
            update_elem.text = now_ms

    # 이륙 기준점 자동 설정(폴리곤 중심값)
    if set_takeoff_ref_point:
        try:
            lons = [float(lon) for lon, _ in lonlat]
            lats = [float(lat) for _, lat in lonlat]
            if lons and lats:
                centroid_lat = sum(lats) / len(lats)
                centroid_lon = sum(lons) / len(lons)
                tk_elem = root.find('.//wpml:takeOffRefPoint', NS)
                if tk_elem is not None:
                    tk_elem.text = f'{centroid_lat:.6f},{centroid_lon:.6f},0.000000'
        except Exception:
            pass

    # 템플릿 파라미터 오버라이드 적용
    apply_template_overrides(root, overrides)

    tree.write(out_kml_path, encoding='UTF-8', xml_declaration=True)


def generate_kml_bytes(template_kml_path: Path, lonlat: List[Tuple[str, str]],
                       set_times: bool = False, set_takeoff_ref_point: bool = False,
                       overrides: Optional[Dict] = None) -> bytes:
    tree = ET.parse(template_kml_path)
    root = tree.getroot()
    coords_elem = root.find('.//kml:Folder/kml:Placemark/kml:Polygon/kml:outerBoundaryIs/kml:LinearRing/kml:coordinates', NS)
    if coords_elem is None:
        coords_elem = root.find('.//kml:coordinates', NS)
    if coords_elem is None:
        raise ValueError('템플릿에서 <coordinates>를 찾지 못했습니다.')

    # 템플릿 형태 유지(들여쓰기 포함)
    indent = '\n                '
    coords_text = indent + indent.join([f'{lon},{lat},0' for lon, lat in lonlat]) + indent
    coords_elem.text = coords_text

    # 생성/업데이트 시간 갱신 (밀리초 epoch)
    if set_times:
        now_ms = str(int(time.time() * 1000))
        create_elem = root.find('.//wpml:createTime', NS)
        update_elem = root.find('.//wpml:updateTime', NS)
        if create_elem is not None:
            create_elem.text = now_ms
        if update_elem is not None:
            update_elem.text = now_ms

    # 이륙 기준점 자동 설정(폴리곤 중심값)
    if set_takeoff_ref_point:
        try:
            lons = [float(lon) for lon, _ in lonlat]
            lats = [float(lat) for _, lat in lonlat]
            if lons and lats:
                centroid_lat = sum(lats) / len(lats)
                centroid_lon = sum(lons) / len(lons)
                tk_elem = root.find('.//wpml:takeOffRefPoint', NS)
                if tk_elem is not None:
                    tk_elem.text = f'{centroid_lat:.6f},{centroid_lon:.6f},0.000000'
        except Exception:
            pass

    # 템플릿 파라미터 오버라이드 적용
    apply_template_overrides(root, overrides)

    # 전체 KML XML을 바이트로 반환하여 디스크에 저장하지 않고 KMZ에 바로 포함 가능하도록 함
    return ET.tostring(root, encoding='UTF-8', xml_declaration=True)


def make_kmz(kml_path: Path, wpml_path: Path, kmz_path: Path, arcname_kml: str = 'template.kml', arcname_wpml: str = 'waylines.wpml'):
    with ZipFile(kmz_path, 'w', compression=ZIP_DEFLATED) as z:
        # 루트에 정확한 파일명으로 저장되도록 arcname 지정
        z.write(kml_path, arcname=arcname_kml)
        z.write(wpml_path, arcname=arcname_wpml)


def make_kmz_from_bytes(kml_bytes: bytes, wpml_path: Path, kmz_path: Path, arcname_kml: str = 'template.kml', arcname_wpml: str = 'waylines.wpml', overrides: Optional[Dict] = None):
    with ZipFile(kmz_path, 'w', compression=ZIP_DEFLATED) as z:
        # KML 파일을 디스크에 저장하지 않고 바로 KMZ에 추가
        z.writestr(arcname_kml, kml_bytes)
        # WPML도 overrides가 있다면 적용된 바이트로 추가
        if overrides:
            wpml_bytes = load_wpml_bytes_with_overrides(wpml_path, overrides)
            z.writestr(arcname_wpml, wpml_bytes)
        else:
            z.write(wpml_path, arcname=arcname_wpml)


# WPML 오버라이드
def load_wpml_bytes_with_overrides(wpml_path: Path, overrides: Optional[Dict] = None) -> bytes:
    """WPML(XML) 파일을 읽어 overrides를 적용한 뒤 bytes로 반환합니다."""
    tree = ET.parse(wpml_path)
    root = tree.getroot()

    def set_text(xpath: str, value):
        if value is None:
            return
        elem = root.find(xpath, NS)
        if elem is not None:
            elem.text = str(value)

    altitude = None
    shoot_height = None
    auto_speed = None
    global_speed = None
    takeoff_sec_h = None
    if overrides:
        altitude = overrides.get('altitude')
        shoot_height = overrides.get('shoot_height', altitude)
        auto_speed = overrides.get('auto_flight_speed')
        global_speed = overrides.get('global_transitional_speed')
        takeoff_sec_h = overrides.get('takeoff_security_height')

    # 속도/보안 고도
    set_text('.//kml:Folder/wpml:autoFlightSpeed', auto_speed)
    set_text('.//wpml:missionConfig/wpml:globalTransitionalSpeed', global_speed)
    set_text('.//wpml:missionConfig/wpml:takeOffSecurityHeight', takeoff_sec_h)

    # 좌표계 파라미터(존재하는 경우에만) - 글로벌 촬영 높이 및 지면 기준 높이
    set_text('.//wpml:waylineCoordinateSysParam/wpml:globalShootHeight', shoot_height if shoot_height is not None else altitude)
    set_text('.//wpml:waylineCoordinateSysParam/wpml:surfaceRelativeHeight', shoot_height if shoot_height is not None else altitude)

    # 각 웨이포인트 속도 업데이트 (autoFlightSpeed가 있을 때만)
    if auto_speed is not None:
        for el in root.findall('.//kml:Folder/kml:Placemark/wpml:waypointSpeed', NS):
            el.text = str(auto_speed)

    # 실행 고도 (각 웨이포인트)
    target_height = shoot_height if shoot_height is not None else altitude
    if target_height is not None:
        for el in root.findall('.//kml:Folder/kml:Placemark/wpml:executeHeight', NS):
            el.text = str(target_height)

    return ET.tostring(root, encoding='UTF-8', xml_declaration=True)


# -----------------------------
# 배치 처리 (KML/GPKG 지원)
# -----------------------------

def batch_process_inputs(missions_dir: Path, template_path: Path, waylines_path: Path, out_dir: Optional[Path] = None,
                         input_format: str = 'auto', naming_field: Optional[str] = None, layer: Optional[str] = None,
                         set_times: bool = True, set_takeoff_ref_point: bool = False, pack_kmz: bool = True,
                         overrides: Optional[Dict] = None, simplify_tolerance: float = 0.0):
    missions_dir = Path(missions_dir)
    template_path = Path(template_path)
    waylines_path = Path(waylines_path)
    if out_dir is None:
        out_dir = missions_dir.parent / 'output'
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def save_result(lonlat, dynm, src_name):
        if pack_kmz:
            kml_bytes = generate_kml_bytes(template_path, lonlat, set_times=set_times,
                                           set_takeoff_ref_point=set_takeoff_ref_point, overrides=overrides)
            out_kmz = out_dir / f'{dynm}.kmz'
            make_kmz_from_bytes(kml_bytes, waylines_path, out_kmz,
                                arcname_kml='template.kml', arcname_wpml='waylines.wpml', overrides=overrides)
            print(f'완료: {src_name} -> {out_kmz.name}')
        else:
            out_kml = out_dir / f'{dynm}.kml'
            inject_coords_to_template(template_path, lonlat, out_kml, set_times=set_times,
                                      set_takeoff_ref_point=set_takeoff_ref_point, overrides=overrides)
            print(f'완료: {src_name} -> {out_kml.name}')

    def process_one(file_path: Path, is_gpkg: bool):
        try:
            if is_gpkg:
                # GPKG는 내부 피처별로 분할 처리 시도
                gdf_all = read_gpkg_to_gdf(file_path, layer=layer)
                # 폴리곤 계열만
                gdf_poly = gdf_all[gdf_all.geometry.geom_type.isin(['Polygon', 'MultiPolygon'])].copy()
                if gdf_poly.empty:
                    print(f'건너뜀(폴리곤 없음): {file_path.name}')
                    return False
                
                for idx, row in gdf_poly.iterrows():
                    # 개별 피처 처리
                    import geopandas as gpd
                    single_gdf = gpd.GeoDataFrame([row], crs=gdf_all.crs)
                    lonlat, _ = parse_polygon_coords_from_gpkg_direct(single_gdf, to_epsg=4326, simplify_tolerance=simplify_tolerance)
                    
                    # 명명 필드 처리
                    dynm = fallback_name = f"{file_path.stem}_{idx}"
                    if naming_field and naming_field in row:
                        val = str(row[naming_field]).strip()
                        if val and val.lower() != 'none':
                            dynm = sanitize_filename(val)
                    
                    save_result(lonlat, dynm, file_path.name)
            else:
                # KML은 기존대로 단일 파일 처리
                lonlat = parse_polygon_coords_from_kml(file_path)
                dynm = parse_name_value_from_kml(file_path, naming_field=naming_field)
                save_result(lonlat, dynm, file_path.name)
            
            return True
        except Exception as e:
            print(f'오류: {file_path.name}: {e}')
            return False

    count_ok = 0
    count_err = 0

    files = []
    if input_format == 'gpkg':
        files = sorted(missions_dir.glob('*.gpkg'))
    elif input_format == 'kml':
        files = sorted(missions_dir.glob('*.kml'))
    else:  # auto
        files = sorted(list(missions_dir.glob('*.gpkg')) + list(missions_dir.glob('*.kml')))

    for src in files:
        is_gpkg = src.suffix.lower() == '.gpkg'
        ok = process_one(src, is_gpkg)
        if ok:
            count_ok += 1
        else:
            count_err += 1

    print(f'총 처리: {count_ok} 성공, {count_err} 실패')


# -----------------------------
# CLI 엔트리포인트
# -----------------------------
if __name__ == '__main__':
    base = Path(__file__).parent

    import argparse
    parser = argparse.ArgumentParser(description='KML 템플릿에 폴리곤 좌표를 주입하여 KMZ/KML 생성 (KML/GPKG 입력 지원)')
    parser.add_argument('--input-dir', type=str, default=str(base / 'input'), help='입력 폴더 경로 (KML 또는 GPKG)')
    parser.add_argument('--input-format', type=str, choices=['auto', 'kml', 'gpkg'], default='gpkg', help='입력 포맷 지정(auto/kml/gpkg)')
    parser.add_argument('--template', type=str, default=str(base / 'template.kml'), help='템플릿 KML 경로')
    parser.add_argument('--waylines', type=str, default=str(base / 'waylines.wpml'), help='waylines.wpml 경로')
    parser.add_argument('--out-dir', type=str, default=str(base / 'output'), help='출력 폴더 경로')
    parser.add_argument('--pack-kmz', action='store_true', help='KMZ로 패키징 (기본: 켜짐)')
    parser.add_argument('--no-pack-kmz', action='store_true', help='KMZ 비활성화(KML만 출력)')
    parser.add_argument('--set-times', action='store_true', help='생성/업데이트 시간을 현재시간으로 설정')
    parser.add_argument('--set-takeoff-ref-point', action='store_true', help='폴리곤 중심으로 이륙 기준점 자동 설정')
    parser.add_argument('--layer', type=str, default=None, help='GPKG 레이어 이름(여러 레이어가 있는 경우 지정)')
    parser.add_argument('--naming-field', type=str, default=None, help='출력 파일명으로 사용할 필드명(KML의 SimpleData name 또는 GPKG 컬럼)')
    parser.add_argument('--simplify-tolerance', type=float, default=0.0, help='지오메트리 단순화 허용 오차(미터 단위, 예: 0.5)')

    # 템플릿 오버라이드 인자
    parser.add_argument('--altitude', type=float, default=None, help='고도값(Placemark height/ellipsoidHeight, wayline globalShootHeight)')
    parser.add_argument('--shoot-height', type=float, default=None, help='waylineCoordinateSysParam의 globalShootHeight 별도 설정')
    parser.add_argument('--margin', type=int, default=None, help='마진값')
    parser.add_argument('--overlap-camera-h', type=int, default=None, help='카메라 수평 중첩(%)')
    parser.add_argument('--overlap-camera-w', type=int, default=None, help='카메라 수직 중첩(%)')
    parser.add_argument('--overlap-lidar-h', type=int, default=None, help='라이다 수평 중첩(%)')
    parser.add_argument('--overlap-lidar-w', type=int, default=None, help='라이다 수직 중첩(%)')
    parser.add_argument('--auto-flight-speed', type=int, default=None, help='자동 비행 속도')
    parser.add_argument('--global-transitional-speed', type=int, default=None, help='미션 전환 속도')
    parser.add_argument('--takeoff-security-height', type=int, default=None, help='이륙 보안 고도')
    parser.add_argument('--drone-model', type=str, default=None, help='DJI 드론 모델명 (예: mavic3e, m350)')
    parser.add_argument('--gimbal-pitch', type=float, default=None, help='짐벌 피치 각도 (예: -90)')

    args = parser.parse_args()

    pack_kmz = True
    if args.no_pack_kmz:
        pack_kmz = False
    elif args.pack_kmz:
        pack_kmz = True

    overrides = {
        'altitude': args.altitude,
        'shoot_height': args.shoot_height,
        'margin': args.margin,
        'overlap_camera_h': args.overlap_camera_h,
        'overlap_camera_w': args.overlap_camera_w,
        'overlap_lidar_h': args.overlap_lidar_h,
        'overlap_lidar_w': args.overlap_lidar_w,
        'auto_flight_speed': args.auto_flight_speed,
        'global_transitional_speed': args.global_transitional_speed,
        'takeoff_security_height': args.takeoff_security_height,
        'drone_model': args.drone_model,
        'gimbal_pitch': args.gimbal_pitch,
    }

    batch_process_inputs(
        missions_dir=Path(args.input_dir),
        template_path=Path(args.template),
        waylines_path=Path(args.waylines),
        out_dir=Path(args.out_dir),
        input_format=args.input_format,
        naming_field=args.naming_field,
        layer=args.layer,
        set_times=args.set_times,
        set_takeoff_ref_point=args.set_takeoff_ref_point,
        pack_kmz=pack_kmz,
        overrides=overrides,
        simplify_tolerance=args.simplify_tolerance,
    )