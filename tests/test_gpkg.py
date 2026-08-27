"""sqlite3 기반 GPKG 리더 검증. 픽스처 조립기는 conftest.py 에 있다."""
import pytest
from shapely.geometry import Point, MultiPolygon

from src.core import gpkg
from tests.conftest import SQUARE


@pytest.fixture
def sample(tmp_path, make_gpkg, gpkg_blob):
    return make_gpkg(tmp_path / 's.gpkg', [
        ('필지1', 'a', SQUARE),
        ('필지2', 'b', gpkg_blob(SQUARE, 5186, with_envelope=True)),
        ('점형', 'c', Point(5, 5)),
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


def test_empty_geometry_reads_as_none(tmp_path, make_gpkg, gpkg_blob):
    from shapely.geometry import Polygon
    p = make_gpkg(tmp_path / 'e.gpkg', [
        ('빈것', 'x', gpkg_blob(Polygon(), 5186, empty=True)),
        ('멀쩡', 'y', SQUARE),
    ])
    geoms = [f.geom for f in gpkg.read_layer(p).features]
    assert geoms[0] is None
    assert geoms[1].area == 100 * 100


def test_non_epsg_authority_yields_no_epsg(tmp_path, make_gpkg):
    p = make_gpkg(tmp_path / 'n.gpkg', [('a', 'a', SQUARE)], srs_id=9999, org='NONE')
    assert gpkg.read_layer(p).epsg is None


def test_rejects_non_gpkg_blob(tmp_path, make_gpkg):
    p = make_gpkg(tmp_path / 'b.gpkg', [('a', 'a', b'NOTGPKG')])
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


def test_multipolygon_survives_the_round_trip(tmp_path, make_gpkg):
    mp = MultiPolygon([(((0, 0), (10, 0), (10, 10), (0, 10)), []),
                       (((20, 0), (30, 0), (30, 10), (20, 10)), [])])
    p = make_gpkg(tmp_path / 'm.gpkg', [('mp', 'z', mp)])
    geom = gpkg.read_layer(p).features[0].geom
    assert geom.geom_type == 'MultiPolygon'
    assert geom.area == mp.area


def test_field_stats_counts_empties_and_uniques(tmp_path, make_gpkg):
    # name 은 전부 고유, note 는 둘이 같고 하나는 공백뿐 → 파일명으로 쓰면 겹친다
    p = make_gpkg(tmp_path / 'st.gpkg', [
        ('가', 'x', SQUARE), ('나', 'x', SQUARE), ('다', '   ', SQUARE),
    ])
    st = {x.name: x for x in gpkg.field_stats(p)}
    assert st['name'].total == 3 and st['name'].unique == 3
    assert st['name'].collisions == 0
    assert st['note'].nulls == 1          # 공백뿐인 값도 빈 값이다
    assert st['note'].unique == 1         # 'x' 하나
    assert st['note'].collisions == 1     # 'x' 둘 중 하나가 겹친다


def test_field_stats_flags_all_empty_field(tmp_path, make_gpkg):
    # 전부 비어 있으면 파일명으로 쓸 수 없다 — GUI 가 후보에서 빼는 근거
    p = make_gpkg(tmp_path / 'e.gpkg', [('가', None, SQUARE), ('나', None, SQUARE)])
    st = {x.name: x for x in gpkg.field_stats(p)}
    assert st['note'].all_null is True
    assert st['name'].all_null is False
