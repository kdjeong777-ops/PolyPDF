"""260609-17 (F4): 화면+음성 녹화 — ffmpeg subprocess(gdigrab+dshow).

설계(끊김 최소화): ffmpeg 가 캡처·인코딩·버퍼링을 전담. 앱은 시작/일시정지/중지만.
- 비디오 H.264(libx264, CRF 23 ≈ CQ 23), 30fps, yuv420p.
- 오디오 AAC 192kbps. 소스: 마이크/시스템/둘 다(amix)/없음.
- 중지는 stdin 에 'q' 전송 → MP4 moov 정상 마감(파일 안 깨짐).
- 일시정지는 프로세스 suspend/resume(ntdll) — 베스트에포트.
ffmpeg.exe 위치: 설정 경로 → 실행파일 옆 → 패키지 옆 → PATH.
"""
from __future__ import annotations

import os
import re
import sys
import shutil
import subprocess
import ctypes
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000


def find_ffmpeg(configured: str = "") -> str:
    cands = []
    if configured:
        cands.append(configured)
    try:
        cands.append(str(Path(sys.executable).parent / "ffmpeg.exe"))
    except Exception:
        pass
    try:
        base = getattr(sys, "_MEIPASS", None)
        if base:
            cands.append(str(Path(base) / "ffmpeg.exe"))
    except Exception:
        pass
    try:
        cands.append(str(Path(__file__).resolve().parent.parent / "ffmpeg.exe"))
    except Exception:
        pass
    for c in cands:
        if c and os.path.isfile(c):
            return c
    w = shutil.which("ffmpeg")
    return w or ""


def list_audio_devices(ffmpeg: str) -> list:
    """dshow 오디오 입력 장치명 목록."""
    if not ffmpeg:
        return []
    try:
        p = subprocess.run([ffmpeg, "-hide_banner", "-f", "dshow",
                            "-list_devices", "true", "-i", "dummy"],
                           capture_output=True, timeout=15,
                           creationflags=CREATE_NO_WINDOW)
        # 장치명이 한글/유니코드일 수 있어 utf-8(보조 cp949)로 디코드
        raw = (p.stderr or b"") + (p.stdout or b"")
        try:
            out = raw.decode("utf-8")
        except Exception:
            out = raw.decode("cp949", errors="replace")
    except Exception:
        return []
    names, in_audio = [], False
    for line in out.splitlines():
        if "(audio)" in line:
            m = re.search(r'"([^"]+)"', line)
            if m:
                names.append(m.group(1))
        elif "DirectShow audio devices" in line:
            in_audio = True
    # 일부 빌드는 (audio) 태그 없이 섹션으로 구분 → 보조 파싱
    if not names:
        for line in out.splitlines():
            if "DirectShow video devices" in line:
                in_audio = False
            elif "DirectShow audio devices" in line:
                in_audio = True
            elif in_audio:
                m = re.search(r'"([^"]+)"', line)
                if m:
                    names.append(m.group(1))
    return names


def guess_system_device(devices: list) -> str:
    """시스템 소리 loopback 장치 추정(Stereo Mix/가상 오디오 등)."""
    keys = ["stereo mix", "스테레오 믹스", "what u hear", "wave out",
            "virtual-audio", "cable output", "voicemeeter", "loopback", "믹스"]
    for d in devices:
        dl = d.lower()
        if any(k in dl for k in keys):
            return d
    return ""


def guess_mic_device(devices: list) -> str:
    keys = ["microphone", "마이크", "mic"]
    for d in devices:
        dl = d.lower()
        if any(k in dl for k in keys):
            return d
    return devices[0] if devices else ""


