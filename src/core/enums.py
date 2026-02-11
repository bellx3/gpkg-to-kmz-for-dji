"""
DJI 드론 및 페이로드 열거 값(enum values) 관리 모듈
이 모듈은 DJI 드론과 페이로드 모델의 enum 값을 제공합니다.
"""

from typing import Tuple

def get_drone_enum_values(drone_model: str) -> Tuple[int, int]:
    """
    지정된 모델에 대한 DJI 드론 enum 값을 가져옵니다.
    
    Args:
        drone_model (str): 드론 모델 식별자
        
    Returns:
        Tuple[int, int]: (droneEnumValue, droneSubEnumValue)
    """
    # DJI Cloud API 및 WPML 표준 명세 기반 enum 맵핑
    model_values = {
        # Mavic 3 Enterprise Series (77)
        'mavic3e': (77, 0),
        'mavic3t': (77, 1),
        'mavic3m': (77, 2),
        
        # Matrice 30 Series (67)
        'm30': (67, 0),
        'm30t': (67, 1),
        
        # Matrice 300/350 Series
        'm300': (60, 0),
        'm350': (89, 0),
        
        # Dock 2 전용 기체 (Matrice 3D)
        'm3d': (91, 0),
        'm3td': (91, 1),
        
        # 미니 및 에어 시리즈 (엔터프라이즈 기능 지원 기상)
        'mini3pro': (76, 0),
        'mini3': (96, 0),
        'air2s': (68, 0),
        'mavic3': (73, 0),
        'mavic3_cine': (74, 0),

        # Phantom 4 Series
        'p4r': (28, 0),
        'p4m': (44, 0),

        # 엔터프라이즈 레거시
        'm210rtk_v2': (41, 0),
        'm600pro': (13, 0),
        'inspire2': (18, 0),

        # 산업용/농업용 특수 기체
        'flycart30': (103, 0),
        'agras_t50': (101, 0),
        'agras_t40': (91, 0),
        'agras_t30': (69, 0),
        'agras_t20p': (92, 0),
        'agras_t10': (63, 0),
        
        'unknown': (0, 0)
    }
    
    return model_values.get(drone_model.lower(), (0, 0))


def get_supported_drone_models() -> list[str]:
    """
    지원하는 전체 드론 모델 목록을 가나다순으로 반환합니다.
    """
    # get_drone_enum_values 내부의 키 목록과 동일하게 유지
    models = [
        'mavic3e', 'mavic3t', 'mavic3m',
        'm30', 'm30t', 'm300', 'm350',
        'm3d', 'm3td',
        'p4r', 'p4m',
        'mini3pro', 'mini3', 'air2s',
        'mavic3', 'mavic3_cine',
        'm210rtk_v2', 'm600pro', 'inspire2',
        'flycart30', 'agras_t50', 'agras_t40', 'agras_t30', 'agras_t20p', 'agras_t10'
    ]
    return sorted(models)


def get_payload_enum_values(drone_model: str) -> Tuple[int, int]:
    """
    지정된 드론 모델에 대한 DJI 페이로드 enum 값을 가져옵니다.
    
    Args:
        drone_model (str): 드론 모델 식별자
        
    Returns:
        Tuple[int, int]: (payloadEnumValue, payloadPositionIndex)
    """
    # 페이로드 맵핑 (드론 모델별 기본 장착 카메라 기준)
    payload_values = {
        'mavic3e': (65, 0),      # M3E Wide
        'mavic3t': (66, 0),      # M3T Thermal
        'mavic3m': (89, 0),      # M3M Multispectral
        
        'm30': (75, 0),
        'm30t': (76, 0),
        
        'm300_h20': (52, 0),
        'm300_h20t': (53, 0),
        'm300_p1': (61, 0),
        'm300_l1': (62, 0),
        
        'm350_h20': (52, 0),
        'm350_h20t': (53, 0),
        'm350_p1': (61, 0),
        'm350_l1': (62, 0),
        'm350_l2': (114, 0),     # Zenmuse L2
        'm350_h30': (120, 0),    # Zenmuse H30
        'm350_h30t': (121, 0),   # Zenmuse H30T
        
        'm3d': (91, 0),
        'm3td': (92, 0),
        
        'p4r': (39, 0),
        'p4m': (50, 0),
        'mini3pro': (73, 0),
        'mini3': (88, 0),
        'air2s': (64, 0),
        'mavic3': (67, 0),
        'flycart30': (95, 0),
        
        'unknown': (0, 0)
    }
    
    # 모델명을 소문자로 변환하여 조회
    # M300/M350의 경우 기본 페이로드를 H20으로 가정 (필요시 수정)
    if drone_model.lower().startswith('m300'):
        return payload_values.get('m300_h20', (0, 0))
    if drone_model.lower().startswith('m350'):
        return payload_values.get('m350_h20', (0, 0))
        
    return payload_values.get(drone_model.lower(), (0, 0))
