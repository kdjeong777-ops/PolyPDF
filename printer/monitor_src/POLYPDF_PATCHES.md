# PolyPDF — MFILEMON 고친 곳

원본: MFILEMON 1.6.1 (Lorenzo Monti, GPL-3.0-or-later) — <https://github.com/lomo74/mfilemon>, 태그 `v1.6.1`, 커밋 `0ef82b651b9e3579688c1f48d97823f7f4164458`.
모니터 빌드에 필요한 `common/`·`monitor/` 만 들였다(설정 화면 `monitorUI/`·설치 프로그램은 들이지 않음). 라이선스 원문은 `LICENSE.txt`.

PolyPDF 가상 프린터의 포트 모니터로 쓰려고 아래만 바꿨다(가상 프린터 SOT §4.2). 바꾼 `.cpp`·`.h` 첫 줄에 이 문서를 가리키는 표시를 넣었다.

| 파일 | 바꾼 것 | 까닭 |
| --- | --- | --- |
| `common/defs.cpp` | 모니터 이름 `PolyPDF Port Monitor`, 포트 설명 `PolyPDF port`, 창 제목 `PolyPDF port monitor` | 원래 이름의 mfilemon 을 쓰는 다른 프로그램(예: TSplus)과 설정·제거가 부딪히지 않게 |
| `monitor/mfilemon.def` | `LIBRARY polypdfmon` | DLL 이름 `polypdfmon.dll` |
| `monitor/log.cpp` | 기록 파일 `polypdfmon.log` | 같은 까닭 |
| `monitor/monitor.cpp` | 설정 화면 DLL 이름 `polypdfmonui.dll`(동봉하지 않음) | 다른 프로그램의 `mfilemonui.dll` 을 불러오지 않게. 포트 설정은 레지스트리로만 한다 |
| `monitor/portlist.cpp` | `POLYPDF_NO_RUNAS` 일 때 '다른 계정으로 실행'(계정·비밀번호, OpenSSL 암호화)을 빼고 비밀번호 칸을 비워 둔다 | 비밀번호를 저장하지 않는다. 인쇄 후 명령은 스풀러 계정으로만 돌고, 사용자 화면의 일은 사용자 예약 작업이 한다(가상 프린터 SOT §4.1). OpenSSL 없이 빌드된다 |
| `monitor/resource.rc` | 파일 설명·내부 이름·원래 파일 이름·제품 이름에 PolyPDF 판임을 적음(저작권 표기는 그대로) | 고친 판임을 드러낸다(GPL 제5조) |

빌드: `printer\build_monitor.bat`(MSVC x64, `POLYPDF_NO_RUNAS` 정의) — CI(`release.yml`)가 부른다.
원본을 새 판으로 바꿀 때는 위 표를 다시 적용하고 가상 프린터 SOT §0 에 적는다.
