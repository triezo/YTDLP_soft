# -*- coding: utf-8 -*-
"""Run every test: python tests/run_all.py

They open real windows and drive real ffmpeg, so they take a minute.
test_exe.py needs a built dist/YT-DLP GUI.exe and is skipped without one.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXE = os.path.join(ROOT, "dist", "YT-DLP GUI.exe")

ORDER = ["test_transform.py", "test_imgtab.py", "test_dnd.py", "test_eta.py",
         "test_playlist.py", "test_focus.py", "test_focusring.py",
         "test_polish.py", "test_cancel.py", "test_close.py", "test_exe.py"]

fails = []
for name in ORDER:
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        continue
    if name == "test_exe.py" and not os.path.exists(EXE):
        print(f"{name:<22} skipped, no built exe")
        continue
    r = subprocess.run([sys.executable, path], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    ok = "ALL OK" in (r.stdout or "")
    print(f"{name:<22} {'OK' if ok else 'FAILED'}")
    if not ok:
        fails.append(name)
        tail = (r.stdout or "") + (r.stderr or "")
        print("\n".join("      " + ln for ln in tail.strip().split("\n")[-12:]))

print("\nresult:", "all green" if not fails else f"failed: {', '.join(fails)}")
sys.exit(1 if fails else 0)
