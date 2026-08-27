"""
SkyMission Builder - Safety Validation Module
고도, 카메라 사양, 비행 속도 등에 기반한 미션 안전 및 품질 검증 로직을 제공합니다.
"""

from typing import Dict

# 주요 카메라 센서 사양 데이터 (GSD 및 블러 계산용)
# sensor_width(mm), sensor_height(mm), image_width(px), image_height(px), focal_length(mm)
CAMERA_SPECS = {
    'mavic3e': {
        'sensor_width': 17.3,    # 4/3 CMOS
        'sensor_height': 13.0,
        'image_width': 5280,
        'image_height': 3956,
        'focal_length': 12.3,    # 35mm 환산 24mm 기준 실제 초점거리
        'shutter_speed': 1/2000, # 일반적인 주간 기계식 셔터 권장치
    },
    'mavic3t': {
        'sensor_width': 6.4,     # 1/2 CMOS
        'sensor_height': 4.8,
        'image_width': 4000,
        'image_height': 3000,
        'focal_length': 4.4,     # 35mm 환산 24mm
        'shutter_speed': 1/1000,
    },
    'm30t': {
        'sensor_width': 10.0,    # 1/2 CMOS
        'sensor_height': 7.5,
        'image_width': 4000,
        'image_height': 3000,
        'focal_length': 4.5,
        'shutter_speed': 1/1000,
    },
    'p4r': {
        'sensor_width': 13.2,    # 1인치 CMOS
        'sensor_height': 8.8,
        'image_width': 5472,
        'image_height': 3648,
        'focal_length': 8.8,
        'shutter_speed': 1/2000,
    }
}

DEFAULT_SPEC = CAMERA_SPECS['mavic3e']
DEFAULT_SPEC_NAME = 'mavic3e'

def spec_for(drone_model) -> tuple:
    """(카메라 사양, 근사 여부). 사양 미등록 기종은 mavic3e 로 근사한다.

    지원 기체 25종 중 사양이 있는 것은 위 4종뿐이다 — 없는 사양을 지어내는 대신
    근사임을 함께 돌려주고, 표시 계층이 그 사실을 사용자에게 보여 준다.
    None 도 받는다(CLI 에서 --drone-model 생략 시) — 예전에는 여기서 죽었다.
    """
    model = (drone_model or DEFAULT_SPEC_NAME).lower()
    if model in CAMERA_SPECS:
        return CAMERA_SPECS[model], False
    return DEFAULT_SPEC, True

def calculate_gsd(altitude_m: float, drone_model: str) -> float:
    """
    GSD(Ground Sample Distance, cm/pixel)를 계산합니다.
    (H * Sw) / (F * Iw) * 100
    """
    spec, _ = spec_for(drone_model)
    
    gsd = (altitude_m * spec['sensor_width']) / (spec['focal_length'] * spec['image_width'])
    return gsd * 100  # meter to cm

def calculate_motion_blur(velocity_ms: float, shutter_speed: float) -> float:
    """
    비행 속도와 셔터 스피드에 따른 모션 블러(cm)를 계산합니다.
    Blur = V * S * 100
    """
    return velocity_ms * shutter_speed * 100

def validate_mission(config_dict: Dict) -> Dict:
    """
    미션 설정값을 검증하고 안전 상태와 메시지를 반환합니다.
    
    Returns:
        {
            'status': 'safe' | 'warning' | 'danger',
            'messages': [str, ...],
            'metrics': { 'gsd': float, 'blur': float, 'est_time': str }
        }
    """
    status = 'safe'
    messages = []
    
    drone_model = config_dict.get('drone_model') or 'mavic3e'
    altitude = float(config_dict.get('altitude') or 50)
    velocity = float(config_dict.get('auto_flight_speed') or 5)

    # 1~2. GSD / 모션 블러 계산 (사양 미등록 기종은 mavic3e 근사)
    spec, spec_approx = spec_for(drone_model)
    gsd = calculate_gsd(altitude, drone_model)
    shutter = spec['shutter_speed']
    blur = calculate_motion_blur(velocity, shutter)
    
    # 3. 데이터 품질 판정
    # 규정상 보통 블러는 GSD의 50% 이내여야 이상적, 100% 초과시 Warning
    if blur > gsd:
        status = 'danger'
        messages.append(f"위험: 모션 블러({blur:.2f}cm)가 GSD({gsd:.2f}cm)를 초과합니다. 속도를 줄이거나 셔터 스피드를 높이세요.")
    elif blur > gsd * 0.5:
        if status != 'danger':
            status = 'warning'
        messages.append(f"주의: 모션 블러({blur:.2f}cm)가 GSD의 50%를 초과하여 이미지가 흐려질 수 있습니다.")
    
    # 4. 고도 및 물리적 제한
    if altitude < 10:
        status = 'danger'
        messages.append("위험: 비행 고도가 너무 낮습니다 (10m 미만). 충돌 위험이 매우 높습니다.")
    elif altitude > 150:
        if status != 'danger':
            status = 'warning'
        messages.append("주의: 법적 허용 고도(150m)를 초과했습니다. 승인 여부를 확인하세요.")
        
    if velocity > 15:
        status = 'danger'
        messages.append("위험: 비행 속도가 너무 빠릅니다 (15m/s 초과). 기체 제어가 어려울 수 있습니다.")

    # 5. 결과 요약
    if not messages:
        messages.append("미션 설정이 안전하며 양호한 데이터 품질이 예상됩니다.")
    if spec_approx:
        messages.append(f"참고: {drone_model} 의 카메라 사양이 등록되지 않아 "
                        f"GSD/블러는 {DEFAULT_SPEC_NAME} 사양으로 근사한 값입니다.")

    return {
        'status': status,
        'messages': messages,
        'metrics': {
            'gsd': round(gsd, 2),
            'blur': round(blur, 2),
            'shutter': f"1/{int(1/shutter)}",
            'spec_model': DEFAULT_SPEC_NAME if spec_approx else drone_model.lower(),
            'spec_approx': spec_approx,
        }
    }
