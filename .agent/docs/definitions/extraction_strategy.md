# 포맷별 추출 전략 정의서 (Extraction Strategy)

## 1. 개요
본 문서는 각 문서 포맷별로 마크다운 언어로의 변환을 위한 기술적 전략을 정의합니다.

## 2. 포맷별 상세 전략

### 2.1 HWP / HWPX
- **기본 전략**: `hwp5html` 또는 XML 트리 분석을 통해 구조적 파싱 수행.
- **텍스트**: 스타일 정보(Heading)를 활용하여 마크다운 헤더(`#`, `##`) 결정.
- **이미지**: `BinData` 내 바이너리 추출 및 로컬 저장 후 마크다운 링크 생성.
- **표**: HTML 및 XML Table 노드를 분석하여 마크다운 GFM(GitHub Flavored Markdown) 테이블로 변환.

### 2.2 DOCX (Microsoft Word)
- **라이브러리**: `python-docx`
- **전략**: Paragraph 객체 순회 및 스타일 이름(Heading 1, 2...) 매핑. 
- **이미지**: `document.part.related_parts` 내 이미지 바이너리 추출.

### 2.3 PDF (Portable Document Format)
- **라이브러리**: `PyMuPDF (fitz)`
- **전략**: 
  - 텍스트 요소를 좌표 기반으로 분석하여 블록 단위 마크다운 변환.
  - 표 감지가 어려운 경우 해당 영역을 이미지로 캡처하여 LLM 이미지 분석 활용.
- **이미지**: `page.get_images()`를 통해 원본 이미지 파일 추출.

### 2.4 Excel (XLSX)
- **라이브러리**: `pandas`, `openpyxl`
- **전략**: 각 시트(Sheet)를 순회하며 데이터프레임으로 로드 후 `to_markdown()` 변환.
- **이미지**: 시트 내 플로팅 객체(Floating Objects) 지원 여부 검토 중.

### 2.5 PPTX (PowerPoint)
- **라이브러리**: `python-pptx`
- **전략**: 슬라이드별 Shape(Textbox, Picture) 순회. 각 슬라이드의 시작을 `---` (Separator)와 슬라이드 번호 헤더로 표시.

---

## 3. 공통 개선 사항
- 모든 파서의 텍스트는 UTF-8 인코딩을 준수함.
- 이미지가 없는 경우를 대비한 Fallback 로직 구현.
