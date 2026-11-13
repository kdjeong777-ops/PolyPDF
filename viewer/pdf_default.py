# -*- coding: utf-8 -*-
"""기본 PDF 앱으로 설정 — Windows 기본 앱 화면을 연다 (마스터 SOT §14.10, 261107-14).

Windows 는 앱이 기본 앱을 스스로 바꾸지 못하게 막는다 — 앱은 **후보로 보이게만** 하고 그 화면을 연다.
- 설치판: 설치 프로그램이 넣은 HKLM 등록(`installer/PolyPDF.iss` [Registry])이 이 exe 를 가리키면 아무것도 쓰지 않는다.
  예전에 앱이 쓴 HKCU 키가 있으면 지운다(HKCU 가 HKLM 을 가려 옛 exe 를 열지 않게).
- 설치 정보 없음(휴대용·zip): 같은 꼴을 HKCU 에 쓴다.
레지스트리는 `Reg` 하나로만 만진다 — 검사는 가짜 `Reg` 를 넘긴다(실제 레지스트리를 건드리지 않는다).
"""
from __future__ import annotations

import os

from viewer.branding import APP_NAME

APP = "PolyPDF"                             # 내부 ID — 등록 키·값 이름·기본 앱 화면 URI(261114-6, 마스터 §1.1: 바꾸지 않는다)
PROG_ID = "PolyPDF.pdf"                     # installer/PolyPDF.iss MyProgId 와 같다
CAPS = r"Software\PolyPDF\Capabilities"
REG_APPS = r"Software\RegisteredApplications"
OPEN_WITH = r"Software\Classes\.pdf\OpenWithProgids"
PROG_KEY = r"Software\Classes\%s" % PROG_ID
URI_MACHINE = "ms-settings:defaultapps?registeredAppMachine=" + APP
URI_USER = "ms-settings:defaultapps?registeredAppUser=" + APP
URI_PLAIN = "ms-settings:defaultapps"
HKLM, HKCU = "HKLM", "HKCU"


class Reg:
    """winreg 얇은 감싸기 — (뿌리, 경로, 이름) 으로 읽기·쓰기·지우기. 실패는 None/False."""

    def __init__(self):
        import winreg
        self.w = winreg
        self.roots = {HKLM: winreg.HKEY_LOCAL_MACHINE, HKCU: winreg.HKEY_CURRENT_USER}

    def get(self, root, path, name=""):
        w = self.w
        for view in ((w.KEY_WOW64_64KEY, w.KEY_WOW64_32KEY) if root == HKLM else (0,)):
            try:
                with w.OpenKey(self.roots[root], path, 0, w.KEY_READ | view) as k:
                    return w.QueryValueEx(k, name)[0]
            except OSError:
                continue
        return None

    def has_key(self, root, path):
        try:
            with self.w.OpenKey(self.roots[root], path):
                return True
        except OSError:
            return False

    def set(self, root, path, name, value, none_type=False):
        w = self.w
        with w.CreateKey(self.roots[root], path) as k:
            if none_type:
                w.SetValueEx(k, name, 0, w.REG_NONE, b"")
            else:
                w.SetValueEx(k, name, 0, w.REG_SZ, value)

    def delete_value(self, root, path, name):
        try:
            with self.w.OpenKey(self.roots[root], path, 0, self.w.KEY_SET_VALUE) as k:
                self.w.DeleteValue(k, name)
            return True
        except OSError:
            return False

    def delete_tree(self, root, path):
        """path 와 그 아래를 지운다(아래부터)."""
        w = self.w
        try:
            with w.OpenKey(self.roots[root], path, 0, w.KEY_READ) as k:
                subs = []
                i = 0
                while True:
                    try:
                        subs.append(w.EnumKey(k, i)); i += 1
                    except OSError:
                        break
            for s in subs:
                self.delete_tree(root, path + "\\" + s)
            w.DeleteKey(self.roots[root], path)
            return True
        except OSError:
            return False


