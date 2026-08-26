# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**SkyMission Builder** — GPKG/KML 폴리곤을 DJI 드론용 KMZ 임무 파일로 **대량 변환**하는 Python 데스크톱 앱. 서버도, 웹도 없다. Tkinter(CustomTkinter) GUI 하나와 `src/core/`의 변환 로직이 전부다.

출력은 DJI **WPML 1.0.6** 표준을 따른다.

## 스타터 잔재는 걷어냈다

한때 `.agent/` 91개와 `.serena/` 6개가 추적되고 있었다 — 추적 파일의 83%. 이 저장소와
무관한 *"Fullstack Starter — Next.js 16, FastAPI, Flutter, GCP"* 템플릿이었고(`frontend-agent`
는 `component-template.tsx`, `mobile-agent` 는 `screen-template.dart` 를 들고 있었다),
2026-08 에 지우고 `.gitignore` 에 넣었다. 도구가 다시 만들어도 커밋되지 않는다.

되살아나 있거든 **따르지 말 것.** 신뢰할 것은 `src/`, `tests/`, `README.md`, `docs/` 뿐이다.

## Commands

```bash
# 필수 — shapely · pyproj · customtkinter 셋뿐이다
pip install -r requirements.txt
# 지도 미리보기를 쓸 때만 (tkintermapview 하나가 17개 패키지 43.9MB 를 끌고 온다)
pip install -r requirements-optional.txt
# 테스트
pip install -r requirements-dev.txt

# 앱 실행 (프로젝트 루트에서)
python main.py

# 테스트 — 반드시 루트에서. tests/ 안에서 실행하면 collection 이 깨진다
python -m pytest tests/ -q
python -m pytest tests/test_validator.py::test_calculate_gsd -q   # 하나만

# 생성된 KMZ 의 내부 값 검증 (KML/WPML 양쪽을 나란히 출력)
python src/core/inspector.py output/어떤미션.kmz
```

린터·포매터 설정은 없다.

테스트는 23개 전부 통과한다. (2026-08 이전에는 8개 중 1개가 실패했다 —
`test_validate_mission_altitude_warning` 이 미국·유럽 기준인 120m 를 기대하고 있었다.
코드가 쓰는 한국 법정 한도 `> 150m` 가 맞아서 테스트 쪽을 고쳤고, 경계값 150 이
`safe` 임을 못박는 테스트를 함께 넣었다.)

## Architecture

### 변환은 "생성"이 아니라 "주입"이다

이것이 이 저장소의 중심 설계다. **KML/WPML 을 처음부터 만들지 않는다.** `src/templates/` 에 DJI 가 받아들이는 것이 검증된 원본 두 개(`template.kml` 79줄, `waylines.wpml` 891줄)를 두고, 거기 특정 XML 노드에 좌표와 설정값을 꽂아 넣는다.

```
GPKG/KML  →  sqlite3+shapely  →  EPSG:4326 재투영(pyproj)
          →  물리적 버퍼(m) · simplify
          →  좌표 리스트
          →  template.kml 의 <coordinates> 치환 + overrides 주입
          →  waylines.wpml 에 같은 overrides 주입
          →  둘을 ZIP → 폴리곤 하나당 KMZ 하나
```

KMZ 안의 파일명은 **반드시 루트에 `template.kml` 과 `waylines.wpml`** 이어야 한다(`make_kmz` 의 `arcname` 인자가 그것을 보장한다).

### 네임스페이스 등록은 모듈 임포트 시점에 일어난다

`generator.py` 최상단에서 `ET.register_namespace('', NS['kml'])` 와 `wpml` 을 전역 등록한다. 이걸 건너뛰면 출력 XML 에 `ns0:` 접두사가 붙고 **DJI 가 파일을 거부한다.** 다른 모듈에서 `xml.etree` 를 따로 쓸 때도 이 등록에 의존한다는 점을 기억할 것.

### KML 과 WPML 에 **같은 값을 두 번** 써야 한다

