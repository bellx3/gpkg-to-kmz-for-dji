# Progress - Frontend Agent (2026-02-11)
- Task: [P2] 물리적 버퍼(Buffer) 설정 UI 추가
- Status: Turn 1 - Analysis & Plan

## Step 0: Preparation
- Difficulty: **Simple** (UI 필드 추가 및 데이터 연동)
- Protocol: Standard Protocol
- Context Budget: `src/gui/app.py` 분석.

## Step 1: Analyze
- Requirements:
    - `src/gui/app.py`의 `group_param` (상세 파라미터) 섹션에 "물리적 버퍼 (m)" 입력란 추가.
    - `overrides` 딕셔너리에 `geometry_buffer_m` 키로 변수 연동.
    - 지도 미리보기 시 입력된 버퍼 값을 반영하여 폴리곤 표시.
    - 프리셋 저장/불러오기 기능에 해당 필드 포함.

## Step 2: Plan
1. **UI 레이아웃 수정**:
    - `self.var_geometry_buffer = tk.StringVar(value="0.0")` 추가.
    - `add_r_item`을 사용하여 "물리적 버퍼 (m)" 필드 배치.
2. **데이터 연동 및 작업 실행**:
    - `_run_job` 내 `overrides` 구성 시 `geometry_buffer_m` 추가.
    - `_on_save_preset`/`_on_load_preset`에 필드 추가.
3. **지도 미리보기 개선**:
    - `_update_map_preview`에서 `parse_polygon_coords_from_gpkg_direct` 호출 시 현재 입력된 `geometry_buffer_m`을 전달하도록 수정.
    - `var_geometry_buffer`에 `trace_add`를 걸어 값이 변할 때마다 지도가 갱신되도록 설정.
4. **검증**:
    - GUI에서 버퍼 값을 입력했을 때 지도상의 폴리곤 크기가 변하는지 확인.
    - "미션 생성 실행" 시 실제 생성된 파일에 좌표 변환이 적용되는지 확인.
