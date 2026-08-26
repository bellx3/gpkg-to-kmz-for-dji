"""GPKG 를 표준 라이브러리 sqlite3 로 직접 읽는다.

GeoPackage 는 SQLite 파일이다. 지오메트리는 BLOB 컬럼에 OGC 표준 형식으로 들어 있다:

    'GP' | version(1) | flags(1) | srs_id(int32) | envelope(가변) | WKB

flags 비트 — 0: 헤더 바이트순서, 1..3: 엔벨로프 종류, 4: 빈 지오메트리, 5: 확장형

이 모듈 하나가 GeoPandas + pandas + fiona + pyogrio 258MB 를 대신한다. 여기서
쓰던 것은 읽기·좌표계·컬럼명 셋뿐이었고 데이터프레임 연산은 없었다. 자세한 배경과
교체 전 대조 결과는 `docs/dependency-diet.md`.
"""
import sqlite3
import struct
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

from shapely import wkb

# 엔벨로프 지시자 -> 뒤따르는 바이트 수
_ENVELOPE_SIZE = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}


class Feature(NamedTuple):
    """GPKG 한 행. attrs 에 지오메트리 컬럼은 들어 있지 않다."""
    attrs: Dict
    geom: object  # shapely geometry, 빈 지오메트리면 None


class Layer(NamedTuple):
    features: List[Feature]
    epsg: Optional[int]
    name: str


def _decode_geometry(blob: bytes):
    """GPKG 지오메트리 BLOB 에서 shapely 지오메트리를 꺼낸다."""
    if not blob or len(blob) < 8 or blob[0:2] != b'GP':
        raise ValueError('GPKG 지오메트리 BLOB 이 아닙니다.')
    flags = blob[3]
    endian = '<' if flags & 0x01 else '>'
    env_kind = (flags >> 1) & 0x07
    env_size = _ENVELOPE_SIZE.get(env_kind)
    if env_size is None:
        raise ValueError(f'알 수 없는 엔벨로프 지시자: {env_kind}')
    if flags & 0x10:  # 빈 지오메트리
        return None
    return wkb.loads(blob[8 + env_size:])


def _connect(path: Path) -> sqlite3.Connection:
    # 읽기 전용으로 연다 — 변환기가 원본을 건드릴 일은 없다.
    con = sqlite3.connect(f'file:{Path(path).as_posix()}?mode=ro', uri=True)
    con.text_factory = str
    return con


def list_layers(path: Path) -> List[str]:
    con = _connect(path)
    try:
        return [r[0] for r in con.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type='features' ORDER BY table_name")]
    finally:
        con.close()


def read_layer(path: Path, layer: Optional[str] = None) -> Layer:
    """레이어 하나를 통째로 읽는다. layer 가 없으면 첫 피처 레이어를 쓴다."""
    path = Path(path)
    con = _connect(path)
    try:
        cur = con.cursor()
        if layer is None:
            row = cur.execute(
                "SELECT table_name FROM gpkg_contents WHERE data_type='features' "
                "ORDER BY table_name LIMIT 1").fetchone()
            if not row:
                raise ValueError(f'피처 레이어가 없습니다: {path.name}')
            layer = row[0]

        gc = cur.execute(
            'SELECT column_name, srs_id FROM gpkg_geometry_columns WHERE table_name=?',
            (layer,)).fetchone()
        if not gc:
            raise ValueError(f'레이어를 찾을 수 없습니다: {layer}')
        geom_col, srs_id = gc

        epsg = None
        srs = cur.execute(
            'SELECT organization, organization_coordsys_id FROM gpkg_spatial_ref_sys WHERE srs_id=?',
            (srs_id,)).fetchone()
        if srs and srs[0] and str(srs[0]).upper() == 'EPSG':
            epsg = int(srs[1])

        cur.execute(f'SELECT * FROM "{layer}"')
        names = [d[0] for d in cur.description]
        gi = names.index(geom_col)
        features = [
            Feature(
                attrs={n: v for i, (n, v) in enumerate(zip(names, row)) if i != gi},
                geom=_decode_geometry(row[gi]),
            )
            for row in cur.fetchall()
        ]
        return Layer(features=features, epsg=epsg, name=layer)
    finally:
        con.close()


def field_names(path: Path, layer: Optional[str] = None) -> List[str]:
    """명명 필드 후보가 될 속성 컬럼 이름.

    지오메트리 컬럼과 정수 기본키(보통 `fid`)를 뺀다 — GDAL 이 기본키를 속성이 아니라
    FID 로 취급하므로, 빼지 않으면 GeoPandas 로 읽던 때에 없던 항목이 목록에 끼어든다.
    """
    path = Path(path)
    con = _connect(path)
    try:
        cur = con.cursor()
        if layer is None:
            row = cur.execute(
                "SELECT table_name FROM gpkg_contents WHERE data_type='features' "
                "ORDER BY table_name LIMIT 1").fetchone()
            if not row:
                return []
            layer = row[0]
        gc = cur.execute(
            'SELECT column_name FROM gpkg_geometry_columns WHERE table_name=?', (layer,)).fetchone()
        geom_col = gc[0] if gc else None
        # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
        cols = cur.execute(f'PRAGMA table_info("{layer}")').fetchall()
        return [c[1] for c in cols
                if c[1] != geom_col and not (c[5] and str(c[2]).upper() == 'INTEGER')]
    finally:
        con.close()