def build_command(ffmpeg, out_path, *, audio_mode="none", mic="", system="",
                  fps=30, crf=23, abitrate="192k"):
    """ffmpeg 명령 인자 리스트 생성."""
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "warning",
           "-f", "gdigrab", "-framerate", str(int(fps)), "-i", "desktop"]
    audios = []
    if audio_mode in ("mic", "both") and mic:
        audios.append(mic)
    if audio_mode in ("system", "both") and system:
        audios.append(system)
    # 260618-7: 마이크·시스템이 같은 장치면 동일 신호를 두 번 섞어 '음성 2중'으로 들리던 문제 →
    #   중복 장치 제거(한 번만 캡처). (노트북에서 마이크가 스피커 소리를 함께 잡는 음향상 이중은
    #   물리적 현상이라 코드로 막을 수 없음 — 설정에서 '시스템'만 선택 권장.)
    _seen = set(); _uniq = []
    for a in audios:
        k = a.strip().lower()
        if k not in _seen:
            _seen.add(k); _uniq.append(a)
    audios = _uniq
    for a in audios:
        cmd += ["-f", "dshow", "-i", f"audio={a}"]
    # 인코딩
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(int(crf)),
            "-pix_fmt", "yuv420p", "-r", str(int(fps))]
    if len(audios) >= 2:
        cmd += ["-filter_complex", "[1:a][2:a]amix=inputs=2:duration=first[a]",
                "-map", "0:v", "-map", "[a]",
                "-c:a", "aac", "-b:a", abitrate]
    elif len(audios) == 1:
        cmd += ["-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", abitrate]
    else:
        cmd += ["-map", "0:v", "-an"]
    cmd += ["-movflags", "+faststart", str(out_path)]
    return cmd


def _nt_set_suspend(pid, suspend):
    try:
        PROCESS_ALL = 0x1F0FFF
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_ALL, False, int(pid))
        if not h:
            return False
        fn = (ctypes.windll.ntdll.NtSuspendProcess if suspend
              else ctypes.windll.ntdll.NtResumeProcess)
        fn(h)
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    except Exception:
        return False


class ScreenRecorder:
    def __init__(self, ffmpeg, out_path, *, audio_mode="none", mic="", system="",
                 fps=30, crf=23, abitrate="192k"):
        self.ffmpeg = ffmpeg
        self.out_path = str(out_path)
        self.audio_mode = audio_mode
        self.mic = mic
        self.system = system
        self.fps = fps
        self.crf = crf
        self.abitrate = abitrate
        self._proc = None
        self._paused = False

    def is_recording(self):
        return self._proc is not None and self._proc.poll() is None

    def is_paused(self):
        return self._paused

    def command(self):
        return build_command(self.ffmpeg, self.out_path, audio_mode=self.audio_mode,
                             mic=self.mic, system=self.system, fps=self.fps,
                             crf=self.crf, abitrate=self.abitrate)

    def start(self):
        if self.is_recording():
            return True, "이미 녹화 중입니다."
        if not self.ffmpeg or not os.path.isfile(self.ffmpeg):
            return False, "ffmpeg 를 찾을 수 없습니다."
        try:
            Path(self.out_path).parent.mkdir(parents=True, exist_ok=True)
            self._proc = subprocess.Popen(
                self.command(), stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW)
            self._paused = False
            return True, "녹화 시작"
        except Exception as e:
            self._proc = None
            return False, f"녹화 시작 실패: {e}"

    def pause(self):
        if self.is_recording() and not self._paused:
            if _nt_set_suspend(self._proc.pid, True):
                self._paused = True

    def resume(self):
        if self.is_recording() and self._paused:
            if _nt_set_suspend(self._proc.pid, False):
                self._paused = False

    def stop(self):
        p = self._proc
        if p is None:
            return
        try:
            if self._paused:
                _nt_set_suspend(p.pid, False)
                self._paused = False
            if p.poll() is None:
                try:
                    p.stdin.write(b"q")
                    p.stdin.flush()
                except Exception:
                    pass
                try:
                    p.wait(timeout=8)
                except Exception:
                    p.terminate()
                    try:
                        p.wait(timeout=3)
                    except Exception:
                        p.kill()
        finally:
            self._proc = None
            self._paused = False
