# -*- coding: utf-8 -*-

'''Table block object parsed from raw image and text blocks.

Data Structure::

    {
        'type': int
        'bbox': (x0, y0, x1, y1),
        'rows': [
            {
                "bbox": (x0, y0, x1, y1),
                "height": float,
                "cells": [
                    {
                        'bbox': (x0, y0, x1, y1),
                        'border_color': (sRGB,,,), # top, right, bottom, left
                        'bg_color': sRGB,
                        'border_width': (,,,),
                        'merged_cells': (x,y), # this is the bottom-right cell of merged region: x rows, y cols
                        'blocks': [ {text blocks} ]
                    }, # end of cell
                    {},
                    None, # merged cell
                    ...
                ]
            }, # end of row
            {...} # more rows
        ] # end of row
    }
'''


from .Row import Row
from .Rows import Rows
from ..common.Block import Block
from ..common import docx


class TableBlock(Block):
    '''Table block.'''
    def __init__(self, raw:dict=None):
        if raw is None: raw = {}
        super().__init__(raw)

        # collect rows
        self._rows = Rows(parent=self).restore(raw.get('rows', []))

        # lattice table by default
        self.set_lattice_table_block()

    def __getitem__(self, idx):
        try:
            row = self._rows[idx]
        except IndexError:
            msg = f'Row index {idx} out of range'
            raise IndexError(msg)
        else:
            return row

    def __iter__(self):
        return (row for row in self._rows)

    def __len__(self):
        return len(self._rows)

    @property
    def num_rows(self):
        '''Count of rows.'''
        return len(self._rows)

    @property
    def num_cols(self):
        '''Count of columns.'''
        return len(self._rows[0]) if self.num_rows else 0

    @property
    def text(self):
        '''Get text contained in each cell.

        Returns:
            list: 2D-list with each element representing text in cell.
        '''
        return [ [cell.text for cell in row] for row in self._rows ]

    @property
    def outer_bbox(self):
        '''Outer bbox with border considered.'''
        x0, y0, x1, y1 = self.bbox
        w0_top, w0_right, w0_bottom, w0_left = self[0][0].border_width
        w1_top, w1_right, w1_bottom, w1_left = self[-1][-1].border_width
        return (x0-w0_left/2.0, y0-w0_top/2.0, x1+w1_right/2.0, y1+w1_bottom/2.0)


    def append(self, row:Row):
        '''Append row to table and update bbox accordingly.

        Args:
            row (Row): Target row to add.
        '''
        self._rows.append(row)


    def store(self):
        res = super().store()
        res.update({
            'rows': self._rows.store()
        })
        return res


    def assign_blocks(self, blocks:list):
        '''Assign ``blocks`` to associated cell.

        Args:
            blocks (list): A list of text/table blocks.
        '''
        for row in self._rows:
            for cell in row:
                if not cell: continue
                cell.assign_blocks(blocks)


    def assign_shapes(self, shapes:list):
        '''Assign ``shapes`` to associated cell.

        Args:
            shapes (list): A list of Shape.
        '''
        for row in self._rows:
            for cell in row:
                if not cell: continue
                cell.assign_shapes(shapes)


    def parse(self, **settings):
        '''Parse layout under cell level.

        Args:
            settings (dict): Layout parsing parameters.
        '''
        for row in self._rows:
            for cell in row:
                if not cell: continue
                cell.parse(**settings)


    def plot(self, page):
        '''Plot table block, i.e. cell/line/span, for debug purpose.
        
        Args:
            page (fitz.Page): pdf page.
            content (bool): Plot text blocks contained in cells if True.
            style (bool): Plot cell style if True, e.g. border width, shading.
            color (bool): Plot border stroke color if ``style=False``.
        '''
        for row in self._rows:
            for cell in row:                
                if not cell: continue  # ignore merged cells   
                cell.plot(page)


    def make_docx(self, table):
        '''Create docx table.
        
        Args:
            table (Table): ``python-docx`` table instance.
        '''
        # POLYPDF 고침 6: python-docx `table.cell()` 은 부를 때마다 표 전체 칸 목록을 새로 만든다 —
        # 칸마다 여러 번 부르니 큰 표에서 몇 분씩 걸렸다. 칸 목록을 **처음 한 번** 만들어 끝까지 쓴다.
        # 합친 뒤에도 다시 만들지 않는다 — 아직 안 다룬 칸의 격자 자리는 그대로이고, 합쳐져 빠진 칸에 쓰는
        # 테두리·여백은 버려진다(다시 만들면 그것이 주 칸에 덧쓰인다). Word 로 찍은 화면이 픽셀까지 같고 더 빠르다.
        table = _CachedTable(table)
        # set left indent
        docx.indent_table(table, self.left_space)

        # set format and contents row by row
        for idx_row in range(len(table.rows)):
            self._rows[idx_row].make_docx(table, idx_row)


class _CachedTable:
    """python-docx Table 대리 — `cell()`·`_cells` 를 한 번 계산해 되쓴다(POLYPDF 고침 6). 나머지는 원래 표로."""

    def __init__(self, table):
        self._polypdf_table = table
        self._polypdf_cells = None

    def __getattr__(self, name):
        return getattr(self._polypdf_table, name)

    @property
    def _cells(self):
        if self._polypdf_cells is None:
            self._polypdf_cells = self._polypdf_table._cells
        return self._polypdf_cells

    def cell(self, row_idx, col_idx):
        return self._cells[col_idx + row_idx * self._polypdf_table._column_count]
