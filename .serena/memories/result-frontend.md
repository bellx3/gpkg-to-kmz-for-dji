# Result - Frontend Agent (2026-02-11)
- Status: **completed**
- Summary: 물리적 버퍼(Buffer) 설정 UI 추가 및 지도 미리보기 연동 완료.

## Work Done
1.  **UI 필드 추가**:
    *   `src/gui/app.py`의 '상세 파라미터' 섹션에 **"물리적 버퍼 (m)"** 입력 필드를 추가했습니다.
    *   사용자 가이드를 위해 "(양수:확장, 음수:축소)" 안내 문구를 배치했습니다.
2.  **데이터 연동**:
    *   입력된 값을 `overrides` 딕셔너리의 `geometry_buffer_m` 키로 백엔드에 전달하도록 구성했습니다.
    *   프리셋 저장 및 불러오기 기능에 물리적 버퍼 필드를 포함시켜 설정의 영속성을 보장했습니다.
3.  **실시간 지도 미리보기 연동**:
    *   버퍼 값이 변경될 때마다 지도 미리보기가 자동으로 갱신되도록 `trace_add` 이벤트를 연결했습니다.
    *   `_update_map_preview` 메서드에서 GPKG 데이터를 읽을 때 입력된 버퍼 값을 적용하여, 사용자가 지면 확장/축소 결과를 즉시 시각적으로 확인할 수 있게 했습니다.

## Files Modified
- `src/gui/app.py`

## Acceptance Criteria
- [x] "물리적 버퍼 (m)" 입력 필드 노출
- [x] 입력 값이 백엔드(geometry_buffer_m)로 정상 전달됨
- [x] 버퍼 변경 시 지도 미리보기에 실시간 반영
- [x] 프리셋 저장/불러오기 지원
