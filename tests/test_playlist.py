# -*- coding: utf-8 -*-
"""Плейлист: что показывает статус на втором и третьем ролике."""
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
APP = _os.path.join(_ROOT, "ytdlp_gui.pyw")
EXE = _os.path.join(_ROOT, "dist", "YT-DLP GUI.exe")

import importlib.util, tkinter as tk
spec = importlib.util.spec_from_file_location("gui", APP)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

r = tk.Tk(); r.withdraw()
app = m.App(r)
statuses = []
app.set_status = lambda t, c=None: statuses.append(t)

MB = 1 << 20
clock = [1000.0]
m.time.monotonic = lambda: clock[0]
app._reset_progress()


def feed(done, total, dt=0.5):
    clock[0] += dt
    app._on_progress([str(done), str(total), "NA", "NA", "NA"])


VID, AUD = 60 * MB, 5 * MB
for item in (1, 2, 3):                       # три ролика плейлиста
    app._on_line(f"[download] Downloading item {item} of 3")
    app._on_line("[info] Downloading 1 format(s): 137+140")
    for i in range(1, 7):                    # видео
        feed(i * 10 * MB, VID)
    print(f"ролик {item}, видео -> {statuses[-1]}")
    assert "Video" in statuses[-1], f"на ролике {item} видео названо неверно"
    assert f"video {item} of 3" in statuses[-1]
    for i in range(1, 5):                    # звук
        feed(i * 1 * MB, AUD)
    print(f"ролик {item}, звук  -> {statuses[-1]}")
    assert "Audio" in statuses[-1] and "file 2 of 2" in statuses[-1]
r.destroy()
print("ALL OK")
