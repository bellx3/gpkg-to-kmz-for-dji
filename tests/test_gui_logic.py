"""GUI 의 순수 로직 검증 — Tk 창 없이 돈다.

app.py 에서 설정 조립과 프리셋 직렬화를 모듈 함수로 분리한 이유가 이 파일이다:
GUI 를 띄우지 않고도 "입력 문자열 → 엔진 인자" 변환의 회귀를 잡는다.
"""
import json
from pathlib import Path

from src.gui.app import (AUTO_NAME, TF_MODELS, build_overrides,
                         effective_naming_field, preset_from_values,
                         to_number, values_from_preset)

BASE_VALUES = {
    "altitude": "150.0", "shoot_height": "", "margin": "0",
    "overlap_camera_h": "80", "overlap_camera_w": "70",
    "overlap_lidar_h": "50", "overlap_lidar_w": "50",
    "auto_flight_speed": "10", "global_transitional_speed": "",
    "takeoff_security_height": "20", "drone_model": "mavic3e",
    "gimbal_pitch": "-90.0", "use_terrain_follow": False,
    "geometry_buffer_m": "0.0", "simplify_tolerance": "0.0",
    "set_times": True, "set_takeoff_ref_point": True, "pack_kmz": True,
}


def test_decimal_speed_survives():
    # 회귀: to_int 시절 12.5 가 조용히 None 이 되어 미주입됐다(B4)
    ov = build_overrides({**BASE_VALUES, "auto_flight_speed": "12.5"})
    assert ov["auto_flight_speed"] == 12.5


def test_integer_speed_stays_integer():
    # "10" 이 10.0 으로 바뀌면 산출물 문자열이 "10.0" 이 된다 — 정수는 정수로
    ov = build_overrides(BASE_VALUES)
    assert ov["auto_flight_speed"] == 10
    assert isinstance(ov["auto_flight_speed"], int)


def test_empty_buffer_is_zero_not_none():
    # 회귀: 빈 버퍼 칸이 None 으로 가면 엔진의 buffer(None) 이 터진다(B16)
    ov = build_overrides({**BASE_VALUES, "geometry_buffer_m": ""})
    assert ov["geometry_buffer_m"] == 0.0


def test_empty_shoot_height_follows_altitude():
    ov = build_overrides(BASE_VALUES)
    assert ov["shoot_height"] == ov["altitude"] == 150.0


def test_explicit_shoot_height_wins():
    ov = build_overrides({**BASE_VALUES, "shoot_height": "80"})
    assert ov["shoot_height"] == 80


def test_naming_sentinel_and_blank_mean_auto():
    assert effective_naming_field(AUTO_NAME) is None
    assert effective_naming_field("") is None
    assert effective_naming_field("(로드 필요)") is None
    assert effective_naming_field("ADDRE_1_2") == "ADDRE_1_2"


def test_to_number():
    assert to_number("12") == 12 and isinstance(to_number("12"), int)
    assert to_number("12.5") == 12.5
    assert to_number("") is None
    assert to_number("abc") is None


def test_terrain_follow_is_exact_match():
    assert "m300" in TF_MODELS
    assert "mini3" not in TF_MODELS       # 부분 문자열 매칭이었다면 위험했던 케이스
    assert "mavic3" not in TF_MODELS      # 무인쇄 기본형은 미지원


def test_preset_roundtrip_is_lossless():
    values = {**BASE_VALUES, "auto_flight_speed": "12.5", "geometry_buffer_m": "4.0",
              "use_terrain_follow": True, "pack_kmz": False}
    data = preset_from_values(values)
    back = values_from_preset(data)
    # 되돌린 값으로 다시 만들면 같은 프리셋이어야 한다
    assert preset_from_values({**values, **back}) == data


def test_tracked_default_preset_loads():
    """저장소에 추적되는 프리셋이 실제로 로드 가능한 스키마인지 — 호환의 증거."""
    p = Path(__file__).resolve().parent.parent / "presets" / "default_inspection.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    out = values_from_preset(data)
    assert out["altitude"] == "50.0"
    assert out["drone_model"] == "mavic3e"
    assert out["shoot_height"] == ""      # 고도와 같으므로 "따름" 표현으로 돌아온다
    # 로드한 값이 엔진 인자로도 조립되는가
    ov = build_overrides({**BASE_VALUES, **out})
    assert ov["altitude"] == 50.0
    assert ov["shoot_height"] == 50.0


def test_preset_ignores_unknown_keys():
    out = values_from_preset({"altitude": 90, "definitely_not_a_key": 1})
    assert out["altitude"] == "90"
    assert "definitely_not_a_key" not in out
