# PDFjsNormalizerGUI

PDF.js에서 일부 PDF가 워터마크만 보이거나 빈 페이지로 보이는 문제를 줄이기 위한 Windows GUI 배치 변환기입니다.

이 도구는 PDF 페이지를 이미지로 렌더링한 뒤 새 PDF로 재생성합니다. JBIG2 등 PDF.js에서 불안정할 수 있는 내부 이미지 인코딩을 우회하는 목적입니다.

## 주요 기능

- 폴더 단위 PDF 일괄 변환
- 하위 폴더 구조 유지
- DPI 설정
- PNG / JPEG 선택
- JPEG 품질 설정
- 동시 작업 수 설정
- 기존 변환본 건너뛰기
- 변환 취소
- 변환 로그 저장
- 권한 있는 문서 전용: 명시적 PDF 워터마크 Artifact 제거 후 변환

## 워터마크 제거 옵션

`명시적 PDF 워터마크 Artifact 제거 후 변환` 옵션은 다음과 같이 PDF 내부에 별도 marked-content block으로 표시된 워터마크만 제거합니다.

```text
/Artifact <</Subtype /Watermark /Type /Pagination >>BDC
...
EMC
```

즉, 이미지에 이미 합쳐진 워터마크나 페이지 하단의 저작권 문구는 제거하지 않습니다. 권한이 있는 PDF에만 사용하세요.

## 권장 설정

### i7-12700F / RAM 32GB 기준

```text
DPI: 200
이미지 형식: PNG
동시 작업 수: 6
```

속도와 용량을 우선하면:

```text
DPI: 200
이미지 형식: JPEG
JPEG 품질: 95
동시 작업 수: 8
```

## Windows에서 EXE 빌드

```bat
build_windows.bat
```

결과물:

```text
dist\PDFjsNormalizerGUI.exe
```

PowerShell 대체 방식:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\build_windows.ps1
```

## GitHub Release 배포

저장소에 업로드 후 태그를 푸시하면 GitHub Actions가 Windows EXE를 빌드하고 Release에 첨부합니다.

```bat
git tag v1.1.0
git push origin v1.1.0
```

Release 첨부 파일:

```text
PDFjsNormalizerGUI.exe
SHA256SUMS.txt
```

수동 실행도 가능합니다.

```text
Repository -> Actions -> Build Windows EXE Release -> Run workflow
```
