"""직접 PyInstaller 빌드 러너 (build.bat 와 동일 산출 — venv 재설치 생략, 현 환경 사용).

smart_pdf_viewer/ 에서 실행:  python build_exe.py
tesseract/ · nltk_data/ 가 있으면(stage_study_assets.py 산출) 자동 동봉.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.chdir(HERE)
SEP = ";"  # Windows add-data 구분자

args = [
    "--noconfirm", "--clean",
    "--name", "PolyPDF",
    "--windowed", "--onedir",      # onefile 추출 오류(charset_normalizer __mypyc) 회피·빠른 시작
    "--paths", ".",
    "--collect-all", "PyQt6",
    "--collect-all", "fitz",
    "--collect-all", "pdfplumber",
    "--collect-all", "pypdfium2",
    "--collect-all", "pypdf",
    "--collect-all", "wordfreq",
    "--collect-all", "pytesseract",
    "--collect-all", "kiwipiepy",
    "--collect-all", "kiwipiepy_model",     # ★ 한국어 모델(별도 103MB 패키지) — 없으면 Kiwi() 크래시
    "--collect-all", "docx",                # 260603: Word 내보내기(템플릿 데이터 포함)
    "--collect-all", "lameenc",
    "--collect-submodules", "viewer",
    "--add-data", f"resources{SEP}resources",
    "--add-data", f"viewer{SEP}viewer",
]
if (HERE / "resources" / "icon.ico").exists():
    args += ["--icon", "resources/icon.ico"]
if (HERE / "tesseract").exists():
    args += ["--add-data", f"tesseract{SEP}tesseract"]
    print("[+] tesseract 동봉")
if (HERE / "nltk_data").exists():
    args += ["--add-data", f"nltk_data{SEP}nltk_data"]
    print("[+] nltk_data 동봉")

for mod in [
    "viewer", "viewer.app", "viewer.history", "viewer.indexer", "viewer.pdf_doc",
    "viewer.screenshot", "viewer.settings_store", "viewer.workers",
    "viewer.resources_path", "viewer.bookmarker_bridge", "viewer.theme",
    "viewer.hyperlinks", "viewer.page_meta", "viewer.recorder",
    "viewer._vendor", "viewer._vendor.pdf_bookmarker", "viewer._vendor.pdf_bookmarker.core",
    "viewer._vendor.pdf_bookmarker.auto", "viewer._vendor.pdf_bookmarker.toc_extractor",
    "viewer._vendor.pdf_bookmarker.font_extractor", "viewer._vendor.pdf_bookmarker.pdf_writer",
    "viewer.widgets", "viewer.widgets.bookmark_tree", "viewer.widgets.main_view",
    "viewer.widgets.search_panel", "viewer.widgets.settings_dialog",
    "viewer.widgets.help_dialog", "viewer.widgets.favorites_dialog",
    "viewer.widgets.strip", "viewer.widgets.thumbs_list",
    "viewer.widgets.bookmarker_dialog", "viewer.widgets.screenshot_pdf_dialog",
    "viewer.widgets.study_panel", "viewer.widgets.study_edit_dialog",
    "viewer.widgets.flow_layout", "viewer.widgets.read_aloud", "viewer.widgets.print_dialog",
    "viewer.widgets.merge_dialog", "viewer.widgets.region_capture",
    "viewer.widgets.hyperlink_dialog", "viewer.widgets.presentation",
    "viewer.widgets.pointer_settings_dialog", "viewer.widgets.crop_dialog",
    "viewer.widgets.pen_settings_dialog",
    "viewer.widgets.capture_settings", "viewer.widgets.shortcuts_dialog",
    "viewer.study", "viewer.study.ocr", "viewer.study.vocab", "viewer.study.study_store",
    "viewer.study.tts", "viewer.study.export_docx", "viewer.study.mp3_export",
    "viewer.study.ocr_headings",
    "pytesseract", "wordfreq", "nltk", "kiwipiepy", "kiwipiepy_model",
    "docx", "win32com", "win32com.client", "pythoncom", "pywintypes", "lameenc",
    "openpyxl", "openpyxl.cell._writer", "send2trash",
]:
    args += ["--hidden-import", mod]

args += ["main.py"]

print("PyInstaller args 준비 완료. 빌드 시작...")
import PyInstaller.__main__
PyInstaller.__main__.run(args)

# 260609-17(F4): ffmpeg.exe 를 EXE 옆(외부)에 복사 — 녹화 기능에서 사용
import shutil
_ff = HERE / "ffmpeg.exe"
_distdir = HERE / "dist" / "PolyPDF"
if _ff.exists() and _distdir.exists():
    try:
        shutil.copy2(str(_ff), str(_distdir / "ffmpeg.exe"))
        print("[+] ffmpeg.exe 를 dist/PolyPDF 에 복사(녹화용).")
    except Exception as e:
        print(f"ffmpeg 복사 실패(무시): {e}")
elif not _ff.exists():
    print("[!] ffmpeg.exe 없음 — 녹화 기능은 ffmpeg 경로 지정 필요.")

# 빌드 후 build/ 정리 — build\PolyPDF\PolyPDF.exe(불완전 부트로더) 오실행 방지
bdir = HERE / "build"
if bdir.exists():
    try:
        shutil.rmtree(bdir)
        print("build/ 정리됨(중간 산출물).")
    except Exception as e:
        print(f"build/ 정리 실패(무시): {e}")
print(f"빌드 종료. 실행: dist\\PolyPDF\\PolyPDF.exe")
