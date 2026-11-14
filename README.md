<!-- moved-to-polypinax -->
> **이 저장소는 옮겼습니다 — PolyPDF 는 이제 PolyPinax 입니다: https://github.com/kdjeong777-ops/PolyPinax**  
> 설치된 앱은 앱 안 업데이트로 새 이름·새 주소로 넘어갑니다(설정·색인 그대로). 이 저장소는 보관만 합니다.
>
> **This repository has moved — PolyPDF is now PolyPinax: https://github.com/kdjeong777-ops/PolyPinax**  
> Installed copies move over through the in-app update (settings and index carry over). This repository is archived.

# PolyPinax

**폴더째 펼쳐 보는 PDF·사진 뷰어** — *A PDF & photo viewer that opens whole folders.*

> **PolyPDF 가 PolyPinax 로 이름을 바꿨습니다.** 설정·검색 색인·기본 앱·작업 표시줄 고정·가상 프린터는 그대로 이어지고,
> 1.1.0-beta.14 부터 설치 폴더·실행 파일(`PolyPinax.exe`)·설정 폴더·저장소 주소(이 저장소, 옛 `kdjeong777-ops/PolyPDF` 는 보관)도 새 이름입니다 —
> 깔린 옛 판은 앱 안 업데이트 한 번으로 저절로 넘어옵니다. 그리스어 *pinax* 는 '그림을 그린 판' 이자 '목록'
> (알렉산드리아 도서관의 첫 장서 목록 *Pinakes*)이라, 여러(*poly*) 판을 엮은 목록처럼 폴더 속 PDF·사진을 한곳에서 찾고 보고 고칩니다.

한글 PDF 뷰어·편집·발표 도구 (PyQt6 + PyMuPDF). 책갈피 탐색, 다중 검색(FTS5),
편집모드 주석(선·도형·글쓰기·지시선·이미지), 전체화면 발표(펜·포인터·녹화·하이퍼링크
미디어 재생), 단어장(OCR·TTS) 기능을 제공합니다.

> 전체 설계·변경 이력(SOT): 상위 폴더의 `통합 PDF 연계 탐색 및 히스토리 관리 시스템.md`

## 실행 / 빌드

