from collections import deque
import numpy as np
# POLYPDF 고침 1·7: opencv 를 쓰지 않는다 — `inner_contours` 는 numpy 로 연결 성분을 묶어 opencv `findContours(RETR_TREE)` 의
#   0~2층(겉 윤곽·구멍·구멍 안 윤곽)과 같은 것을 낸다(고침 7, 261014-30 — 대각선·곡선이 있는 쪽에서 실제로 불렸다)


# -------------------------------------------------------------------------------------------
# Intersection area of two iso-oriented rectangles
# -------------------------------------------------------------------------------------------
def get_area(bbox_1:tuple, bbox_2:tuple):
    x0, y0, x1, y1 = bbox_1
    u0, v0, u1, v1 = bbox_2

    # width of intersected area
    w = (x1-x0) + (u1-u0) - (max(x1, u1)-min(x0, u0))
    if w<=0: return 0

    # height of intersected area
    h = (y1-y0) + (v1-v0) - (max(y1, v1)-min(y0, v0))
    if h<=0: return 0

    return w*h


# -------------------------------------------------------------------------------------------
# Breadth First Search method for graph
# -------------------------------------------------------------------------------------------
def graph_bfs(graph): 
    '''Breadth First Search graph (may be disconnected graph).
    
    Args:
        graph (list): GRAPH represented by adjacent list, [set(1,2,3), set(...), ...]
    
    Returns:
        list: A list of connected components
    '''
    # search graph
    # NOTE: generally a disconnected graph
    counted_indexes = set() # type: set[int]
    groups = []
    for i in range(len(graph)):
        if i in counted_indexes: continue
        # connected component starts...
        indexes = set(_graph_bfs_from_node(graph, i))
        groups.append(indexes)
        counted_indexes.update(indexes)

    return groups


def _graph_bfs_from_node(graph, start):
    '''Breadth First Search connected graph with start node.
    
    Args:
        graph (list): GRAPH represented by adjacent list, [set(1,2,3), set(...), ...].
        start (int): Index of any start vertex.
    '''
    search_queue = deque()    
    searched = set()

    search_queue.append(start)
    while search_queue:
        cur_node = search_queue.popleft()
        if cur_node in searched: continue
        yield cur_node
        searched.add(cur_node)
        for node in graph[cur_node]:
            search_queue.append(node)



# -------------------------------------------------------------------------------------------
# Implementation of solving Rectangle-Intersection Problem according to algorithm proposed in
# paper titled "A Rectangle-Intersection Algorithm with Limited Resource Requirements".
# https://ieeexplore.ieee.org/document/5578313
# 
# - Input
# The rectangle is represented by its corner points, (x0, y0, x1, y1)
# 
# - Output
# The output is an Adjacent List of each rect, which could be used to initialize a GRAPH.
# -------------------------------------------------------------------------------------------
# procedure report(S, n)
# 1 Let V be the list of x-coordinates of the 2n vertical edges in S sorted in non-decreasing order.
# 2 Let H be the list of n y-intervals corresponding to the bottom and top y-coordinates of each rectangle.
# 3 Sort the elements of H in non-decreasing order by their bottom y-coordinates.
# 4 Call procedure detect(V, H, 2n).

def solve_rects_intersection(V:list, num:int, index_groups:list):
    '''Implementation of solving Rectangle-Intersection Problem.

    Performance::

        O(nlog n + k) time and O(n) space, where k is the count of intersection pairs.

    Args:
        V (list): Rectangle-related x-edges data, [(index, Rect, x), (...), ...].
        num (int): Count of V instances, equal to len(V).
        index_groups (list): Target adjacent list for connectivity between rects.
    
    Procedure ``detect(V, H, m)``::
    
        if m < 2 then return else
        - let V1 be the first ⌊m/2⌋ and let V2 be the rest of the vertical edges in V in the sorted order;
        - let S11 and S22 be the set of rectangles represented only in V1 and V2 but not spanning V2 and V1, respectively;
        - let S12 be the set of rectangles represented only in V1 and spanning V2; 
        - let S21 be the set of rectangles represented only in V2 and spanning V1
        - let H1 and H2 be the list of y-intervals corresponding to the elements of V1 and V2 respectively
        - stab(S12, S22); stab(S21, S11); stab(S12, S21)
        - detect(V1, H1, ⌊m/2⌋); detect(V2, H2, m − ⌊m/2⌋)
    '''
    if num < 2: return
    
    # start/end points of left/right intervals
    center_pos = int(num/2.0)
    X0, X, X1 = V[0][-1], V[center_pos-1][-1], V[-1][-1] 

    # split into two groups
    left = V[0:center_pos]
    right = V[center_pos:]

    # filter rects according to their position to each intervals
    S11 = list(filter( lambda item: item[1][2]<=X, left ))
    S12 = list(filter( lambda item: item[1][2]>=X1, left ))
    S22 = list(filter( lambda item: item[1][0]>X, right ))
    S21 = list(filter( lambda item: item[1][0]<=X0, right ))
    
    # intersection in x-direction is fulfilled, so check y-direction further
    _stab(S12, S22, index_groups)
    _stab(S21, S11, index_groups)
    _stab(S12, S21, index_groups)

    # recursive process
    solve_rects_intersection(left,  center_pos,     index_groups)
    solve_rects_intersection(right, num-center_pos, index_groups)


