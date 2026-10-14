# pdf2docx — PolyPDF 가 가져와 고친 판

- 원본: pdf2docx **0.5.13** (PyPI 2026-05-01, MIT — `LICENSE`), 휠 SHA-256
  `a293e9e78d89b12a4a43fcefba1346de220681c3daf20b8a7d3e1fce77f0fe97`.
- 규칙·까닭: `형식 변환 작업 계획서.md` §4.1 (PolyPDF 작업 폴더, 공개 저장소 밖).
- 다시 받을 때: 같은 판의 휠을 받아 SHA-256 을 대조하고, 아래 고침을 다시 적용한 뒤 `test_convert_*` 를 돌린다.

| # | 파일 | 고친 것 | 까닭 | 검사 |
| --- | --- | --- | --- | --- |
| 1 | `common/algorithm.py` | 맨 위 `import cv2` 를 `inner_contours` 안으로 | 그 함수만 opencv 를 쓰고, 그 함수를 부르는 `detect_svg_contours` 는 아무도 부르지 않는다 — opencv 없이 불러지게 | `test_convert_docx_261014` (opencv 없이 import) |
| 2 | `image/ImagesExtractor.py` `_rotate_image` | opencv `warpAffine` → Pillow `rotate(각도, expand=True)` | 같은 반시계·회전 상자·검정 바탕 — opencv 없이 회전한 그림 | `test_convert_docx_261014` (회전한 그림) |
| 3 | `converter.py` `parse_pages`·`make_docx` | 설정 `progress(했음, 전체, 글) -> bool`, False 면 `ConversionCancelled` | 진행창·취소 | `test_convert_docx_261014` (취소) |
| 4 | `gui/` | 지움 | tkinter 창 — 앱에 필요 없다 | — |
| 5 | `page/RawPageFitz.py` `_preprocess_text`·`_preprocess_images` | 보이는 글이 없고 보이지 않는 글만 있는 쪽은 그 글을 쓰고 그 쪽 그림은 뺀다(쪽 단위 `ocr=2`) | 원본 `ocr` 설정은 문서 전체 하나 — 디지털·스캔이 섞인 문서의 스캔 쪽 OCR 층이 버려졌다 | `test_convert_docx_261014` D |
