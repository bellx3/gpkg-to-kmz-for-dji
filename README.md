# SkyMission Builder (gpkg-to-kmz-for-dji)

## 개요
이 도구는 GPKG 폴리곤 데이터를 DJI 드론용 KML/WPML 기반 KMZ 임무 파일로 대량 변환하는 전문 솔루션입니다. 복잡한 지오메트리 단순화 및 기체별 맞춤형 파라미터 설정을 원클릭으로 처리하여 현장 미션 생성 시간을 획기적으로 단축합니다.

## 핵심 기능
- **대량 자동 변환**: 수백 개의 폴리곤이 포함된 GPKG 파일을 개별 미션 KMZ로 자동 분할 및 명명.
- **기체 최적화**: Mavic 3E, M350 등 DJI 기체별 하드웨어 파라미터(Enum) 자동 주입.
- **지오메트리 단순화**: 드론 컨트롤러 부하 방지를 위한 50cm 단위 폴리곤 단순화(Simplify).
- **정밀 미션 제어**: 고도, 중첩도, 짐벌 피치, 자동 비행 속도 등 상세 파라미터 오버라이드.
- **프리셋 시스템**: 현장별 최적 설정값을 JSON 파일로 관리하여 반복 작업 제거.

## 프로젝트 구조
- `src/core/`: 핵심 변환 및 검사 로직 (Generator, Inspector, Enums)
- `src/gui/`: SkyMission Builder 데스크톱 인터페이스
- `src/templates/`: DJI WPML 표준 KML/WPML 템플릿
- `presets/`: 사용자 정의 미션 프리셋 (JSON)
- `input/`: 처리할 소스 (.gpkg, .kml)
- `output/`: 생성된 결과물 (.kmz)
- `docs/`: 프로젝트 고도화 로드맵 및 매뉴얼

## 설치 및 실행 방법

### 1단계: 필수 라이브러리 설치
```bash
pip install shapely geopandas fiona pyproj pyogrio
```

### 2단계: 어플리케이션 실행
프로젝트 루트 폴더에서 다음을 실행합니다.
```bash
python main.py
```

## 사용 팁 (Workflow)
1. `input/` 폴더에 GPKG 파일을 넣습니다.
2. `python main.py`를 실행하여 UI를 엽니다.
3. 대상 기체(예: Mavic 3E)를 선택하고 '프리셋 불러오기'를 통해 표준 설정값을 로드합니다.
4. '실행' 버튼을 누르면 `output/` 폴더에 미션 파일들이 생성됩니다.

## 검증 및 유지보수
생성된 KMZ 파일의 내부 값을 검증하려면 다음 명령을 사용하세요.
```bash
python src/core/inspector.py [KMZ경로]
```

## 참고
- 본 도구는 DJI WPML 1.0.6 표준을 준수합니다.
- 한글 파일명 및 속성값을 완벽하게 지원합니다.