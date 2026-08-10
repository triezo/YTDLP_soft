# -*- coding: utf-8 -*-
"""Closing the window mid-job must not leave ffmpeg running."""
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
APP = _os.path.join(_ROOT, "ytdlp_gui.pyw")
EXE = _os.path.join(_ROOT, "dist", "YT-DLP GUI.exe")

import importlib.util, os, subprocess, tempfile, time, tkinter as tk

spec = importlib.util.spec_from_file_location("gui", APP)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def ffmpeg_count():
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "(Get-Process ffmpeg -EA SilentlyContinue).Count"],
                         capture_output=True, text=True,
                         creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
    return int(out or 0)


work = tempfile.mkdtemp(prefix="close_")
src = os.path.join(work, "src.mp4")
subprocess.run([m.FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi",
                "-i", "testsrc=duration=60:size=1280x720:rate=30",
                "-c:v", "libx264", "-preset", "ultrafast", src], check=True)

base = ffmpeg_count()
print("ffmpeg processes before start:", base)

r = tk.Tk(); r.withdraw()
app = m.App(r)
app.src.set(src); app.cfolder.set(work); app.cname.set("res")
app.cfmt.set("mov"); app.comp.set("Medium"); app.cres.set("Best")
app.start_convert()

for _ in range(100):
    r.update(); time.sleep(0.05)
    if ffmpeg_count() > base:
        break
during = ffmpeg_count()
print("ffmpeg while converting:", during)
assert during > base, "conversion did not start"

# emulate the close button; clear busy so no dialog blocks the test
app.busy = False           # no confirmation dialog in an automated run
app.on_close()
time.sleep(1.5)
after = ffmpeg_count()
print("ffmpeg after closing the window:", after)
assert after <= base, "ffmpeg kept running in the background!"

for f in os.listdir(work):
    try:
        os.remove(os.path.join(work, f))
    except OSError:
        pass
try:
    os.rmdir(work)
except OSError:
    pass
print("ALL OK")
