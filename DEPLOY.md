# PolyPDF 배포 & 자동 업데이트 가이드 (260618-11)

사용자가 **도움말 → 업데이트 확인…** 으로 새 버전을 받고, **[업데이트]** 한 번으로
자동 교체·재시작되게 하는 구성입니다. (GitHub Releases 기반, 공개 저장소)

이 저장소에는 이미 **GitHub Actions 워크플로**가 있어, **버전 태그를 push 하면
자동으로 Windows 빌드 → zip → Release 업로드**까지 됩니다.
- `.github/workflows/release.yml` : 태그 `v*` push 시 빌드 후 **두 자산** 업로드 —
  `PolyPDF-<tag>-win64.zip`(전체=첫 설치용)과 `PolyPDF-<tag>-win64-update.zip`(업데이트용, 무거운
  불변부 제외). v2.26.0부터 **ffmpeg·Tesseract 재동봉**(다운로드+은밀실행을 Defender 가 차단하던 문제 회피).
- `.github/workflows/ci.yml` : push/PR 마다 오프스크린 GUI 회귀 테스트.

---

## 1. 동작 원리

- 앱이 **전체 릴리스 목록에서 최고 SemVer 태그**(예 `v2.26.0`)를 `__version__` 과 비교
  (`components` 등 비버전·draft 제외). 새 버전이면 **`update` zip 자산을 우선**(없으면 full)
  내려받아, 도우미 배치가 앱 종료 대기 → 설치 폴더 **덮어쓰기(없는 파일은 보존)** → 재실행.
- **업데이트가 가벼운 이유**: `update` zip 은 안 바뀌는 무거운 부분(ffmpeg·Tesseract·한국어
  모델·NLTK)을 제외 → 덮어쓰기 시 기존 설치분이 **그대로 보존**되어 다시 받지 않음.
- 저장소는 앱 기본값 `kdjeong777-ops/PolyPDF` 고정(설정 `update_repo` 로 변경 가능).
- 자동 확인: 배포 exe 에서 시작 4초 뒤 1회(`auto_check_update`, 기본 켜짐).

> 규약: 태그 = `v`+버전. 첫 설치 = full zip, 자동 업데이트 = update zip(이름에 `update`).

---

## 2. 최초 1회: 저장소 만들기 & 올리기

> ⚠️ 인증·push 는 본인 GitHub 계정으로 직접. (대신 로그인/발행 불가)
> `ffmpeg.exe`(101MB)·`tesseract/`·`nltk_data/`·`.venv/`·`dist/` 는 `.gitignore` 로 제외
> (GitHub 100MB 한도/대용량). 저장소엔 코드만, 대용량은 릴리스 zip(CI가 생성)에만.

```powershell
cd C:\Claude\MPDF\smart_pdf_viewer
# git init·첫 커밋은 이미 되어 있을 수 있음(git log 로 확인). 없으면:
#   git init; git add .; git commit -m "PolyPDF v2.23.0"

gh auth login
gh repo create PolyPDF --public --source . --remote origin --push
#   (gh 없으면: GitHub 웹에서 빈 repo 생성 후
#    git remote add origin https://github.com/<OWNER>/PolyPDF.git
#    git branch -M main; git push -u origin main)
```

앱에서 **도움말 → 업데이트 확인…** → `OWNER/PolyPDF` 1회 입력.

---

## 3. 새 버전 낼 때마다 (권장: 원클릭)

```powershell
cd C:\Claude\MPDF\smart_pdf_viewer
.\scripts\release.ps1 2.26.0     # 버전 bump→commit→태그→push 한 번에 (CI가 빌드·릴리스)
```
`release.ps1` 이 `viewer\__init__.py` 의 `__version__` 변경 + 커밋 + 태그 `v2.26.0` + push 까지
수행하고, GitHub Actions(release.yml)가 빌드해 릴리스를 만듭니다. (잘못된 버전·중복 태그는 자동 차단)

수동으로 하려면:
```powershell
# viewer\__init__.py 의 __version__ 수정 후
git add -A; git commit -m "v2.26.0"; git tag v2.26.0; git push; git push origin v2.26.0
```

GitHub Actions(release.yml)가 Windows 에서 빌드하고
`PolyPDF-v2.25.0-win64.zip` 을 릴리스에 올립니다. 기존 사용자 앱이 자동 감지·업데이트.

### 3-b. (대안) 로컬 빌드 후 수동 릴리스
CI를 쓰지 않거나 빠르게 올릴 때:
```powershell
.\build_ci.bat
powershell -ExecutionPolicy Bypass -File scripts\make_release_zip.ps1   # full + update zip 2종 생성
gh release create v2.26.0 PolyPDF-v2.26.0-win64.zip PolyPDF-v2.26.0-win64-update.zip --title "PolyPDF v2.26.0" --generate-notes
#   (gh 없으면 GitHub 웹 Releases → Draft new release → 태그 v2.26.0 → 두 zip 업로드)
```

---

## 3-c. (선택) 구성요소 별도 설치 — `components` 태그

v2.26.0부터 ffmpeg·Tesseract 는 **release(full) zip 에 동봉**되어 첫 설치만으로 녹화·OCR 이
동작합니다. 따라서 `components` 태그/구성요소 설치는 **선택적 폴백**입니다(번들이 우선 사용됨).
번들 없이 따로 받게 하려면 아래처럼 `components` 태그에 자산을 올려둘 수 있습니다:

```powershell
cd C:\Claude\MPDF\smart_pdf_viewer
powershell -ExecutionPolicy Bypass -File scripts\make_components.ps1   # ffmpeg.exe + tesseract.zip 준비
gh release create components ffmpeg.exe tesseract.zip --title "Components (ffmpeg/Tesseract)" --prerelease --notes "녹화·OCR 구성요소"
#   (이미 있으면) gh release upload components ffmpeg.exe tesseract.zip --clobber
```
> 주의: `components` 릴리스는 반드시 **pre-release** 로 두세요(아니면 `releases/latest` 를 가로채
> 구버전 앱의 업데이트 확인이 깨집니다 — 신버전은 목록에서 최고 버전을 고르므로 영향 없음).

---

## 4. 참고 / 주의

- **서명 안 된 exe**: 첫 실행 시 SmartScreen 경고(정상). 없애려면 코드서명 인증서(유료).
- **zip 크기**: full 은 ffmpeg·Tesseract·모델 포함으로 큼(dist 약 780MB, zip 은 압축되어 작음).
  **update zip 은 그 무거운 불변부(≈290MB)를 빼서** 자동 업데이트가 그만큼 가볍습니다. 첫 설치만
  full, 이후는 update.
- **서명 안 된 exe / 백신**: 첫 실행 SmartScreen 경고(정상). 드물게 Defender 가 ffmpeg.exe 를
  false-positive 로 차단할 수 있는데, 번들(사용자가 직접 압축 해제)이면 다운로드+은밀실행 패턴이
  없어 확률이 낮습니다. 차단 시 녹화 테스트가 **ffmpeg 오류/차단 안내**를 표시하니, 설치 폴더의
  ffmpeg.exe 를 Windows 보안 예외에 추가하면 됩니다.
- **비공개 저장소**: 릴리스 조회에 토큰 내장이 필요해 비권장(현재 공개 전제).
