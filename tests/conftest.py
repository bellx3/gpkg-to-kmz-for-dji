"""테스트가 공유하는 GPKG 픽스처.

GPKG 를 파일로 커밋하지 않고 그때그때 만든다 — 지오메트리 BLOB 을 직접 조립하므로
헤더의 어느 비트가 무엇인지가 코드에 드러나고, 엔벨로프 유무·빈 지오메트리처럼
평소 샘플에 잘 들어 있지 않은 경우도 확실히 만들 수 있다.
"""
import sqlite3
import struct

import pytest
from shapely import wkb
from shapely.geometry import Polygon

# 100m x 100m 정사각형. 투영 좌표계에서 면적이 10000 이라 계산이 눈으로 검산된다.
SQUARE = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])


def _blob(geom, srs_id, with_envelope=False, empty=False):
    """GPKG 지오메트리 BLOB 조립: 'GP' | version | flags | srs_id | envelope | WKB"""
    flags = 0x01                      # 비트0: 헤더가 리틀엔디언
    if with_envelope:
        flags |= 0x01 << 1            # 비트1..3: 엔벨로프 지시자 1 = XY, 32바이트
    if empty:
        flags |= 0x10                 # 비트4: 빈 지오메트리
    head = b'GP' + bytes([0, flags]) + struct.pack('<i', srs_id)
    env = b''
    if with_envelope:
        xmin, ymin, xmax, ymax = geom.bounds
        env = struct.pack('<4d', xmin, xmax, ymin, ymax)
    return head + env + wkb.dumps(geom)


def _make(path, rows, srs_id=5186, org='EPSG', table='parcels'):
    """rows 는 (name, note, 지오메트리 또는 BLOB) 의 나열."""
    path = str(path)
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE gpkg_spatial_ref_sys (srs_name TEXT, srs_id INTEGER PRIMARY KEY,
            organization TEXT, organization_coordsys_id INTEGER, definition TEXT, description TEXT);
        CREATE TABLE gpkg_contents (table_name TEXT PRIMARY KEY, data_type TEXT, identifier TEXT,
            description TEXT, last_change DATETIME, min_x DOUBLE, min_y DOUBLE,
            max_x DOUBLE, max_y DOUBLE, srs_id INTEGER);
        CREATE TABLE gpkg_geometry_columns (table_name TEXT, column_name TEXT,
            geometry_type_name TEXT, srs_id INTEGER, z TINYINT, m TINYINT);
        """
    )
    con.execute('INSERT INTO gpkg_spatial_ref_sys VALUES (?,?,?,?,?,?)',
                (f'srs{srs_id}', srs_id, org, srs_id, 'undefined', ''))
    con.execute('INSERT INTO gpkg_contents VALUES (?,?,?,?,?,?,?,?,?,?)',
                (table, 'features', table, '', '2026-01-01T00:00:00Z', 0, 0, 0, 0, srs_id))
    con.execute('INSERT INTO gpkg_geometry_columns VALUES (?,?,?,?,?,?)',
                (table, 'geom', 'GEOMETRY', srs_id, 0, 0))
    con.execute(f'CREATE TABLE "{table}" (fid INTEGER PRIMARY KEY AUTOINCREMENT, '
                'name TEXT, note TEXT, geom BLOB)')
    con.executemany(
        f'INSERT INTO "{table}" (name, note, geom) VALUES (?,?,?)',
        [(n, note, g if isinstance(g, bytes) else _blob(g, srs_id)) for n, note, g in rows],
    )
    con.commit()
    con.close()
    return path


@pytest.fixture
def gpkg_blob():
    return _blob


@pytest.fixture
def make_gpkg():
    return _make
