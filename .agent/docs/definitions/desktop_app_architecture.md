# 설치형 SW 아키텍처 (Desktop App Architecture)

## 1. 개요
로컬 환경에서 독립적으로 실행되며, 복잡한 설치 과정 없이 작동하는 데스크톱 애플리케이션 구조를 정의합니다.

## 2. 구성 요소

### 2.1 Interface (GUI)
- **프레임워크**: `PySide6` (Python용 Qt)
- **주요 기능**:
  - 드래그 앤 드롭 파일 로더
  - 변환 대기열(Queue) 관리
  - LLM API 키 설정 및 저장 (로컬 암호화)
  - 변환 결과 미리보기 (Markdown Viewer)

### 2.2 Core Engine (Backend)
- **로직**: `apps/worker`에 구현된 파서 모듈 재사용.
- **런타임**: 내장된 Python 인터프리터 (PyInstaller 번들).

### 2.3 Local Storage
- **파일**: 변환된 마크다운 및 추출된 이미지 저장용 로컬 폴더.
- **설정**: SQLite 또는 JSON 파일을 활용한 사용자 환경 설정 저장.

## 3. 통신 방식 (IPC)
- GUI 루프와 파서 루프를 별도의 쓰레드(Thread)로 분리하여 변환 중 UI 멈춤 방지.
- `Signal/Slot` 패턴을 활용하여 변환 진행률과 로그 실시간 전달.

## 4. 배포 모델
- **대상 OS**: Windows (우선), macOS (향후)
- **패키징**: `PyInstaller` 또는 `Nuitka`를 사용한 단일 `.exe` 실행 파일 제작.

---

## 5. 보안 및 권한
- 로컬 파일 시스템 읽기/쓰기 권한 필요.
- LLM API 통신을 위한 네트워크 연결 필요.
