# 의존성 다이어트

GPKG 읽기를 GeoPandas 스택에서 표준 라이브러리 `sqlite3` 로 옮긴다. 기능 손실 0.

## 체크리스트

- [x] 1. `src/core/gpkg.py` 신설 — sqlite3 기반 GPKG 리더
- [x] 2. `generator.py` 전환 — 리더 교체, 배치 루프, 죽은 함수 둘 제거
- [x] 3. `app.py` 전환 — 임포트, 미리보기, 필드 스캔
- [x] 4. 테스트 — `test_buffer.py` 전환, `test_gpkg.py` 신설, 낡은 고도 테스트 수정
- [x] 5. `requirements.txt` 신설 (필수/선택 분리)
- [x] 6. `.agent/` 91개 + `.serena/` 6개 삭제, `.gitignore` 반영
- [x] 7. `README.md` · `CLAUDE.md` 갱신
- [x] 8. 검증 — 골든 KMZ 대조, 전체 테스트
- [x] 9. 커밋 (범위별 분리)

## 기준선 (2026-08-26 측정)

의존성 폐포 **34개 패키지 · 340.9 MB**. 상위 항목:

| MB | 패키지 | 정체 |
|---:|---|---|
| 67.9 | pyogrio | GDAL 번들 (GPKG 읽기) |
| 65.4 | numpy | shapely·pandas 가 요구 |
| 64.0 | fiona | GDAL 번들 — **코드가 임포트하지 않음** |
| 61.2 | pandas | geopandas 가 요구 |
| 24.4 | pyproj | 좌표 변환 (실사용) |
| 19.4 | pywin32 | ← tkintermapview |
| 15.3 | pillow | ← tkintermapview |
| 6.1 | shapely | 기하 연산 (실사용) |
| 3.4 | geopandas | 실제 사용은 여섯 가지 |

추적 파일 117개 중 **97개(83%)가 다른 프로젝트의 스타터 잔재**(`.agent/` 91, `.serena/` 6).
테스트는 8개 중 7개 통과.

## 왜 GeoPandas 를 걷어낼 수 있나

GeoPandas 로 하는 일이 여섯 가지뿐이고 데이터프레임 연산이 하나도 없다 —
`read_file` · `.crs` · `geom_type` 필터 · `to_crs` · `GeoDataFrame([row])` · `.columns`.
258 MB 를 얇은 껍데기 하나에 쓰고 있었다.

**GPKG 는 SQLite 파일이다.** 지오메트리 BLOB 은 OGC 표준으로 정해져 있다:

```
'GP' | version(1) | flags(1) | srs_id(int32) | envelope(가변) | WKB
flags 비트: 0=바이트순서, 1..3=엔벨로프 종류, 4=빈 지오메트리, 5=확장형
```

`sqlite3`(표준 라이브러리) 로 읽고 `shapely.wkb` 로 WKB 를 풀면 된다. 좌표계는
`gpkg_geometry_columns.srs_id` → `gpkg_spatial_ref_sys` 로 EPSG 코드를 얻고,
재투영은 `pyproj.Transformer` + `shapely.ops.transform` 이 한다 (GeoPandas 의
`to_crs` 가 내부에서 하던 것과 같다 — `always_xy=True`).

### 착수 전 검증

교체 전에 옛 경로와 새 경로를 같은 입력으로 돌려 최종 좌표 문자열을 대조했다.
**81건 중 불일치 0.**

- 좌표계 4종: EPSG 5186 / 5174(Bessel — 진짜 datum shift) / 32652 / 4326(재투영 없음)
- 버퍼 3종(0, +5m, −3m) × 단순화 3종(0, 1m, 10m)
- 전체병합 경로와 피처별 경로 양쪽
- 폴리곤·멀티폴리곤·구멍 있는 폴리곤·점형(걸러져야 함) 혼재

## 어디서 멈추는가

| | 패키지 | 크기 | 기능 |
|---|---:|---:|---|
| 현재 | 34 | 340.9 MB | — |
| fiona 만 제거 | 30 | 276.4 MB | 손실 0 · 코드 무변경 |
| **채택: + geopandas·pyogrio 제거** | **25** | **142.6 MB** | **손실 0** |
| ↳ 지도 위젯을 선택 설치로 | 8 | 98.8 MB | 필수 설치 기준 |
| 기각: + shapely 제거 | 6 | 27.3 MB | buffer·union 직접 구현 |
| 기각: + pyproj 제거 | 4 | 2.6 MB | datum 변환 직접 구현 |

