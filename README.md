# PolyPDF

한글 PDF 뷰어·편집·발표 도구 (PyQt6 + PyMuPDF). 책갈피 탐색, 다중 검색(FTS5),
편집모드 주석(선·도형·글쓰기·지시선·이미지), 전체화면 발표(펜·포인터·녹화·하이퍼링크
미디어 재생), 단어장(OCR·TTS) 기능을 제공합니다.

> 전체 설계·변경 이력(SOT): 상위 폴더의 `통합 PDF 연계 탐색 및 히스토리 관리 시스템.md`

## 실행 / 빌드

```powershell
pip install -r requirements.txt
python main.py            # 개발 실행 (또는 .\run.bat)
.\build_ci.bat            # PyInstaller onedir 빌드 → dist\PolyPDF\PolyPDF.exe
```

### 선택 런타임(전체 기능)
`build_ci.bat` 은 아래가 **있으면 자동 동봉**하고, 없으면 그 기능만 비활성화한 채 빌드됩니다.
- `ffmpeg.exe` (저장소 루트) — 전체화면 녹화·동영상 하이퍼링크 재생
- `tesseract\` — 스캔 PDF OCR(단어장)
- `nltk_data\` — WordNet(단어장 뜻풀이)

이 셋은 용량이 커서 **git 에 포함하지 않습니다**(`.gitignore`). 각자 받아 두면 됩니다:
- ffmpeg: 공식 빌드의 `ffmpeg.exe` 를 저장소 루트에 복사
- Tesseract: portable 설치본을 `tesseract\` 로 (`tesseract.exe` + `tessdata\`)
- NLTK: `python -m nltk.downloader -d nltk_data wordnet omw-1.4`

## 설정 저장 위치 (업데이트해도 유지)
사용자 설정은 **프로그램 폴더가 아니라 사용자 프로필**에 저장되어, 프로그램을 교체(업데이트)해도
유지됩니다.
- `%APPDATA%\LocalTools\PolyPDF\settings.json` — 즐겨찾기·글쓰기 스타일·펜·환경설정 등
- 같은 폴더의 `index.db`(검색 인덱스)·스크린샷 / 창 레이아웃은 레지스트리

## 배포용 기본값 프로파일
설정 메뉴 →
- **현재 설정을 기본값으로 저장(배포용)…** : 현재 설정·스타일을 `default_settings.json`(프로그램 폴더)로 저장.
  개인 항목(즐겨찾기·최근 폴더·세션·머신 경로)은 제외됩니다. 이 파일을 배포본에 함께 넣으면
  **새 설치 시 그 설정으로 시작**합니다.
- **설정 초기화(기본값으로)…** : 위 기본값(없으면 공장값)으로 되돌립니다(개인 항목 유지, 재시작).

---

## GitHub 배포 / 자동화

### 무엇을 올리나 (커밋 대상)
- 소스: `viewer/`, `main.py`, `test_*.py`
- 빌드/실행: `build_ci.bat`, `run.bat`, `requirements.txt`
- 에셋: `resources/`(아이콘·사전 CSV)
- 메타: `README.md`, `.gitignore`, `.github/`, (선택) `default_settings.json`

### 올리지 않는 것 (`.gitignore`)
`.venv/`, `build/`, `dist/`, `__pycache__/`, 빌드 로그·selftest db, 로컬 `index.db`/`settings.json`,
그리고 대용량 런타임 바이너리 `ffmpeg.exe`·`tesseract/`·`nltk_data/`.

### 최초 1회
```powershell
git init; git add .; git commit -m "PolyPDF 1.88.0"
git branch -M main
gh repo create PolyPDF --private --source . --remote origin --push   # gh CLI (또는 웹에서 repo 생성 후 remote add)
```

### 자동화 (.github/workflows)
- **ci.yml** — push/PR 마다 오프스크린 GUI 회귀 테스트 실행(자체 PDF 생성 테스트만).
- **release.yml** — `v*` 태그를 push 하면 Windows 에서 빌드 → zip → **GitHub Release 자동 생성**.
  (ffmpeg/Tesseract/NLTK 는 워크플로가 choco/다운로드로 best-effort 동봉)

릴리스 내기:
```powershell
git tag v1.88.0
git push origin v1.88.0        # → release.yml 이 빌드·업로드
```

### 권장(가장 안정적): 로컬 빌드 → 릴리스 업로드
바이너리(ffmpeg/tesseract)가 갖춰진 개발 PC에서:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\publish_release.ps1 -Tag v1.88.0 -Build
```
`build_ci.bat` 로 빌드 → `dist\PolyPDF` 를 zip → `gh release create` 로 업로드합니다.

### 평소 업데이트 관리
```powershell
git add -A; git commit -m "fix: ..."; git push      # 소스 갱신(설정/스타일 영향 없음)
```
사용자 설정은 `%APPDATA%` 에 있으므로, 새 빌드를 받아도 기존 즐겨찾기·스타일이 그대로 유지됩니다.

## 단축키
| 단축키 | 동작 |
|--------|------|
| Ctrl+O | 폴더 열기 |
| Ctrl+F | 검색바 포커스 |
| F3 / Shift+F3 | 다음/이전 매치 |
| ↓ / ↑ / PgDn / PgUp | 페이지 이동 (2장 보기 ±2) |
| Home / End | 첫/마지막 페이지 |
| Ctrl+Wheel | 줌 |
| Ctrl+Shift+S | 스크린샷 캡처 |
| Ctrl+S | 스크린샷 PDF 일괄 저장 |
| F5 | 발표 보기(전체화면) |
| Ctrl+Q | 종료 |