def _stab(S1:list, S2:list, index_groups:list):
    '''Check interval intersection in y-direction.
    
    Procedure ``stab(A, B)``::
        i := 1; j := 1
        while i ≤ |A| and j ≤ |B|
            if ai.y0 < bj.y0 then
            k := j
            while k ≤ |B| and bk.y0 < ai.y1
                reportPair(air, bks)
                k := k + 1
            i := i + 1
            else
            k := i
            while k ≤ |A| and ak.y0 < bj.y1
                reportPair(bjs, akr)
                k := k + 1
            j := j + 1
    '''
    if not S1 or not S2: return

    # sort
    S1.sort(key=lambda item: item[1][1])
    S2.sort(key=lambda item: item[1][1])

    i, j = 0, 0
    while i<len(S1) and j<len(S2):
        m, a, _ = S1[i]
        n, b, _ = S2[j]
        if a[1] < b[1]:
            k = j
            while k<len(S2) and S2[k][1][1] < a[3]:
                _report_pair(int(m/2), int(S2[k][0]/2), index_groups)
                k += 1
            i += 1
        else:
            k = i
            while k<len(S1) and S1[k][1][1] < b[3]:
                _report_pair(int(S1[k][0]/2), int(n/2), index_groups)
                k += 1
            j += 1


def _report_pair(i:int, j:int, index_groups:list):
    '''add pair (i,j) to adjacent list.'''
    index_groups[i].add(j)
    index_groups[j].add(i)



# -------------------------------------------------------------------------------------------
# Implementation of recursive X-Y cut algorithm, which is:
# a top-down page segmentation technique that decomposes a document image recursively into a 
# set of rectangular blocks.
# 
# - https://en.wikipedia.org/wiki/Recursive_X-Y_cut
# - Recursive X-Y Cut using Bounding Boxes of Connected Components by Jaekyu Ha, 
#   Robert M.Haralick and Ihsin T. Phillips
# -------------------------------------------------------------------------------------------
def recursive_xy_cut(img_binary:np.array, 
                    min_w:float=0.0, min_h:float=0.0, 
                    min_dx:float=15.0, min_dy:float=15.0): 
    '''Split image with recursive xy-cut algorithm.
    
    Args:
        img_binary (np.array): Binarized image with interesting region (255) and empty region (0).
        min_w (float): Ignore bbox if the width is less than this value.
        min_h (float): Ignore bbox if the height is less than this value.
        min_dx (float): Merge two bbox-es if the x-gap is less than this value.
        min_dy (float): Merge two bbox-es if the y-gap is less than this value.
    
    Returns:
        list: bbox (x0, y0, x1, y1) of split blocks.
    '''
    def xy_cut(arr:np.array, top_left:tuple, res:list, 
                    min_w:float, min_h:float, min_dx:float, min_dy:float):
        x0, y0 = top_left
        h, w = arr.shape
        # cut along x-direction
        projection = np.count_nonzero(arr==255, axis=1)
        pos_y = _split_projection_profile(projection, min_w, min_dy)
        if not pos_y: return        

        # cut along y-direction for each part
        arr_y0, arr_y1 = pos_y
        for r0, r1 in zip(arr_y0, arr_y1):
            x_arr = arr[r0:r1, 0:w]
            projection = np.count_nonzero(x_arr==255, axis=0)
            pos_x = _split_projection_profile(projection, min_h, min_dx)
            if not pos_x: continue
            
            # determined the block bbox
            arr_x0, arr_x1 = pos_x
            if len(arr_x0)==1:
                res.append((x0+arr_x0[0], y0+r0, x0+arr_x1[0], y0+r1))
                continue
            
            # xy-cut recursively if the count of blocks > 1
            for c0, c1 in zip(arr_x0, arr_x1):
                y_arr = arr[r0:r1, c0:c1]
                top_left = (x0+c0, y0+r0)
                xy_cut(y_arr, top_left, res, min_w, min_h, min_dx, min_dy)

    # do xy-cut recursively
    res = []
    xy_cut(arr=img_binary, top_left=(0, 0), res=res, 
            min_w=min_w, min_h=min_h, min_dx=min_dx, min_dy=min_dy)
    return res


