"""입력 지정 해석 — 폴더 · 파일 하나 · 파일 여러 개.

입력이 폴더에 한정돼 있었기 때문에, "폴더 안에서 이 파일만" 이 불가능했다.
해석은 엔진의 resolve_input_files 하나로 모았다 — GUI 가 따로 glob 하면
미리보기에는 보이는데 실행에서 빠지는 불일치가 생긴다.
"""
from pathlib import Path

import pytest
from shapely.geometry import Polygon

from src.core.generator import (INPUT_SEP, batch_process_inputs, input_base_dir,
                                resolve_input_files)

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = REPO_ROOT / 'src' / 'templates'


@pytest.fixture
def three_files(tmp_path, make_gpkg):
    src = tmp_path / 'in'
    src.mkdir()
    for i in range(3):
        poly = Polygon([(126.5, 33.5), (126.501, 33.5), (126.501, 33.501), (126.5, 33.501)])
        make_gpkg(src / f'p{i}.gpkg', [(f'필지{i}', f'r{i}', poly)], srs_id=4326)
    (src / 'note.txt').write_text('무시된다', encoding='utf-8')
    return src


def test_folder_spec_collects_matching_extensions(three_files):
    files = resolve_input_files(three_files, 'gpkg')
    assert [f.name for f in files] == ['p0.gpkg', 'p1.gpkg', 'p2.gpkg']


def test_single_file_spec(three_files):
    files = resolve_input_files(three_files / 'p1.gpkg', 'gpkg')
    assert [f.name for f in files] == ['p1.gpkg']


def test_multiple_files_joined_by_separator(three_files):
    spec = INPUT_SEP.join([str(three_files / 'p2.gpkg'), str(three_files / 'p0.gpkg')])
    files = resolve_input_files(spec, 'gpkg')
    assert [f.name for f in files] == ['p2.gpkg', 'p0.gpkg']   # 고른 순서를 지킨다


def test_explicit_file_survives_format_filter(three_files):
    """포맷 드롭다운은 폴더를 훑을 때의 필터다 — 직접 고른 파일을 걸러내면 안 된다."""
    files = resolve_input_files(three_files / 'p0.gpkg', 'kml')
    assert [f.name for f in files] == ['p0.gpkg']


def test_folder_and_its_file_together_are_not_processed_twice(three_files):
    spec = INPUT_SEP.join([str(three_files), str(three_files / 'p0.gpkg')])
    files = resolve_input_files(spec, 'gpkg')
    assert len(files) == 3


def test_missing_paths_are_dropped(tmp_path):
    assert resolve_input_files(tmp_path / 'none', 'gpkg') == []
    assert resolve_input_files('', 'gpkg') == []


def test_input_base_dir(three_files):
    assert input_base_dir(three_files) == three_files
    assert input_base_dir(three_files / 'p0.gpkg') == three_files
    assert input_base_dir(INPUT_SEP.join([str(three_files / 'p1.gpkg'), 'x'])) == three_files


def test_batch_runs_on_a_single_file(three_files, tmp_path):
    """골라 준 파일 하나만 변환된다 — 폴더의 나머지는 건드리지 않는다."""
    out = tmp_path / 'out'
    batch_process_inputs(three_files / 'p1.gpkg', TEMPLATES / 'template.kml',
                         TEMPLATES / 'waylines.wpml', out_dir=out, input_format='gpkg',
                         overrides={'altitude': 100, 'drone_model': 'mavic3e'})
    kmz = sorted(p.name for p in out.glob('*.kmz'))
    assert len(kmz) == 1 and kmz[0].startswith('p1')