```powershell
pip install -r requirements.txt
python scripts/i18n.py compile   # 언어팩 .po → .mo (Babel 필요: pip install babel==2.18.0). 한국어만 쓰면 생략 가능
python main.py            # 개발 실행 (또는 .\run.bat)
.\build_ci.bat            # PyInstaller onedir 빌드 → dist\PolyPinax\PolyPinax.exe
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

가상 프린터 동봉물 `printer\bin`(포트 모니터 `polypdfmon.dll`·Ghostscript `gs\`)은 **CI 만 만듭니다**
(`release.yml` 의 'Build printer port monitor'·'Stage Ghostscript' — 원본은 `printer\monitor_src`, Ghostscript 는 Artifex `gs10080` 릴리스).
로컬 빌드에는 없으므로 그 빌드로는 가상 프린터를 설치할 수 없습니다.

## 설정 저장 위치 (업데이트해도 유지)
사용자 설정은 **프로그램 폴더가 아니라 사용자 프로필**에 저장되어, 프로그램을 교체(업데이트)해도
유지됩니다.
- `%APPDATA%\LocalTools\PolyPinax\settings.json` — 즐겨찾기·글쓰기 스타일·펜·환경설정 등 (옛 판의 `LocalTools\PolyPDF` 는 첫 실행 때 이 이름으로 옮겨짐)
- 같은 폴더의 `index.db`(검색 인덱스)·스크린샷 / 창 레이아웃은 레지스트리

## 무설치(휴대용) 판
릴리스의 `PolyPinax-<버전>-win64-portable.zip` 을 쓰기 가능한 폴더(USB 등)에 풀고 `PolyPinax\PolyPinax.exe` 를 실행합니다.
- `PolyPinax.exe` 옆의 `PolyPinax.portable` 표식(옛 판의 `PolyPDF.portable` 도 알아봄)이 있으면 설정·색인·사전·스크린샷·창 레이아웃을 **그 폴더의 `Data\`** 에 둡니다
  (레지스트리·`%APPDATA%` 를 쓰지 않음). 표식을 지우면 위의 사용자 폴더를 씁니다.
- `Program Files` 처럼 쓸 수 없는 폴더에 풀면 휴대용을 쓰지 못하고 사용자 폴더로 물러섭니다(상태줄에 안내).
- 앱 안 업데이트가 그대로 됩니다 — `_internal\` 만 바꾸므로 `Data\` 는 남습니다.
- 설치판과 함께 써도 설정·색인이 섞이지 않습니다. PDF 기본 앱 연결·시작 메뉴 바로가기는 만들지 않습니다.
- 내려받은 zip 은 Windows 가 '인터넷에서 받은 파일' 로 표시해 첫 실행 때 경고할 수 있습니다 — 풀기 전에 zip 의
  속성 → '차단 해제' 를 켜 두면 됩니다(서명되지 않은 프로그램).

## 배포용 기본값 프로파일
환경설정(도구 → 환경설정, Ctrl+,) **고급 › 관리** →
- **현재 설정을 기본값으로 저장(배포용)** : 현재 설정·스타일을 `default_settings.json`(프로그램 폴더)로 저장.
  개인 항목(즐겨찾기·최근 폴더·세션·머신 경로)은 제외됩니다. 이 파일을 배포본에 함께 넣으면
  **새 설치 시 그 설정으로 시작**합니다.
- **설정 초기화(기본값으로 되돌리기)** : 위 기본값(없으면 공장값)으로 되돌립니다(개인 항목 유지, 재시작).

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
git init; git add .; git commit -m "PolyPinax 1.88.0"
git branch -M main
gh repo create PolyPinax --private --source . --remote origin --push   # gh CLI (또는 웹에서 repo 생성 후 remote add)
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
`build_ci.bat` 로 빌드 → `dist\PolyPinax` 를 zip → `gh release create` 로 업로드합니다.

### 평소 업데이트 관리
```powershell
git add -A; git commit -m "fix: ..."; git push      # 소스 갱신(설정/스타일 영향 없음)
```
사용자 설정은 `%APPDATA%` 에 있으므로, 새 빌드를 받아도 기존 즐겨찾기·스타일이 그대로 유지됩니다.

## 단축키
| 단축키 | 동작 |
|--------|------|
| Ctrl+N | 새 창 |
| Ctrl+O | 폴더 열기 |
| Ctrl+R | 새로고침 (책갈피창) |
| Ctrl+S | 저장 |
| F12 | 다른 이름으로 저장 |
| Ctrl+Shift+C | 경로 복사 |
| Ctrl+Shift+N / Alt+Shift+R | 새 폴더 / 파일 탐색기 열기 |
| Alt+Enter | 문서 정보·사진 정보 |
| Ctrl+B / Ctrl+K / Ctrl+D | 책갈피 추가 / 하이퍼링크 / 즐겨찾기에 추가 |
| Ctrl+Shift+X / Ctrl+Enter | 크롭 / 새 페이지 넣기 |
| Ctrl+Alt+O | OCR 로 읽기 |
| Ctrl+, | 환경설정 |
| Alt+1 / Alt+2 | PDF 모드로 / 사진 모드로 (보기 종류 '혼용' 일 때만) |
| Ctrl+F | 검색바 포커스 |
| F3 / Shift+F3 | 다음/이전 매치 |
| ↓ / ↑ / PgDn / PgUp | 페이지 이동 (2장 보기 ±2) |
| Home / End | 첫/마지막 페이지 |
| Ctrl+Wheel | 줌 |
| Ctrl++ / Ctrl+- / Ctrl+0 | 확대 / 축소 / 기본 크기 (포커스가 있는 창 — 본문·썸네일·책갈피창·텍스트 창) |
| Ctrl+Shift+S | 스크린샷 캡처 |
| Ctrl+Alt+S | 스크린샷 PDF 일괄 저장 |
| Ctrl+Alt+C | 스크린샷 클립보드로 복사 |
| F5 | 발표 보기(전체화면) |
| S / D (발표 중) | 상하 2분할 보기 / 좌우 2쪽 보기 토글 |
| Ctrl+Q | 종료 |