def _split_projection_profile(arr_values:np.array, min_value:float, min_gap:float):
    '''Split projection profile:

    ```
                              ┌──┐
         arr_values           │  │       ┌─┐───
             ┌──┐             │  │       │ │ |
             │  │             │  │ ┌───┐ │ │min_value
             │  │<- min_gap ->│  │ │   │ │ │ |
         ────┴──┴─────────────┴──┴─┴───┴─┴─┴─┴───
         0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16
    ```

    Args:
        arr_values (np.array): 1-d array representing the projection profile.
        min_value (float): Ignore the profile if `arr_value` is less than `min_value`.
        min_gap (float): Ignore the gap if less than this value.

    Returns:
        tuple: Start indexes and end indexes of split groups.
    '''
    # all indexes with projection height exceeding the threshold
    arr_index = np.where(arr_values>min_value)[0]
    if not len(arr_index): return

    # find zero intervals between adjacent projections
    # |  |                    ||
    # ||||<- zero-interval -> |||||
    arr_diff = arr_index[1:] - arr_index[0:-1]
    arr_diff_index = np.where(arr_diff>min_gap)[0]
    arr_zero_intvl_start = arr_index[arr_diff_index]
    arr_zero_intvl_end = arr_index[arr_diff_index+1]

    # convert to index of projection range:
    # the start index of zero interval is the end index of projection
    arr_start = np.insert(arr_zero_intvl_end, 0, arr_index[0])
    arr_end = np.append(arr_zero_intvl_start, arr_index[-1])
    arr_end += 1 # end index will be excluded as index slice

    return arr_start, arr_end


def _label(mask: np.ndarray, conn8: bool):
    """POLYPDF 고침 7: 연결 성분 — 행마다 연속 구간(run)을 찾아 위 행의 겹치는 구간과 잇는다(union-find).
    `conn8` 이면 대각으로 닿아도 잇는다(opencv 가 윤곽을 찾는 전경과 같다), 아니면 상하좌우만(구멍 — 배경).
    반환: (성분 번호 배열 — 0 은 없음, 성분 수)."""
    h, w = mask.shape
    parent = []

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    m = mask.astype(np.int8)
    prev, allruns = [], []
    for y in range(h):
        d = np.diff(np.concatenate(([0], m[y], [0])))
        starts = np.flatnonzero(d == 1).tolist()
        ends = np.flatnonzero(d == -1).tolist()
        cur, j = [], 0
        for s, e in zip(starts, ends):
            rid = len(parent)
            parent.append(rid)
            lo, hi = (s - 1, e + 1) if conn8 else (s, e)
            while j < len(prev) and prev[j][1] <= lo:
                j += 1
            k = j
            while k < len(prev) and prev[k][0] < hi:
                a, b = find(rid), find(prev[k][2])
                if a != b:
                    parent[max(a, b)] = min(a, b)
                k += 1
            cur.append((s, e, rid))
            allruns.append((y, s, e, rid))
        prev = cur
    labels = np.zeros((h, w), np.int32)
    roots = {}
    for y, s, e, rid in allruns:
        labels[y, s:e] = roots.setdefault(find(rid), len(roots) + 1)
    return labels, len(roots)


def _bboxes(labels: np.ndarray, n: int) -> dict:
    """성분마다 (x0, y0, x1, y1) — opencv `boundingRect` 처럼 끝을 포함한 폭(+1)."""
    ys, xs = np.nonzero(labels)
    lab = labels[ys, xs]
    out = {}
    if n == 0:
        return out
    x0 = np.full(n + 1, 1 << 30); y0 = np.full(n + 1, 1 << 30); x1 = np.full(n + 1, -1); y1 = np.full(n + 1, -1)
    np.minimum.at(x0, lab, xs); np.minimum.at(y0, lab, ys)
    np.maximum.at(x1, lab, xs); np.maximum.at(y1, lab, ys)
    for i in range(1, n + 1):
        if x1[i] >= 0:
            out[i] = (int(x0[i]), int(y0[i]), int(x1[i]) + 1, int(y1[i]) + 1)
    return out


