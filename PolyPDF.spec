# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

datas = [('resources', 'resources'), ('viewer', 'viewer'), ('tesseract', 'tesseract'), ('nltk_data', 'nltk_data')]
binaries = [('ffmpeg.exe', '.')]
hiddenimports = ['PyQt6.QtMultimedia', 'PyQt6.QtMultimediaWidgets', 'viewer', 'viewer.app', 'viewer.history', 'viewer.indexer', 'viewer.pdf_doc', 'viewer.screenshot', 'viewer.settings_store', 'viewer.workers', 'viewer.updater', 'viewer.resources_path', 'viewer.global_hotkey', 'viewer.bookmarker_bridge', 'viewer._vendor', 'viewer._vendor.pdf_bookmarker', 'viewer._vendor.pdf_bookmarker.core', 'viewer._vendor.pdf_bookmarker.auto', 'viewer._vendor.pdf_bookmarker.toc_extractor', 'viewer._vendor.pdf_bookmarker.font_extractor', 'viewer._vendor.pdf_bookmarker.pdf_writer', 'viewer.widgets', 'viewer.widgets.bookmark_tree', 'viewer.widgets.main_view', 'viewer.widgets.search_panel', 'viewer.widgets.settings_dialog', 'viewer.widgets.help_dialog', 'viewer.widgets.favorites_dialog', 'viewer.widgets.strip', 'viewer.widgets.thumbs_list', 'viewer.widgets.bookmarker_dialog', 'viewer.widgets.screenshot_pdf_dialog', 'viewer.widgets.study_panel', 'viewer.widgets.study_edit_dialog', 'viewer.widgets.flow_layout', 'viewer.widgets.read_aloud', 'viewer.widgets.print_dialog', 'viewer.study', 'viewer.study.ocr', 'viewer.study.vocab', 'viewer.study.study_store', 'viewer.study.dict_store', 'viewer.study.glossary_import', 'viewer.study.term_spotter', 'viewer.study.dict_export', 'viewer.study.image_fetch', 'viewer.study.online_dict', 'viewer.study.law_api', 'viewer.widgets.law_search_dialog', 'viewer.widgets.toggle_splitter', 'viewer.widgets.icons', 'viewer.widgets.image_search_dialog', 'viewer.study.tts', 'viewer.study.export_docx', 'viewer.study.mp3_export', 'pytesseract', 'wordfreq', 'nltk', 'kiwipiepy', 'kiwipiepy_model', 'docx', 'lameenc', 'win32com', 'win32com.client', 'pythoncom', 'pywintypes', 'openpyxl', 'openpyxl.cell._writer', 'send2trash']
hiddenimports += collect_submodules('viewer')
tmp_ret = collect_all('PyQt6')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('fitz')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pdfplumber')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pypdfium2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pypdf')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('wordfreq')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pytesseract')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('kiwipiepy')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('kiwipiepy_model')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('docx')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('lameenc')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=['C:\\Claude\\MPDF\\smart_pdf_viewer'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PolyPDF',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['resources\\icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PolyPDF',
)
