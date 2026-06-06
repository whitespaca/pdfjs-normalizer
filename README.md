# PDF.js 호환 PDF 일괄 변환기

PDF.js에서 워터마크만 보이거나 페이지가 비어 보이는 이미지 기반 PDF를 웹 임베딩용으로 정규화하는 Windows GUI 앱입니다.

## 동작 방식

각 PDF 페이지를 지정 DPI로 렌더링한 뒤, 그 이미지를 새 PDF 페이지에 삽입합니다.

- JBIG2 등 PDF.js 호환성 문제가 있는 내부 이미지 필터 제거
- PDF JavaScript / OpenAction / 첨부파일 / 폼 같은 동적 요소 제거
- 원본 폴더 구조 유지
- 기존 변환본 건너뛰기 가능
- 변환 로그 TSV 생성

## 권장 설정

| 용도 | DPI | 이미지 형식 |
|---|---:|---|
| 웹 임베딩 기본 | 200 | PNG |
| 파일 크기 절감 | 180~200 | JPEG 95 |
| 악보 가독성 우선 | 220 | PNG 또는 JPEG 95 |
| 인쇄 품질 우선 | 300 | PNG |

대량 변환 전에는 20~30개 샘플로 DPI와 파일 크기를 비교하세요.

## 개발 환경 실행

```bat
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

## Windows EXE 빌드

1. Windows PC에 Python 3.11 이상 설치
2. 이 폴더에서 `build_windows.bat` 실행
3. 결과물 확인

```text
dist\PDFjsNormalizerGUI.exe
```

## 사용 순서

1. `원본 PDF 폴더` 선택
2. `변환본 저장 폴더` 선택
3. DPI / 이미지 형식 / 동시 작업 수 설정
4. `변환 시작`
5. 웹사이트에는 변환본 PDF만 임베딩

## 출력 파일명

기본값은 원본 파일명 뒤에 `-pdfjs`를 붙입니다.

예시:

```text
109-파일.pdf
109-파일-pdfjs.pdf
```

접미사를 비우면 원본과 같은 파일명으로 출력 폴더에 저장됩니다.

## 주의사항

- 출력 폴더를 원본 폴더와 동일하게 지정하지 마세요.
- 전체 페이지를 이미지화하므로 텍스트 선택/검색은 유지되지 않습니다.
- 악보 PDF 등 본문이 원래 이미지 기반인 경우에는 실질 손실이 작습니다.
- PNG는 품질이 안정적이지만 파일이 커질 수 있습니다.
- JPEG는 파일 크기가 작아질 수 있지만 아주 미세한 압축 흔적이 생길 수 있습니다.


## Windows build troubleshooting

If `build_windows.bat` shows broken Korean text or commands such as `evel`, `m venv`, or `clean --onefile`, use this fixed package. The batch file is ASCII-only and uses Windows CRLF line endings.

Recommended command:

```bat
build_windows.bat
```

PowerShell alternative:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\build_windows.ps1
```