def inner_contours(img_binary:np.array, bbox:tuple, min_w:float, min_h:float):
    '''Inner contours of current region, especially level 2 contours of the default opencv tree hirerachy.

    POLYPDF 고침 7: opencv 없이 — 전경 성분(8방향)·배경 성분(4방향)과 둘이 맞닿은 관계로 층을 매긴다.
    0층 = 바깥 배경에 닿은 전경(표 테두리), 1층 = 0층에 닿은 구멍(칸), 2층 = 1층 구멍 안의 전경(칸 안 내용).
    아래 고르는 규칙(1층 안의 1층 · 2층)은 원본 그대로다.

    Args:
        img_binary (np.array): Binarized image with interesting region (255) and empty region (0).
        bbox (tuple): The external bbox.
        min_w (float): Ignore contours if the bbox width is less than this value.
        min_h (float): Ignore contours if the bbox height is less than this value.

    Returns:
        list: A list of bbox-es of inner contours.
    '''
    x0, y0, x1, y1 = bbox
    arr = np.zeros(img_binary.shape, dtype=np.uint8)
    arr[y0:y1, x0:x1] = img_binary[y0:y1, x0:x1]
    fg = arr > 0
    F, nf = _label(fg, True)
    B, nb = _label(~fg, False)
    outer = set(np.unique(np.concatenate([B[0, :], B[-1, :], B[:, 0], B[:, -1]])).tolist()) - {0}
    # 전경-배경이 맞닿은 짝(상하좌우)
    codes = []
    for fa, ba in ((F[:, :-1], B[:, 1:]), (F[:, 1:], B[:, :-1]), (F[:-1, :], B[1:, :]), (F[1:, :], B[:-1, :])):
        m = (fa > 0) & (ba > 0)
        codes.append(fa[m].astype(np.int64) * (nb + 1) + ba[m])
    pairs = np.unique(np.concatenate(codes)) if codes else np.zeros(0, np.int64)
    f_of = pairs // (nb + 1)
    b_of = pairs % (nb + 1)
    level_0 = set(f_of[np.isin(b_of, list(outer))].tolist())
    level_1 = set(b_of[np.isin(f_of, list(level_0))].tolist()) - outer
    level_2 = set(f_of[np.isin(b_of, list(level_1))].tolist()) - level_0
    fb, bb = _bboxes(F, nf), _bboxes(B, nb)

    def contains(bbox1, bbox2):
        x0, y0, x1, y1 = bbox1
        u0, v0, u1, v1 = bbox2
        return u0>=x0 and v0>=y0 and u1<=x1 and v1<=y1

    level_1_bbox_list, res_level_1, res = [], [], []
    for i in sorted(level_1):
        bx = bb[i]
        if bx[2] - bx[0] < min_w or bx[3] - bx[1] < min_h: continue
        level_1_bbox_list.append(bx)

    for bbox1 in level_1_bbox_list:
        for bbox2 in level_1_bbox_list:
            if bbox1==bbox2: continue # skip itself
            if contains(bbox1, bbox2):
                res_level_1.append(bbox2)
                res.append(bbox2)

    def contained_in_concerned_level_1(bbox):
        for level_1_bbox in res_level_1:
            if contains(level_1_bbox, bbox): return True
        return False

    for i in sorted(level_2):
        bx = fb[i]
        if bx[2] - bx[0] < min_w or bx[3] - bx[1] < min_h: continue
        if contained_in_concerned_level_1(bx): continue
        res.append(bx)

    return res


def xy_project_profile(img_source:np.array, img_binary:np.array, gap:int=5, dw:int=None, dh:int=None):   
    '''Projection profile along x and y direction.

    ```
           ┌────────────────┐
        dh │                │
           └────────────────┘
                 gap
           ┌────────────────┐ ┌───┐
           │                │ │   │
         h │     image      │ │   │
           │                │ │   │
           └────────────────┘ └───┘
                    w           dw
    ```

    Args:
        img_source (np.array): Source image, e.g. RGB mode.
        img_binary (np.array): Binarized image.
        gap (int, optional): Gap between sub-graph. Defaults to 5.
        dw (int, optional): Graph height of x projection profile. Defaults to None.
        dh (int, optional): Graph height of y projection profile. Defaults to None.

    Returns:
        np.array: The combined graph data.
    '''
    # combined image
    h, w = img_binary.shape
    dh = dh or max(int(h/3), 15)
    dw = dw or max(int(w/3), 15)
    arr = 255*np.ones((h+dh+gap, w+dw+gap, 3), dtype=np.uint8)

    # source image
    arr[dh+gap:dh+gap+h, 0:w, :] = img_source

    # x projection
    vals = np.count_nonzero(img_binary==255, axis=1)
    for i, val in enumerate(vals):
        c = int(val/w*dw)
        arr[i+dh+gap, w+gap:w+gap+int(c), :] = 0
    
    # y projection
    vals = np.count_nonzero(img_binary==255, axis=0)
    for i, val in enumerate(vals):
        r = int(val/h*dh)
        arr[dh-r:dh, i, :] = 0

    return arr