def _cmd(exe: str) -> str:
    return '"%s" "%%1"' % exe


def _same_exe(cmd, exe: str) -> bool:
    if not cmd:
        return False
    c = str(cmd).strip()
    first = c[1:c.find('"', 1)] if c.startswith('"') else c.split(" ")[0]
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(exe))


def installed_for(exe: str, reg) -> bool:
    """설치 프로그램의 HKLM 등록이 이 exe 를 가리키나(설치판에서 실행 중)."""
    return bool(reg.get(HKLM, REG_APPS, APP)) and _same_exe(reg.get(HKLM, PROG_KEY + r"\shell\open\command"), exe)


def remove_user_keys(reg, exe_name: str = "PolyPDF.exe") -> list:
    """앱이 HKCU 에 쓴 PolyPDF 키만 지운다 — `.pdf` 키·다른 앱의 값·UserChoice 는 그대로. 지운 것 목록."""
    done = []
    if reg.delete_tree(HKCU, PROG_KEY):
        done.append(PROG_KEY)
    if reg.delete_value(HKCU, OPEN_WITH, PROG_ID):
        done.append(OPEN_WITH + "\\" + PROG_ID)
    if reg.delete_value(HKCU, REG_APPS, APP):
        done.append(REG_APPS + "\\" + APP)
    if reg.delete_tree(HKCU, r"Software\PolyPDF\Capabilities"):
        done.append(CAPS)
    if reg.delete_tree(HKCU, r"Software\Classes\Applications\%s" % exe_name):
        done.append(r"Software\Classes\Applications\%s" % exe_name)
    return done


def write_user_keys(reg, exe: str, desc: str, app_desc: str) -> None:
    """설치 프로그램 [Registry] 와 같은 꼴을 HKCU 에 — 휴대용·zip 판."""
    reg.set(HKCU, PROG_KEY, "", desc)
    reg.set(HKCU, PROG_KEY + r"\DefaultIcon", "", '"%s",0' % exe)
    reg.set(HKCU, PROG_KEY + r"\shell\open\command", "", _cmd(exe))
    reg.set(HKCU, OPEN_WITH, PROG_ID, None, none_type=True)
    reg.set(HKCU, CAPS, "ApplicationName", APP_NAME)          # 기본 앱 화면에 보이는 이름(261114-6)
    reg.set(HKCU, CAPS, "ApplicationDescription", app_desc)
    reg.set(HKCU, CAPS + r"\FileAssociations", ".pdf", PROG_ID)
    reg.set(HKCU, REG_APPS, APP, CAPS)
    base = os.path.basename(exe)
    reg.set(HKCU, r"Software\Classes\Applications\%s\shell\open\command" % base, "", _cmd(exe))
    reg.set(HKCU, r"Software\Classes\Applications\%s" % base, "FriendlyAppName", APP_NAME)   # '연결 프로그램' 목록 이름


def prepare(exe: str, frozen: bool, reg, desc: str = "PDF (" + APP_NAME + ")", app_desc: str = APP_NAME) -> dict:
    """무엇을 할지 정하고 레지스트리를 맞춘다. → {"kind": "dev"|"installed"|"user", "uris": [...], "removed": [...]}"""
    if not frozen:
        return {"kind": "dev", "uris": [], "removed": []}
    if installed_for(exe, reg):
        return {"kind": "installed", "uris": [URI_MACHINE, URI_PLAIN],
                "removed": remove_user_keys(reg, os.path.basename(exe))}
    write_user_keys(reg, exe, desc, app_desc)
    return {"kind": "user", "uris": [URI_USER, URI_PLAIN], "removed": []}


def open_settings(uris, opener) -> str:
    """차례로 열어 본다 — 연 URI, 다 못 열면 ""."""
    for u in uris:
        try:
            if opener(u):
                return u
        except Exception:
            continue
    return ""