고도·중첩도·속도 같은 설정은 두 파일 모두에 들어 있고, 주입 경로가 서로 다르다.

| 대상 | 함수 |
|---|---|
| `template.kml` | `apply_template_overrides()` / `generate_kml_bytes()` |
| `waylines.wpml` | `load_wpml_bytes_with_overrides()` |

**한쪽만 고치면 기체가 서로 다른 값을 읽는다.** 설정 항목을 추가할 때는 두 경로 모두에 넣어야 한다. `inspector.py` 가 존재하는 이유가 바로 이것 — 같은 필드를 KML/WPML 나란히 출력해 불일치를 눈으로 잡는다.

### `src/core/` 의 역할 분담

- **`generator.py`** (645줄) — 파싱·재투영·버퍼·simplify·주입·ZIP·배치. 진입점은 `batch_process_inputs()`.
- **`gpkg.py`** — GPKG 리더. **GeoPandas 를 쓰지 않는다** — GeoPackage 는 SQLite 파일이라
  표준 라이브러리 `sqlite3` 로 읽고 지오메트리 BLOB 에서 WKB 만 떼어 `shapely.wkb` 에 넘긴다.
  이 135줄이 GeoPandas·pandas·fiona·pyogrio 258MB 를 대신한다(`docs/dependency-diet.md`).
  되돌리지 말 것. 재투영은 `pyproj.Transformer` + `shapely.ops.transform` 이 하고,
  버퍼·단순화는 **재투영 전에 원본 좌표계에서** 한다 — 지리 좌표계면 미터를 도로 환산(÷111111)한다.
- **`enums.py`** — 기체/페이로드의 DJI 정수 enum. WPML 이 모델명이 아니라 숫자를 요구한다. `m300*`/`m350*` 는 접두사 매칭으로 H20 을 기본 페이로드로 가정한다.
- **`validator.py`** — 안전·품질 판정. GSD `(H·Sw)/(F·Iw)`, 모션 블러 `V·S`. **블러 > GSD 면 danger, GSD 의 50% 초과면 warning.** 카메라 사양(`CAMERA_SPECS`)은 4기종만 있고 나머지는 Mavic 3E 로 폴백한다 — 지원 기체 25종에 비해 한참 적으므로 다른 기체의 GSD 는 신뢰도가 낮다.
- **`reporter.py`** — 배치 결과를 단일 HTML 리포트로. 템플릿이 f-string 이라 CSS 중괄호가 `{{ }}` 로 이스케이프되어 있다.
- **`inspector.py`** — 위 참조. 라이브러리가 아니라 CLI 스크립트다.

### GUI (`src/gui/app.py`, 760줄)

CustomTkinter + `tkintermapview`. 알아 둘 것 셋:

- **경로는 프로젝트 루트 기준으로 유도된다** — `BASE.parent.parent / "input"`. `src/gui/` 에서 두 단계 올라간다. 파일을 옮기면 기본 경로가 조용히 어긋난다.
- **배치는 스레드로 돌고 로그는 큐로 온다** — `LogRedirector` 가 `sys.stdout` 을 가로채 큐에 넣고 UI 가 폴링한다. core 쪽에서 `print()` 한 것이 그대로 로그창에 뜬다.
- **언어 토글은 UI 를 통째로 다시 만든다**(`_toggle_language` → `_rebuild_full_ui`). 위젯 상태를 들고 있는 코드를 추가할 때 재생성에서 살아남는지 확인할 것.

## 파일 규약

- `input/`·`output/` 은 gitignore 된다. 앱이 기본 경로로 쓰지만 저장소에는 없다.
- `presets/*.json` 도 gitignore 되며 **`default_inspection.json` 만 예외**로 추적된다. 새 프리셋을 커밋하려면 gitignore 를 고쳐야 한다.
- `docs/roadmap.md` 의 Task 1~3 은 완료, **Task 4(기체별 KMZ 구조 검증)만 미완**이다.
