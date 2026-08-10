# -*- coding: utf-8 -*-
"""Проверка собранного exe тем же способом, каким его читает сама программа."""
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
APP = _os.path.join(_ROOT, "ytdlp_gui.pyw")
EXE = _os.path.join(_ROOT, "dist", "YT-DLP GUI.exe")

import subprocess, time, os

EXE = EXE
URL = "https://www.youtube.com/watch?v=VphzfqoaoNs"

# 1) кириллица через пайп с utf-8 — как в _worker
p = subprocess.run(
    [EXE, "--__run_ytdlp__", "--simulate", "--no-playlist", "--print", "%(title)s", URL],
    capture_output=True, text=True, encoding="utf-8", errors="replace",
    creationflags=subprocess.CREATE_NO_WINDOW, timeout=300)
title = p.stdout.strip()
print("заголовок:", title)
assert "Баястан" in title, "кириллица побилась при передаче через пайп!"
print("кириллица через пайп: ОК")

# 2) окно действительно открывается
proc = subprocess.Popen([EXE])
time.sleep(12)
alive = proc.poll() is None
print("окно живо через 12 c:", alive)
if alive:
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                   capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
assert alive, "программа упала при старте"
print("ALL OK")
