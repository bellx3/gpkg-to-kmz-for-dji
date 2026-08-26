"""sqlite3 기반 GPKG 리더 검증.

픽스처를 파일로 커밋하지 않고 테스트 안에서 만든다 — 지오메트리 BLOB 을 직접 조립하므로
헤더의 어느 비트가 무엇인지가 테스트에 드러나고, 엔벨로프 유무·빈 지오메트리처럼
평소 샘플에 잘 안 들어 있는 경우도 확실히 만들 수 있다.
"""
import sqlite3
import struct

import pytest
from shapely.geometry import Polygon, Point, MultiPolygon
from shapely import wkb

from src.core import gpkg

SQUARE = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])


def gpkg_blob(geom, srs_id, with_envelope=False, empty=False):
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


def make_gpkg(path, rows, srs_id=5186, org='EPSG', table='parcels'):
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
    con.executemany(f'INSERT INTO "{table}" (name, note, geom) VALUES (?,?,?)', rows)
    con.commit()
    con.close()
    return path


@pytest.fixture
def sample(tmp_path):
    return make_gpkg(str(tmp_path / 's.gpkg'), [
        ('필지1', 'a', gpkg_blob(SQUARE, 5186)),
        ('필지2', 'b', gpkg_blob(SQUARE, 5186, with_envelope=True)),
        ('점형', 'c', gpkg_blob(Point(5, 5), 5186)),
    ])


def test_reads_geometry_crs_and_attrs(sample):
    lyr = gpkg.read_layer(sample)
    assert lyr.name == 'parcels'
    assert lyr.epsg == 5186
    assert [f.geom.geom_type for f in lyr.features] == ['Polygon', 'Polygon', 'Point']
    assert [f.attrs['name'] for f in lyr.features] == ['필지1', '필지2', '점형']


def test_envelope_is_skipped_not_parsed_as_geometry(sample):
    # 엔벨로프가 붙은 행과 안 붙은 행이 같은 도형이어야 한다.
    a, b = gpkg.read_layer(sample).features[:2]
    assert a.geom.equals(b.geom)
    assert a.geom.area == 100 * 100


def test_layer_listing_and_explicit_layer(sample):
    assert gpkg.list_layers(sample) == ['parcels']
    assert gpkg.read_layer(sample, layer='parcels').name == 'parcels'


def test_field_names_drops_geometry_and_integer_pk(sample):
    # fid 는 GDAL 이 FID 로 취급하므로 명명 필드 후보가 아니다.
    assert gpkg.field_names(sample) == ['name', 'note']


def test_empty_geometry_reads_as_none(tmp_path):
    p = make_gpkg(str(tmp_path / 'e.gpkg'), [
        ('빈것', 'x', gpkg_blob(Polygon(), 5186, empty=True)),
        ('멀쩡', 'y', gpkg_blob(SQUARE, 5186)),
    ])
    geoms = [f.geom for f in gpkg.read_layer(p).features]
    assert geoms[0] is None
    assert geoms[1].area == 100 * 100


def test_non_epsg_authority_yields_no_epsg(tmp_path):
    p = make_gpkg(str(tmp_path / 'n.gpkg'), [('a', 'a', gpkg_blob(SQUARE, 9999))],
                  srs_id=9999, org='NONE')
    assert gpkg.read_layer(p).epsg is None


def test_rejects_non_gpkg_blob(tmp_path):
    p = make_gpkg(str(tmp_path / 'b.gpkg'), [('a', 'a', b'NOTGPKG')])
    with pytest.raises(ValueError):
        gpkg.read_layer(p)


def test_missing_layer_is_an_error(sample):
    with pytest.raises(ValueError):
        gpkg.read_layer(sample, layer='nope')


def test_polygon_features_keeps_original_index(sample):
    # 점형(인덱스 2)이 걸러져도 남는 것의 인덱스는 0,1 그대로여야 한다.
    from src.core.generator import polygon_features
    lyr = gpkg.read_layer(sample)
    assert [i for i, _ in polygon_features(lyr.features)] == [0, 1]


def test_multipolygon_survives_the_round_trip(tmp_path):
    mp = MultiPolygon([(((0, 0), (10, 0), (10, 10), (0, 10)), []),
                       (((20, 0), (30, 0), (30, 10), (20, 10)), [])])
    p = make_gpkg(str(tmp_path / 'm.gpkg'), [('mp', 'z', gpkg_blob(mp, 5186))])
    geom = gpkg.read_layer(p).features[0].geom
    assert geom.geom_type == 'MultiPolygon'
    assert geom.area == mp.area
