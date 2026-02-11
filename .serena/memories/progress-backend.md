# Progress - Backend Agent (2026-02-11)
- Task: [P2] 지오메트리 물리적 버퍼(Buffer) 기능 구현
- Status: Turn 1 - Analysis & Plan

## Step 0: Preparation
- Difficulty: **Medium** (Shapely 지오메트리 연산 및 좌표계 변환 처리 필요)
- Protocol: Standard Protocol
- Context Budget: `src/core/generator.py` 집중 분석.

## Step 1: Analyze
- Requirements:
    - `parse_polygon_coords_from_gpkg_direct`: `geometry_buffer_m` 인자 추가 및 `poly.buffer()` 적용.
    - 지리 좌표계(WGS84)인 경우 미터 단위를 도 단위로 변환 ($1m \approx 1/111111^{\circ}$).
    - `batch_process_inputs`에서 `overrides`를 통해 버퍼 값을 전달받아 처리.
- 핵심 도전 과제:
    - 투영 좌표계가 아닌 WGS84에서 `buffer()`를 직접 적용할 때의 왜곡 고려 (근사치 사용).

## Step 2: Plan
1. **`generator.py` 수정**:
    - `parse_polygon_coords_from_gpkg_direct` 함수 시그니처 수정 (`geometry_buffer_m: float = 0.0` 추가).
    - `poly.simplify` 전 또는 후에 `poly.buffer(actual_buffer)` 로직 삽입.
    - `parse_polygon_coords_from_gpkg` 및 `process_one` 로직 업데이트하여 값 전달.
2. **검증**:
    - `geometry_buffer_m`이 양수일 때 폴리곤이 확장되고, 음수일 때 축소되는지 확인.
    - 기존 WPML 마진 기능과 독립적으로 작동하는지 확인.
