# -*- coding: utf-8 -*-
'''POLYPDF 고침 8 — 줄 잇기·쪽 맞춤·글꼴 (형식 변환 SOT §1.2·§4.1, 261113-3).

앱(`viewer/convert/word_fit.Hook`)이 `HOOK` 에 걸이를 넣는다. 걸이가 없으면(원본 pdf2docx 처럼 쓰면) 아무것도 바꾸지 않는다.
- `begin_page(쪽 id)` — `converter.parse_pages` 가 쪽을 풀기 전에 부른다(그 쪽의 줄 잇기 계획).
- `decide_breaks(rows)` — `Lines.parse_line_break` 끝: 줄 끝 끊기를 계획대로(모양 그대로 = 줄마다 끊음, 편집 가능 = 이어지는 줄만 잇는다).
- `fit_block(block)` — `TextBlock.make_docx` 처음: 글꼴을 바꾸고, 줄 간격을 '정확히'(원본 줄 간격)로, 원본 줄 수 안에 들게
  자간 → 줄 간격 → 글자 크기.
- `font_name(span)` — `TextSpan._set_text_format`: Word 에 넣을 글꼴 이름.
'''

import math

HOOK = None
CUR = None


def begin_page(pid):
    global CUR
    CUR = HOOK.plan(pid) if HOOK is not None else None


def _match(bbox, cont):
    cx, cy = (bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0
    for c in cont:
        if c[1] - 1 <= cy <= c[3] + 1 and bbox[0] < c[2] + 1 and bbox[2] > c[0] - 1 and c[0] - 1 <= cx <= c[2] + 1:
            return c
    return None


def decide_breaks(rows):
    '''편집 가능 — 줄 끝 끊기를 앱의 쪽 계획으로(이어지는 줄만 잇고 나머지는 끊는다). 마지막 줄은 그대로(문단 끝).
    모양 그대로는 pdf2docx 의 판정 그대로 — 줄마다 끊으면 조금 넓어진 줄이 꺾여 오히려 쪽이 늘었다(별첨4 실측 48 → 53쪽).'''
    if CUR is None or not rows or CUR.get('mode') != 'edit':
        return
    cont = CUR.get('cont') or []
    for lines in rows[:-1]:
        end_line = lines[-1]
        hit = _match(tuple(end_line.bbox), cont)
        end_line.line_break = 0 if hit is not None else 1
        end_line.pp_sep = (hit[4] if len(hit) > 4 else '') if hit is not None else ''


def font_name(span):
    if HOOK is None:
        return span.font
    return HOOK.font(span.font, span.flags)[0]


def safe_text(text):
    if HOOK is None or not text:
        return text
    return HOOK.safe(text)


def font_bold(span):
    return bool(HOOK is not None and HOOK.bold(span.font, span.flags))


def _text_spans(line):
    from .text.TextSpan import TextSpan
    return [s for s in line.spans if isinstance(s, TextSpan)]


def _in_cell(block):
    p, k = getattr(block, 'parent', None), 0
    while p is not None and k < 6:
        if type(p).__name__ == 'Cell':
            return True
        p, k = getattr(p, 'parent', None), k + 1
    return False


def fit_block(block, layout_width):
    '''블록을 원본 줄 수 안에 — 줄 간격은 '정확히' 원본 줄 간격으로(Word 글꼴의 줄 높이를 타지 않게).'''
    if HOOK is None or not block.is_horizontal_text or not layout_width:
        return
    rows = block.lines.group_by_physical_rows()
    if not rows:
        return
    if block.line_space_type != 0 and getattr(HOOK, 'exact', True):   # 상대 줄 간격 → 정확히(원본 줄 간격)
        block.line_space_type = 0
        block.parse_exact_line_spacing()
    if not _in_cell(block):                          # 표 칸 밖 글 문단의 위 간격 — 꺾임이 남은 쪽의 여유(SOT §1.2 B 안)
        block.before_space = max(0.0, float(block.before_space or 0) * float(getattr(HOOK, 'before_k', 1.0)))
    pitch = float(block.line_space or 0)
    # 문단 너비 — make_docx 가 쓰는 들여쓰기와 같게(오른쪽 들여쓰기는 0.1 인치 아래로 내림)
    from .common import constants
    left = block.left_space - (block.first_line_space if block.first_line_space < 0 else 0)
    right = math.floor(block.right_space / constants.ITP * 10) / 10 * constants.ITP
    avail = layout_width - left - right
    if avail <= 10:
        return
    # 줄 묶음(문단 안 끊은 줄 사이) — 끊긴 줄마다 한 덩이
    segs, cur = [], []
    for row in rows:
        cur.append(row)
        if row[-1].line_break:
            segs.append(cur)
            cur = []
    if cur:
        segs.append(cur)
    min_pitch = None
    for k, seg in enumerate(segs):
        spans = [s for row in seg for line in row for s in _text_spans(line)]
        if not spans:
            continue
        size = max(s.size for s in spans)
        meas = {id(s): HOOK.width(s.text, s.size, s.font, s.flags, s.bbox.width) for s in spans}
        # 줄 너비 = 원본 줄 너비 + (Word 글꼴 너비 − 원본 글 너비) — 탭·빈칸 자리(조각 사이)는 원본 그대로 남는다
        width = 0.0
        for row in seg:
            x0 = min(line.bbox[0] for line in row)
            x1 = max(line.bbox[2] for line in row)
            rs = [s for line in row for s in _text_spans(line)]
            width += (x1 - x0) + sum(meas[id(s)] - s.bbox.width for s in rs)
        text_w = sum(meas.values()) or 1.0
        n = len(seg)
        # 조각 사이 자리(탭·빈칸)는 줄지 않으니 문단 너비에서 빼고, 글자 너비만으로 계획한다
        avail_eff = max(10.0, avail - max(0.0, width - text_w) / n)
        indent = block.first_line_space if k == 0 else 0.0
        plan = HOOK.fit(text_w, n, avail_eff, size, pitch if n > 1 else None, indent)
        if plan['shrink'] < 0:
            for s in spans:
                chars = max(1, len(s.text))
                s.char_spacing = (s.char_spacing or 0.0) + plan['shrink'] * meas[id(s)] / chars
        if plan['scale'] < 1.0:
            for s in spans:
                s.size *= plan['scale']
                s.char_spacing = (s.char_spacing or 0.0) * plan['scale']
        if n > 1 and plan.get('pitch'):
            min_pitch = plan['pitch'] if min_pitch is None else min(min_pitch, plan['pitch'])
    if min_pitch is not None and min_pitch < pitch:
        block.line_space = min_pitch
