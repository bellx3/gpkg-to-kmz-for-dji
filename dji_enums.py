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
    # 샘플 파일에서 확인된 정확한 드론 enum 값 적용
    model_values = {
        'mavic3e': (77, 0),      # Mavic 3E
        'mavic3t': (79, 0),      # Mavic 3T
        'mavic3m': (98, 0),      # Mavic 3M
        'm30': (83, 0),          # Matrice 30
        'm30t': (89, 0),         # Matrice 30T
        'm300': (60, 0),         # Matrice 300 RTK
        'm350': (99, 0),         # Matrice 350 RTK
        'p4r': (28, 0),          # Phantom 4 RTK
        'p4m': (44, 0),          # Phantom 4 Multispectral
        'm210rtk_v2': (41, 0),   # Matrice 210 RTK V2
        'm600pro': (13, 0),      # Matrice 600 Pro
        'inspire2': (18, 0),     # Inspire 2
        'mavic2pro': (26, 0),    # Mavic 2 Pro
        'mavic2zoom': (27, 0),   # Mavic 2 Zoom
        'mavic2enterprise': (30, 0), # Mavic 2 Enterprise
        'mavic2enterprise_dual': (38, 0), # Mavic 2 Enterprise Dual
        'mavic2enterprise_advanced': (67, 0), # Mavic 2 Enterprise Advanced
        'mavicair2': (58, 0),    # Mavic Air 2
        'air2s': (68, 0),        # DJI Air 2S
        'mini2': (61, 0),        # DJI Mini 2
        'mini_se': (70, 0),      # DJI Mini SE
        'mini3pro': (76, 0),     # DJI Mini 3 Pro
        'mini3': (96, 0),        # DJI Mini 3
        'mavic3': (73, 0),       # Mavic 3
        'mavic3_cine': (74, 0),  # Mavic 3 Cine
        'avata': (88, 0),        # DJI Avata
        'fpv': (66, 0),          # DJI FPV
        'm30_dock': (83, 1),     # Matrice 30 Dock Version
        'm30t_dock': (89, 1),    # Matrice 30T Dock Version
        'mavic3e_cn': (77, 1),   # Mavic 3E (China)
        'mavic3t_cn': (79, 1),   # Mavic 3T (China)
        'mavic3m_cn': (98, 1),   # Mavic 3M (China)
        'm300_cn': (60, 1),      # Matrice 300 RTK (China)
        'm350_cn': (99, 1),      # Matrice 350 RTK (China)
        'agras_t10': (63, 0),    # Agras T10
        'agras_t16': (31, 0),    # Agras T16
        'agras_t20': (59, 0),    # Agras T20
        'agras_t30': (69, 0),    # Agras T30
        'agras_t40': (91, 0),    # Agras T40
        'agras_t20p': (92, 0),   # Agras T20P
        'agras_t50': (101, 0),   # Agras T50
        'agras_t25': (102, 0),   # Agras T25
        'unknown': (0, 0)        # Default/Unknown
    }
    
    # 모델명을 소문자로 변환하여 조회
    return model_values.get(drone_model.lower(), (0, 0))


def get_payload_enum_values(drone_model: str) -> Tuple[int, int]:
    """
    지정된 드론 모델에 대한 DJI 페이로드 enum 값을 가져옵니다.
    
    Args:
        drone_model (str): 드론 모델 식별자
        
    Returns:
        Tuple[int, int]: (payloadEnumValue, payloadPositionIndex)
    """
    # 샘플 파일에서 확인된 정확한 페이로드 enum 값 적용
    payload_values = {
        'mavic3e': (65, 0),      # Mavic 3E Camera
        'mavic3t': (66, 0),      # Mavic 3T Camera (Thermal)
        'mavic3m': (89, 0),      # Mavic 3M Camera (Multispectral)
        'm30': (75, 0),          # Matrice 30 Camera
        'm30t': (76, 0),         # Matrice 30T Camera (Thermal)
        'm300_h20': (52, 0),     # Zenmuse H20
        'm300_h20t': (53, 0),    # Zenmuse H20T
        'm300_xt2': (26, 0),     # Zenmuse XT2
        'm300_z30': (20, 0),     # Zenmuse Z30
        'm300_p1': (61, 0),      # Zenmuse P1
        'm300_l1': (62, 0),      # Zenmuse L1
        'm350_h20': (52, 0),     # Zenmuse H20 (M350)
        'm350_h20t': (53, 0),    # Zenmuse H20T (M350)
        'm350_p1': (61, 0),      # Zenmuse P1 (M350)
        'm350_l1': (62, 0),      # Zenmuse L1 (M350)
        'm350_h20n': (87, 0),    # Zenmuse H20N (M350)
        'p4r': (39, 0),          # Phantom 4 RTK Camera
        'p4m': (50, 0),          # Phantom 4 Multispectral Camera
        'mavic2pro': (28, 0),    # Mavic 2 Pro Camera
        'mavic2zoom': (29, 0),   # Mavic 2 Zoom Camera
        'mavic2enterprise': (33, 0), # Mavic 2 Enterprise Camera
        'mavic2enterprise_dual': (41, 0), # Mavic 2 Enterprise Dual Camera
        'mavic2enterprise_advanced': (60, 0), # Mavic 2 Enterprise Advanced Camera
        'mavicair2': (58, 0),    # Mavic Air 2 Camera
        'air2s': (64, 0),        # DJI Air 2S Camera
        'mini2': (59, 0),        # DJI Mini 2 Camera
        'mini_se': (63, 0),      # DJI Mini SE Camera
        'mini3pro': (73, 0),     # DJI Mini 3 Pro Camera
        'mini3': (88, 0),        # DJI Mini 3 Camera
        'mavic3': (67, 0),       # Mavic 3 Camera
        'mavic3_cine': (67, 0),  # Mavic 3 Cine Camera (Same as Mavic 3)
        'avata': (79, 0),        # DJI Avata Camera
        'fpv': (68, 0),          # DJI FPV Camera
        'unknown': (0, 0)        # Default/Unknown
    }
    
    # 모델명을 소문자로 변환하여 조회
    # M300/M350의 경우 기본 페이로드를 H20으로 가정 (필요시 수정)
    if drone_model.lower().startswith('m300'):
        return payload_values.get('m300_h20', (0, 0))
    if drone_model.lower().startswith('m350'):
        return payload_values.get('m350_h20', (0, 0))
        
    return payload_values.get(drone_model.lower(), (0, 0))
