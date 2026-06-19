"""단어학습(Vocabulary/Study) 서브시스템 — OCR·어휘·난이도.

P1: ocr (스캔감지·렌더·Tesseract OCR·전처리), study_store (study.db).
P2(예정): vocab (표제어화·난이도·뜻·예문).
기존 index.db(FTS5 검색)와 분리된 study.db 에 캐시.
"""
