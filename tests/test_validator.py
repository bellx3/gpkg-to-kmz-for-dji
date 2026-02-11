import pytest
from src.core.validator import calculate_gsd, calculate_motion_blur, validate_mission

def test_calculate_gsd():
    # Mavic 3E at 100m
    # Sw=17.3, F=12.3, Iw=5280
    # GSD = (100 * 17.3) / (12.3 * 5280) * 100 = 2.664...
    gsd = calculate_gsd(100, 'mavic3e')
    assert 2.6 < gsd < 2.7

def test_calculate_motion_blur():
    # 5m/s at 1/2000s shutter
    # Blur = 5 * (1/2000) * 100 = 0.25 cm
    blur = calculate_motion_blur(5, 1/2000)
    assert blur == 0.25

def test_validate_mission_safe():
    config = {
        'drone_model': 'mavic3e',
        'altitude': 100,
        'auto_flight_speed': 5
    }
    result = validate_mission(config)
    assert result['status'] == 'safe'
    assert len(result['messages']) >= 1

def test_validate_mission_danger_blur():
    config = {
        'drone_model': 'mavic3t', # Smaller sensor, lower focal length
        'altitude': 20, # Low altitude = low GSD
        'auto_flight_speed': 15 # High speed = high blur
    }
    result = validate_mission(config)
    # GSD at 20m for M3T: (20 * 6.4) / (4.4 * 4000) * 100 = 0.72 cm
    # Blur at 15m/s for M3T: 15 * (1/1000) * 100 = 1.5 cm
    # 1.5 > 0.72 -> danger
    assert result['status'] == 'danger'
    assert any("모션 블러" in m for m in result['messages'])

def test_validate_mission_altitude_warning():
    config = {
        'drone_model': 'mavic3e',
        'altitude': 150,
        'auto_flight_speed': 5
    }
    result = validate_mission(config)
    assert result['status'] == 'warning'
    assert any("고도(120m)를 초과" in m for m in result['messages'])
