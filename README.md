# gpkg-to-kmz-for-dji

개요
- 이 도구는 GPKG 폴리곤 입력을 바탕으로 KML+WPML을 포함한 KMZ 임무 파일을 생성합니다.
- 템플릿(template.kml, waylines.wpml)을 기반으로 고도/겹침/속도 등 주요 파라미터를 UI 또는 명령행(옵션)으로 덮어쓸 수 있습니다.

필수 준비 사항
- 운영체제: Windows
- Python: 3.9 이상 권장
- 주요 라이브러리: shapely, geopandas, fiona, pyproj 등
  - 설치 예시 (PowerShell):
    - pip install shapely geopandas fiona pyproj
  - 주의: GeoPandas/Fiona는 GDAL 등 네이티브 의존성이 있어 Conda 환경에서 설치 시 더 안정적입니다.

폴더 구조
- input/ : 처리할 .gpkg 파일들을 넣는 폴더
- output/ : 생성된 .kmz 결과가 저장되는 폴더
- template.kml, waylines.wpml : 임무 템플릿 파일
- kml_setting_v2.py : KMZ 생성 메인 스크립트(배치 처리용)
- ui_desktop.py : 간단 데스크톱 UI 실행 파일
- inspect_kmz.py : 생성된 KMZ 파일 내 KML/WPML 값을 검사하는 도구

실행 방법 1) 데스크톱 UI로 실행
- PowerShell에서 프로젝트 폴더로 이동: cd d:\00_미션저작도구
- 데스크톱 UI 실행: python ui_desktop.py
- 화면에서 다음과 같은 값들을 입력/조정 후 실행합니다.
  - 고도(ellipsoid/height), 촬영고도(globalShootHeight), 지면기준고도(surfaceRelativeHeight)
  - 마진(margin)
  - 겹침(카메라 H/W, 라이다 H/W)
  - 자동비행속도(autoFlightSpeed), 전환속도(globalTransitionalSpeed)
  - 이륙안전고도(takeOffSecurityHeight)
- 실행하면 input 폴더의 GPKG 파일들을 처리하여 output 폴더에 KMZ를 생성합니다.

실행 방법 2) 명령행(배치 처리)
- 기본 실행:
  - python kml_setting_v2.py --input d:\00_미션저작도구\input --output d:\00_미션저작도구\output
- 주요 옵션(예시):
  - --altitude 160
  - --shoot_height 160
  - --margin 40
  - --overlap_camera_h 80 --overlap_camera_w 70
  - --overlap_lidar_h 80 --overlap_lidar_w 70
  - --auto_flight_speed 14
  - --global_transitional_speed 15
  - --takeoff_security_height 20
- 전체 옵션은 도움말로 확인하세요: python kml_setting_v2.py -h

결과 확인 (검증)
- 특정 KMZ 검사:
  - python inspect_kmz.py d:\00_미션저작도구\output\b_0.kmz
- 검사 내용:
  - KML의 ellipsoidHeight, height, globalShootHeight, surfaceRelativeHeight, margin, overlap(카메라/라이다), 속도/이륙안전고도 값
  - WPML의 autoFlightSpeed, globalTransitionalSpeed, takeOffSecurityHeight 값
  - WPML에서 각 웨이포인트의 executeHeight(개수와 샘플) 요약
- 참고: 현재 WPML 템플릿에는 globalShootHeight/surfaceRelativeHeight 태그가 없을 수 있습니다. 이 경우 KML 수준에서만 표시되며, WPML은 각 웨이포인트의 executeHeight로 고도가 반영됩니다.

예시 명령 모음
- UI 실행: python ui_desktop.py
- 배치 생성(옵션 포함):
  - python kml_setting_v2.py --input d:\00_미션저작도구\input --output d:\00_미션저작도구\output --altitude 160 --shoot_height 160 --margin 40 --overlap_camera_h 80 --overlap_camera_w 70 --overlap_lidar_h 80 --overlap_lidar_w 70 --auto_flight_speed 14 --global_transitional_speed 15 --takeoff_security_height 20
- KMZ 검사: python inspect_kmz.py d:\00_미션저작도구\output\b_0.kmz

자주 묻는 질문 / 문제 해결
- GeoPandas/Fiona 설치 오류:
  - Conda 사용을 권장합니다. 예: conda install geopandas
- DeprecationWarning(unary_union 관련):
  - 코드에서 shapely.ops.unary_union을 사용하도록 개선되어 경고가 제거되었습니다.
- WPML에 globalShootHeight/surfaceRelativeHeight가 없음:
  - 현재 템플릿에 해당 태그가 없으면 정상입니다. 필요 시 템플릿 스키마 확장을 통해 추가 가능하며, executeHeight로 웨이포인트 고도를 정확히 반영합니다.
- 속도/고도/겹침 값이 반영되지 않는 경우:
  - 옵션 이름과 값이 정확한지 확인하고, python kml_setting_v2.py -h로 지원 옵션을 다시 확인하세요.

참고
- 출력 KMZ는 한글 파일명을 지원합니다.
- 생성된 KMZ에는 template.kml과 waylines.wpml가 포함됩니다.