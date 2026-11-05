"""고른 사진들을 한 지도에 — 이 PC 안 작은 웹 서버 + Leaflet 페이지 (사진 보기 SOT §4.29, 261105-17, D18).

- **왜 서버인가**: OpenStreetMap 타일 정책은 브라우저 페이지가 Referer 를 보내기를 요구한다. `file://` 페이지는 보내지 않으므로
  `127.0.0.1` 의 빈 포트에서 페이지를 준다(앱에 하나, 처음 쓸 때 데몬 스레드로). 지도 그림은 브라우저가 OpenStreetMap 에서 직접 받는다.
- 페이지마다 맞추기 어려운 토큰 주소(`/m/<토큰>/`), 최근 `MAP_PAGES_MAX` 개만 기억한다. 파일 경로는 페이지에 싣지 않는다(번호로 가리킨다).
- 작은 사진은 썸네일 캐시(`photo_strip.load_thumb`)를 그때그때 줄여 준다 — 브라우저가 보이는 표시만 부른다, 동시 `MAP_THUMB_WORKERS`.
- 브라우저의 [PolyPDF 에서 열기]·[PolyPDF 에서 고르기] 는 `MapBridge.picked`(경로 목록) 신호로 메인에 — 서버 스레드에서 보내므로 큐로 간다.
- Leaflet 1.9.4(BSD-2)·Leaflet.markercluster 1.5.3(MIT)은 `resources/map` 에 동봉(CDN 을 쓰지 않는다).
"""
from __future__ import annotations

import json
import os
import secrets
import threading
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PyQt6.QtCore import QObject, pyqtSignal

from viewer.i18n import tr

MAP_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"    # OpenStreetMap 표준 타일 — 브라우저가 직접 받는다(미리 받기 없음)
MAP_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
MAP_PAGES_MAX = 5           # 기억하는 지도 페이지 수 — 넘으면 오래된 것부터 잊는다(그 탭을 다시 읽으면 '없음')
MAP_THUMB_WORKERS = 2       # 썸네일을 동시에 만드는 수 — 수백 장이 한꺼번에 불려도 CPU 를 다 쓰지 않게
MAP_ICON_SIDE = 56          # 지도 위 작은 사진(CSS px)
MAP_POPUP_SIDE = 240        # 눌렀을 때 보이는 사진(CSS px)
MAP_PICK_MAX = 20000        # 한 번에 고르는 사진 수 상한(받는 글 크기 상한을 정한다)
LIB_FILES = {"leaflet.js": "application/javascript", "leaflet.css": "text/css",
             "leaflet.markercluster.js": "application/javascript", "MarkerCluster.css": "text/css"}


class MapBridge(QObject):
    """서버 스레드 → 메인. 메인 스레드에서 만든다(받는 쪽 스레드)."""
    picked = pyqtSignal(list)


class _Page:
    __slots__ = ("token", "points", "html")

    def __init__(self, token: str, points: list, html: str):
        self.token, self.points, self.html = token, points, html


_LOCK = threading.Lock()
_STATE = {"httpd": None, "thread": None, "pages": OrderedDict(), "bridge": None,
          "sem": threading.Semaphore(MAP_THUMB_WORKERS)}


def set_bridge(bridge: MapBridge | None) -> None:
    _STATE["bridge"] = bridge


def _thumb_bytes(path: str, side: int) -> bytes:
    """썸네일 캐시에서 읽어 긴 변 side(화면 배율 2배)로 줄인 JPEG — 서버 스레드에서."""
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from viewer.widgets.photo_strip import load_thumb
    img = load_thumb(path)
    if img.isNull():
        return b""
    px = side * 2
    if max(img.width(), img.height()) > px:
        img = img.scaled(px, px, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "JPG", 80)
    buf.close()
    return bytes(ba)


