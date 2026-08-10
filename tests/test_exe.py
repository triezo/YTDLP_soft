# -*- coding: utf-8 -*-
"""Check the built exe the same way the app itself reads it."""
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
APP = _os.path.join(_ROOT, "ytdlp_gui.pyw")
EXE = _os.path.join(_ROOT, "dist", "YT-DLP GUI.exe")

import subprocess, time, os

EXE = EXE
URL = "https://www.youtube.com/watch?v=VphzfqoaoNs"

# 1) non-ASCII text through a utf-8 pipe, exactly as _worker does it
p = subprocess.run(
    [EXE, "--__run_ytdlp__", "--simulate", "--no-playlist", "--print", "%(title)s", URL],
    capture_output=True, text=True, encoding="utf-8", errors="replace",
    creationflags=subprocess.CREATE_NO_WINDOW, timeout=300)
title = p.stdout.strip()
print("title:", title)
# the Cyrillic here is test data on purpose: it is the real video
# title, and the whole point is that it survives the pipe intact
assert "Баястан" in title, "non-ASCII text was mangled on its way through the pipe!"
print("non-ASCII through the pipe: OK")

# 2) the window really does open
proc = subprocess.Popen([EXE])
time.sleep(12)
alive = proc.poll() is None
print("window alive after 12 s:", alive)
if alive:
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                   capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
assert alive, "the app crashed on startup"
print("ALL OK")
