# -*- coding: utf-8 -*-
"""Cancelling a conversion must not leave a broken file on disk."""
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
APP = _os.path.join(_ROOT, "ytdlp_gui.pyw")
EXE = _os.path.join(_ROOT, "dist", "YT-DLP GUI.exe")

import glob, importlib.util, os, subprocess, tempfile, time, tkinter as tk

spec = importlib.util.spec_from_file_location("gui", APP)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

work = tempfile.mkdtemp(prefix="cancel_")
src = os.path.join(work, "src.mp4")
# a long clip, so there is time to cancel
subprocess.run([m.FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi",
                "-i", "testsrc=duration=40:size=1280x720:rate=30",
                "-c:v", "libx264", "-preset", "ultrafast", src], check=True)
print("source:", round(os.path.getsize(src) / 1024 / 1024, 1), "MB")

r = tk.Tk(); r.withdraw()
app = m.App(r)
app.src.set(src)
app.cfolder.set(work)
app.cname.set("result")
app.cfmt.set("mov")            # a heavy codec keeps the conversion slow
app.comp.set("Medium")
app.cres.set("Best")
app.start_convert()

for _ in range(200):           # wait until the file shows up and starts growing
    r.update()
    time.sleep(0.05)
    hits = glob.glob(os.path.join(work, "result*.mov"))
    if hits and os.path.getsize(hits[0]) > 400_000:
        break
out = glob.glob(os.path.join(work, "result*.mov"))
print("file started growing:", bool(out),
      round(os.path.getsize(out[0]) / 1024, 0) if out else 0, "KB")
assert out, "conversion never started"

app.cancel()
for _ in range(120):           # let the worker finish its finally block
    r.update()
    time.sleep(0.05)
    if not app.busy:
        break

left = glob.glob(os.path.join(work, "result*.mov"))
print("on disk after cancel:", [os.path.basename(f) for f in left] or "nothing")
print("status:", app.status.cget("text"))
assert not left, "a broken file survived the cancel!"
r.destroy()

for f in glob.glob(os.path.join(work, "*")):
    os.remove(f)
os.rmdir(work)
print("ALL OK")