class _Handler(BaseHTTPRequestHandler):
    server_version = "PolyPDF-map"

    def log_message(self, *a):          # 콘솔에 쓰지 않는다
        pass

    def _send(self, code: int, body: bytes = b"", ctype: str = "text/plain; charset=utf-8", cache: int = 0):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")   # 타일 서버에 출처(Referer)를 보낸다
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "max-age=%d" % cache if cache else "no-store")
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _host_ok(self) -> bool:
        """DNS 리바인딩 막기 — 이 서버 주소로 온 요청만."""
        host = (self.headers.get("Host") or "").strip().lower()
        port = self.server.server_address[1]
        return host in ("127.0.0.1:%d" % port, "localhost:%d" % port)

    def _page(self, parts):
        if len(parts) < 2 or parts[0] != "m":
            return None
        with _LOCK:
            return _STATE["pages"].get(parts[1])

    def do_GET(self):
        if not self._host_ok():
            return self._send(403)
        path = self.path.split("?", 1)[0]
        parts = [p for p in path.split("/") if p]
        if len(parts) == 2 and parts[0] == "lib" and parts[1] in LIB_FILES:
            from viewer.resources_path import resource_path
            f = resource_path("map/" + parts[1])
            try:
                with open(f, "rb") as fh:
                    data = fh.read()
            except OSError:
                return self._send(404)
            return self._send(200, data, LIB_FILES[parts[1]] + "; charset=utf-8", cache=86400)
        pg = self._page(parts)
        if pg is None:
            return self._send(404, tr("지도 페이지가 없습니다 — PolyPDF 에서 다시 여세요.").encode("utf-8"))
        if len(parts) == 2:
            if not path.endswith("/"):
                self.send_response(301)
                self.send_header("Location", path + "/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            return self._send(200, pg.html.encode("utf-8"), "text/html; charset=utf-8")
        if len(parts) == 4 and parts[2] in ("t", "b") and parts[3].endswith(".jpg"):
            try:
                i = int(parts[3][:-4])
                p = pg.points[i]["path"]
            except (ValueError, IndexError):
                return self._send(404)
            with _STATE["sem"]:
                try:
                    data = _thumb_bytes(p, MAP_ICON_SIDE if parts[2] == "t" else MAP_POPUP_SIDE)
                except Exception:
                    data = b""
            if not data:
                return self._send(404)
            return self._send(200, data, "image/jpeg", cache=3600)
        return self._send(404)

    do_HEAD = do_GET

    def do_POST(self):
        if not self._host_ok():
            return self._send(403)
        parts = [p for p in self.path.split("?", 1)[0].split("/") if p]
        pg = self._page(parts)
        if pg is None or len(parts) != 3 or parts[2] != "pick":
            return self._send(404)
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > MAP_PICK_MAX * 8:
            return self._send(400)
        raw = self.rfile.read(n).decode("ascii", "replace")
        idx = []
        for t in raw.split(","):
            try:
                i = int(t)
            except ValueError:
                continue
            if 0 <= i < len(pg.points):
                idx.append(i)
        paths = [pg.points[i]["path"] for i in dict.fromkeys(idx)]
        b = _STATE["bridge"]
        if paths and b is not None:
            b.picked.emit(paths)                 # 서버 스레드 → 메인(큐)
        return self._send(204)


def ensure_server() -> int:
    """서버를 띄우고(이미 있으면 그대로) 포트를 돌려준다. 배경에서 불러도 된다."""
    with _LOCK:
        h = _STATE["httpd"]
        if h is not None:
            return h.server_address[1]
        h = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        h.daemon_threads = True
        t = threading.Thread(target=h.serve_forever, name="PolyPDF-map", daemon=True)
        t.start()
        _STATE["httpd"], _STATE["thread"] = h, t
        return h.server_address[1]


def stop_server() -> None:
    """검사·앱 끝에서 — 서버를 닫고 페이지를 잊는다."""
    with _LOCK:
        h = _STATE["httpd"]
        _STATE["httpd"] = _STATE["thread"] = None
        _STATE["pages"].clear()
    if h is not None:
        try:
            h.shutdown()
            h.server_close()
        except Exception:
            pass


def page_html(points: list, skipped_gps: int = 0, skipped_cloud: int = 0) -> str:
    """지도 페이지 HTML. points: [{"lat","lon","name","date"}...] — 경로는 싣지 않는다."""
    note = []
    if skipped_gps:
        note.append(tr("위치 없는 사진 {n}장 뺌").format(n=skipped_gps))
    if skipped_cloud:
        note.append(tr("클라우드에만 있는 사진 {n}장 뺌").format(n=skipped_cloud))
    data = {
        "pts": [[round(float(p["lat"]), 6), round(float(p["lon"]), 6), p.get("name", ""), p.get("date", "")] for p in points],
        "tile": MAP_TILE_URL, "attr": MAP_ATTRIBUTION, "icon": MAP_ICON_SIDE, "pop": MAP_POPUP_SIDE,
        "title": tr("사진 위치 — {n}장").format(n=len(points)), "note": " · ".join(note),
        "t": {"open": tr("PolyPDF 에서 열기"), "pick": tr("PolyPDF 에서 고르기"), "zoom": tr("확대"),
              "n": tr("{n}장"), "sent": tr("PolyPDF 로 보냈습니다"), "fail": tr("PolyPDF 에 닿지 않습니다 — 앱이 닫혔을 수 있습니다")},
    }
    js = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return _TEMPLATE.replace("__TITLE__", _esc(data["title"])).replace("__DATA__", js)


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def add_page(points: list, skipped_gps: int = 0, skipped_cloud: int = 0) -> str:
    """points(경로 포함)로 페이지를 만들어 주소를 돌려준다 — 배경에서 부른다."""
    port = ensure_server()
    html = page_html(points, skipped_gps, skipped_cloud)
    tok = secrets.token_urlsafe(18)
    with _LOCK:
        pages = _STATE["pages"]
        pages[tok] = _Page(tok, [dict(p) for p in points], html)
        while len(pages) > MAP_PAGES_MAX:
            pages.popitem(last=False)
    return "http://127.0.0.1:%d/m/%s/" % (port, tok)


class PhotoMapWorker(QObject):
    """고른 사진의 위치 읽기(머리만) + 페이지 만들기 — 배경(응답성 SOT §4.4 감사표). 클라우드에만 있는 사진은 읽지 않는다."""
    done = pyqtSignal(dict)          # {"url": 주소 또는 "", "shown": n, "no_gps": n, "cloud": n}
    finished = pyqtSignal()

    def __init__(self, paths):
        super().__init__()
        self.paths = [str(p) for p in (paths or [])]
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    def run(self):
        from pathlib import Path
        from viewer import pacing, photo_io
        out = {"url": "", "shown": 0, "no_gps": 0, "cloud": 0, "points": []}
        try:
            pts = []
            for p in self.paths:
                if self._cancel:
                    return
                try:
                    st = os.stat(p)
                except OSError:
                    out["no_gps"] += 1
                    continue
                if photo_io.cloud_only(st):
                    out["cloud"] += 1                     # 내려받지 않는다(§4.37)
                    continue
                try:
                    info = photo_io.photo_info(p)
                except Exception:
                    info = {}
                g = info.get("gps")
                if not g:
                    out["no_gps"] += 1
                else:
                    pts.append({"path": p, "lat": g[0], "lon": g[1], "name": Path(p).name,
                                "date": (info.get("taken") or "")[:16].replace(":", "-", 2)})
                pacing.pace(self)
            out["shown"] = len(pts)
            out["points"] = pts
            if pts and not self._cancel:
                out["url"] = add_page(pts, out["no_gps"], out["cloud"])
        except Exception:
            pass
        finally:
            if not self._cancel:
                self.done.emit(out)
            self.finished.emit()


_TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="stylesheet" href="/lib/leaflet.css"><link rel="stylesheet" href="/lib/MarkerCluster.css">
<style>
html,body{margin:0;height:100%;font-family:"Malgun Gothic","Segoe UI",sans-serif}
#bar{position:absolute;z-index:1000;top:8px;left:56px;background:#fff;padding:6px 10px;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.3);font-size:14px}
#bar small{color:#666;margin-left:8px}
#map{position:absolute;inset:0}
.ph{background:none;border:none}
.ph img{width:100%;height:100%;object-fit:cover;border:2px solid #fff;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.5);background:#ddd;box-sizing:border-box}
.ph b{position:absolute;left:50%;bottom:-7px;width:8px;height:8px;margin-left:-4px;border-radius:50%;background:#e33;border:1px solid #fff}
.ph span{position:absolute;right:-8px;top:-8px;min-width:20px;padding:1px 5px;border-radius:10px;background:#1a73e8;color:#fff;font-size:12px;text-align:center;box-sizing:border-box}
.pop img{display:block;max-width:100%;border-radius:4px}
.pop .nm{font-weight:bold;margin-top:4px;word-break:break-all}.pop .dt{color:#666}
.pop button{margin-top:6px;margin-right:4px;padding:3px 10px;cursor:pointer}
#toast{position:absolute;z-index:1000;bottom:24px;left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:6px 14px;border-radius:6px;display:none}
</style></head><body>
<div id="map"></div><div id="bar"></div><div id="toast"></div>
<script src="/lib/leaflet.js"></script><script src="/lib/leaflet.markercluster.js"></script>
<script>
const D = __DATA__;
const S = D.icon;
document.getElementById('bar').innerHTML = esc(D.title) + (D.note ? '<small>' + esc(D.note) + '</small>' : '');
function esc(s){return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function toast(s){const t=document.getElementById('toast'); t.textContent=s; t.style.display='block'; clearTimeout(t._h); t._h=setTimeout(()=>t.style.display='none',2500);}
function pick(ids){
  fetch('pick', {method:'POST', body: ids.join(',')}).then(r => toast(r.ok ? D.t.sent : D.t.fail)).catch(() => toast(D.t.fail));
}
const map = L.map('map', {zoomControl: true});
L.tileLayer(D.tile, {maxZoom: 19, attribution: D.attr}).addTo(map);
const cl = L.markerClusterGroup({zoomToBoundsOnClick: false, showCoverageOnHover: false, maxClusterRadius: 70,
  iconCreateFunction: c => { const ms = c.getAllChildMarkers();
    return L.divIcon({className: 'ph', html: '<img src="t/' + ms[0].options.i + '.jpg"><b></b><span>' + ms.length + '</span>',
                      iconSize: [S, S], iconAnchor: [S/2, S/2]}); }});
D.pts.forEach((p, i) => {
  const m = L.marker([p[0], p[1]], {i: i, title: p[2],
    icon: L.divIcon({className: 'ph', html: '<img src="t/' + i + '.jpg" loading="lazy"><b></b>', iconSize: [S, S], iconAnchor: [S/2, S/2]})});
  m.bindPopup(() => {
    const d = document.createElement('div'); d.className = 'pop'; d.style.width = D.pop + 'px';
    d.innerHTML = '<img src="b/' + i + '.jpg"><div class="nm">' + esc(p[2]) + '</div><div class="dt">' + esc(p[3]) + '</div>';
    const b = document.createElement('button'); b.textContent = D.t.open; b.onclick = () => pick([i]); d.appendChild(b);
    return d; }, {maxWidth: D.pop + 40});
  cl.addLayer(m);
});
cl.on('clusterclick', e => {
  const c = e.layer, ms = c.getAllChildMarkers(), ids = ms.map(m => m.options.i);
  const d = document.createElement('div'); d.className = 'pop'; d.style.width = (D.pop * 0.75) + 'px';
  d.innerHTML = '<img src="b/' + ids[0] + '.jpg"><div class="nm">' + esc(D.t.n.replace('{n}', ids.length)) + '</div>';
  const z = document.createElement('button'); z.textContent = D.t.zoom;
  z.onclick = () => { map.closePopup(); if (map.getZoom() >= map.getMaxZoom()) c.spiderfy(); else c.zoomToBounds({padding: [40, 40]}); };
  const k = document.createElement('button'); k.textContent = D.t.pick; k.onclick = () => pick(ids);
  d.appendChild(z); d.appendChild(k);
  L.popup({maxWidth: D.pop + 40}).setLatLng(c.getLatLng()).setContent(d).openOn(map);
});
map.addLayer(cl);
if (D.pts.length) map.fitBounds(cl.getBounds(), {padding: [50, 50], maxZoom: 16}); else map.setView([36.5, 127.8], 7);
</script></body></html>
"""
