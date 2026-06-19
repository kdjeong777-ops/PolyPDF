# PolyPDF 배포 & 자동 업데이트 가이드 (260618-11)

사용자가 **도움말 → 업데이트 확인…** 으로 새 버전을 받고, **[업데이트]** 한 번으로
자동 교체·재시작되게 하는 구성입니다. (GitHub Releases 기반, 공개 저장소)

이 저장소에는 이미 **GitHub Actions 워크플로**가 있어, **버전 태그를 push 하면
자동으로 Windows 빌드 → zip → Release 업로드**까지 됩니다.
- `.github/workflows/release.yml` : 태그 `v*` push 시 빌드·릴리스(ffmpeg/Tesseract/NLTK는
  러너에서 자동 설치, 실패해도 핵심 뷰어는 빌드). 자산명 `PolyPDF-<tag>-win64.zip`.
- `.github/workflows/ci.yml` : push/PR 마다 오프스크린 GUI 회귀 테스트.

---

## 1. 동작 원리

- 앱이 `releases/latest` 의 **태그**(예 `v2.23.0`)를 `viewer/__init__.py` 의
  `__version__`(`2.23.0`)과 비교 → 새 버전이면 릴리스의 **zip 자산**(이름에 `win`
  포함분 우선)을 받아, 도우미 배치가 앱 종료 대기 → 설치 폴더 덮어쓰기 → 재실행.
- 저장소는 앱 설정 `update_repo`(`OWNER/REPO`). 최초 '업데이트 확인…' 시 입력받아 저장.
- 자동 확인: 배포 exe 에서 시작 4초 뒤 1회(`auto_check_update`, 기본 켜짐).

> 규약: 태그 = `v`+버전. 자산 = zip(루트에 `PolyPDF.exe`·`_internal\` 또는 `PolyPDF\` 하위).

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

## 3. 새 버전 낼 때마다 (권장: CI 자동)

```powershell
cd C:\Claude\MPDF\smart_pdf_viewer
# 1) viewer\__init__.py 의 __version__ = "2.24.0" 로 수정
git add -A
git commit -m "v2.24.0"
git tag v2.24.0
git push
git push origin v2.24.0        # ← 태그 push 가 끝. CI가 빌드→릴리스 자동 생성
```

GitHub Actions(release.yml)가 Windows 에서 빌드하고
`PolyPDF-v2.24.0-win64.zip` 을 릴리스에 올립니다. 기존 사용자 앱이 자동 감지·업데이트.

### 3-b. (대안) 로컬 빌드 후 수동 릴리스
CI를 쓰지 않거나 빠르게 올릴 때:
```powershell
.\build_ci.bat
powershell -ExecutionPolicy Bypass -File scripts\make_release_zip.ps1   # PolyPDF-v<ver>-win64.zip
gh release create v2.24.0 PolyPDF-v2.24.0-win64.zip --title "PolyPDF v2.24.0" --generate-notes
#   (gh 없으면 GitHub 웹 Releases → Draft new release → 태그 v2.24.0 → zip 업로드)
```

---

## 4. 참고 / 주의

- **서명 안 된 exe**: 첫 실행 시 SmartScreen 경고(정상). 없애려면 코드서명 인증서(유료).
- **릴리스 zip 크기**: ffmpeg·tesseract·모델 포함 시 수백 MB(릴리스 자산 2GB 한도 내 OK).
  업데이트는 전체 교체 방식이라 매번 전체 다운로드입니다.
- **CI 자산 설치 실패 시**(choco/네트워크): 녹화/OCR 바이너리 없이 빌드될 수 있음
  (핵심 뷰어는 동작). 전체 기능 보장이 필요하면 로컬 빌드(3-b) 권장.
- **비공개 저장소**: 릴리스 조회에 토큰 내장이 필요해 비권장(현재 공개 전제).
