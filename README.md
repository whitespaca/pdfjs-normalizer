# PDF.js Normalizer GUI

PDF.js에서 일부 페이지만 보이거나 워터마크만 보이는 PDF를, 페이지 이미지 기반의 PDF.js 호환 PDF로 일괄 변환하는 Windows GUI 도구입니다.

## 기능

- 원본 PDF 폴더 선택
- 출력 폴더 선택
- 하위 폴더 포함 일괄 변환
- DPI 설정
- PNG / JPEG 출력 선택
- JPEG 품질 설정
- 동시 작업 수 설정
- 기존 변환본 건너뛰기
- 변환 취소
- 진행률 표시
- 실패 로그 저장
- GitHub Actions Release 빌드 지원

## 권한 있는 문서 전용 워터마크 처리

v1.2.0부터 워터마크 처리 방식이 2개입니다.

| 옵션 | 대상 | 설명 |
|---|---|---|
| 명시적 PDF 워터마크 Artifact 제거 | 워터마크가 PDF content stream의 `/Artifact /Watermark` 블록인 경우 | PDF 객체 단계에서 블록 제거 후 렌더링 |
| 이미지에 합쳐진 연한/컬러 워터마크 제거 시도 | 워터마크가 본문 이미지에 이미 합쳐진 경우 | 렌더링 후 흑백 임계값 변환으로 연한/컬러 픽셀 제거 |

두 번째 옵션은 출력물을 흑백화합니다. 검은 악보/흰 배경 문서에는 적합하지만, 의도적인 연한 회색 요소가 있으면 함께 사라질 수 있습니다.

권장 시작값:

```text
DPI: 200
Format: PNG
Workers: 6
흑백 임계값: 180
```

워터마크가 일부 남으면 임계값을 190~210으로 올려 테스트하세요.
얇은 악보선이나 가사가 끊기면 임계값을 160~175로 낮추세요.

## Windows에서 EXE 빌드

```bat
build_windows.bat
```

완료 후:

```text
dist\PDFjsNormalizerGUI.exe
```

PowerShell 대안:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\build_windows.ps1
```

## GitHub Release 배포

태그를 푸시하면 GitHub Actions가 Windows EXE를 빌드하고 Release에 첨부합니다.

```bat
git tag v1.2.0
git push origin v1.2.0
```

생성 파일:

```text
PDFjsNormalizerGUI.exe
SHA256SUMS.txt
```