**shapely 와 pyproj 는 남긴다.** `buffer` 와 `unary_union` 은 직접 짜면 미묘하게 틀리고,
pyproj 를 걷어내면 Bessel datum 변환을 손으로 짜야 한다. 여기서 몇 미터 어긋나면
기체가 남의 땅 위를 난다. 27 MB 를 아끼자고 할 일이 아니다.

**지도 미리보기(tkintermapview)는 남기되 선택 설치로 뺀다.** 폴리곤이 제 위치에
떨어졌는지 눈으로 보는 수단이라 기능으로서는 유지할 값어치가 있는데, 이것 하나가
17개 패키지 43.9 MB(pywin32·pillow·requests·geopy·geocoder…)를 끌고 온다.
코드는 이미 `try/except` 로 없어도 돌게 돼 있으니 `requirements.txt` 만 나누면 된다.

## 회귀 판정 방법

바꾸기 **전에** 현재 코드로 KMZ 12개를 떠 두고(골든), 바꾼 뒤 같은 입력으로 다시 떠서
KMZ 내부 `template.kml` · `waylines.wpml` 의 SHA-256 을 대조한다. KMZ 는 ZIP 이라
파일 타임스탬프가 섞이므로 압축 파일째 비교하지 않고 **내부 파일의 내용만** 해시한다.
`set_times=False` 로 고정한다 — 시각이 들어가면 매 실행 결과가 달라져 대조가 불가능하다.

## 결과 (2026-08-26)

| | 전 | 후 |
|---|---:|---:|
| 필수 설치 | 34개 · 340.9 MB | **8개 · 98.8 MB** (−71%) |
| 지도 미리보기까지 | — | 25개 · 142.6 MB (−58%) |
| 추적 파일 | 117개 | **20개** |
| 테스트 | 8개 중 7개 통과 | **23개 전부 통과** |

필수 폐포 8개: numpy(65.4) · pyproj(24.4) · shapely(6.1) · customtkinter(1.5) ·
packaging · typing-extensions · certifi · darkdetect.
numpy 는 shapely 가 요구하므로 shapely 를 남기는 한 함께 남는다.

### 회귀 검증 결과

- **골든 KMZ 12개 × 내부파일 2개 = 24개 대조, 불일치 0.** 정상성 확인으로
  `template.kml` 해시가 12종 모두 다름을 함께 봤다 — 같은 파일 12개를 비교하고
  "일치"라고 읽는 사고를 막는다.
- **geopandas·fiona·pyogrio·pandas 를 임포트 불가로 막은 채** 같은 변환을 돌려
  동일한 KMZ 12개를 얻었다. 전역 환경에 그것들이 깔려 있으므로, 막지 않으면
  남아 있는 임포트가 조용히 성공해 다이어트가 된 것처럼 보인다.
  차단기 자체의 정상성도 확인했다(넷 다 ImportError, shapely·pyproj·sqlite3 는 통과).
- 차단 상태로 전체 테스트 23개 통과.
- GUI 모듈이 **지도 위젯 유무 양쪽에서** 임포트된다 — 선택 설치 주장의 실증.
- 새 테스트가 실제로 고장을 잡는지 돌연변이 셋으로 확인했다(엔벨로프 크기 0 고정,
  빈 지오메트리 플래그 무시, 기본키 필터 제거 → 각각 4·1·1건 실패).

## 손대지 않은 것

- **`waylines.wpml` 이 모든 임무에서 동일하다.** 골든을 뜨면서 확인했다 — 좌표는
  `template.kml` 에만 들어가고 WPML 에는 설정값만 주입되므로, 폴리곤이 달라도
  WPML 해시가 같다. 현 설계 그대로의 동작이고 이번 작업 범위 밖이라 건드리지 않는다.
  기체가 무엇을 읽는지(템플릿을 받아 경로를 다시 계산하는지, WPML 을 그대로 따르는지)는
  `docs/roadmap.md` Task 4(기체별 KMZ 구조 검증)에서 볼 일이다.
- **`validator.py` 의 `CAMERA_SPECS` 가 4기종뿐**인데 지원 기체는 25종이라 나머지는
  Mavic 3E 로 폴백한다. GSD 신뢰도 문제지만 의존성과 무관하다.
