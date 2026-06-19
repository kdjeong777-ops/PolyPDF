"""빌드 전 단어학습 동봉 자산 준비 (계획서 §14.5/§8.3).

빌드 폴더(smart_pdf_viewer/)에 다음을 만든다 — build.bat 의 %TESS_ARG%/%NLTK_ARG% 가 자동 인식:
  tesseract/Library/bin/*        (portable Tesseract: tesseract.exe + DLL 전체, libcurl 포함)
  tesseract/share/tessdata/*     (eng/kor traineddata)
  nltk_data/                     (WordNet + omw-1.4)

Tesseract 원본 = 개발용 micromamba 환경(study_spike/mamba/envs/ocr). 없으면 안내.
사용:  python stage_study_assets.py
"""
from __future__ import annotations
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # smart_pdf_viewer/
REPO = HERE.parent                              # MPDF/
ENV = REPO / "study_spike" / "mamba" / "envs" / "ocr"
DEST = HERE / "tesseract"
NLTK_DIR = HERE / "nltk_data"


def stage_tesseract() -> bool:
    src_bin = ENV / "Library" / "bin"
    src_td = ENV / "share" / "tessdata"
    if not (src_bin / "tesseract.exe").exists():
        print(f"[!] Tesseract 원본 없음: {src_bin}\\tesseract.exe")
        print("    먼저 개발 환경을 만드세요 (무관리자):")
        print("      study_spike\\micromamba.exe create -p study_spike\\mamba\\envs\\ocr "
              "-c conda-forge tesseract libcurl")
        return False
    dst_bin = DEST / "Library" / "bin"
    dst_td = DEST / "share" / "tessdata"
    dst_bin.mkdir(parents=True, exist_ok=True)
    dst_td.mkdir(parents=True, exist_ok=True)

    # Library/bin 전체(DLL + exe). __pycache__ 등 불필요 항목은 자연히 없음.
    n = 0
    for f in src_bin.iterdir():
        if f.is_file():
            shutil.copy2(f, dst_bin / f.name)
            n += 1
    # tessdata: eng/kor (+ osd) 만 — 용량 절약
    keep = {"eng.traineddata", "kor.traineddata", "osd.traineddata"}
    td = 0
    for f in src_td.iterdir():
        if f.name in keep and f.is_file():
            shutil.copy2(f, dst_td / f.name)
            td += 1
    print(f"[OK] Tesseract: bin {n}개 파일, tessdata {td}개 → {DEST}")
    return True


def stage_nltk() -> bool:
    try:
        import nltk
    except Exception:
        print("[!] nltk 미설치 — pip install nltk")
        return False
    NLTK_DIR.mkdir(parents=True, exist_ok=True)
    ok = True
    for pkg in ("wordnet", "omw-1.4"):
        try:
            nltk.download(pkg, download_dir=str(NLTK_DIR), quiet=True)
        except Exception as e:
            print(f"[!] nltk {pkg} 다운로드 실패: {e}")
            ok = False
    if ok:
        print(f"[OK] NLTK WordNet → {NLTK_DIR}")
    return ok


def stage_ko_levels() -> bool:
    """한국어 등급 어휘 CSV 생성 (resources/ko_levels.csv). wordfreq 데이터 기반, 오프라인."""
    csv = HERE / "resources" / "ko_levels.csv"
    if csv.exists() and csv.stat().st_size > 1000:
        print(f"[OK] ko_levels.csv 존재 ({csv.stat().st_size} B)")
        return True
    try:
        import subprocess
        subprocess.run([sys.executable, str(HERE / "gen_ko_levels.py")],
                       check=True, cwd=str(HERE))
        print(f"[OK] ko_levels.csv 생성")
        return csv.exists()
    except Exception as e:
        print(f"[!] ko_levels.csv 생성 실패(난이도 한국어 미동봉): {e}")
        return False


def stage_ko_en() -> bool:
    """한영사전 CSV(resources/ko_en_dict.csv) 생성 — kengdic(CC-BY-SA-3.0) 기반.
    kengdic.tsv 없으면 다운로드. 한국어 단어의 영어 뜻 제공(출처고지는 도움말 About)."""
    csv = HERE / "resources" / "ko_en_dict.csv"
    if csv.exists() and csv.stat().st_size > 100000:
        print(f"[OK] ko_en_dict.csv 존재 ({csv.stat().st_size} B)")
        return True
    tsv = HERE.parent / "study_spike" / "kengdic.tsv"
    if not tsv.exists():
        try:
            import urllib.request
            tsv.parent.mkdir(parents=True, exist_ok=True)
            url = "https://raw.githubusercontent.com/garfieldnate/kengdic/master/kengdic.tsv"
            print("  kengdic.tsv 다운로드 중...")
            urllib.request.urlretrieve(url, tsv)
        except Exception as e:
            print(f"[!] kengdic 다운로드 실패(한국어 영어뜻 미동봉): {e}")
            return False
    try:
        import subprocess
        subprocess.run([sys.executable, str(HERE / "gen_ko_en_dict.py")],
                       check=True, cwd=str(HERE))
        subprocess.run([sys.executable, str(HERE / "gen_en_ko_dict.py")],
                       check=True, cwd=str(HERE))     # 260603: 영어→한글(한글 뜻)
        print("[OK] ko_en_dict.csv / en_ko_dict.csv 생성")
        return csv.exists()
    except Exception as e:
        print(f"[!] 사전 생성 실패: {e}")
        return False


def main():
    print("=== 단어학습 동봉 자산 스테이징 ===")
    t = stage_tesseract()
    n = stage_nltk()
    stage_ko_levels()    # resources/ 는 build 시 자동 동봉 → 실패해도 빌드는 진행
    stage_ko_en()
    print("\n결과:", "완료. 이제 build.bat 실행 가능." if (t and n)
          else "일부 누락 — 위 안내 참고.")
    sys.exit(0 if (t and n) else 1)


if __name__ == "__main__":
    main()
