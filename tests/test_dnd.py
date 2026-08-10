# -*- coding: utf-8 -*-
"""Drag-and-drop: target registration and behaviour per payload type."""
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
APP = _os.path.join(_ROOT, "ytdlp_gui.pyw")
EXE = _os.path.join(_ROOT, "dist", "YT-DLP GUI.exe")

import importlib.util, os, subprocess, tempfile, tkinter as tk
spec = importlib.util.spec_from_file_location("gui", APP)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

work = tempfile.mkdtemp(prefix="dnd_")
png = os.path.join(work, "pic.png")
open(png, "wb").write(m.encode_png(4, 3, bytes(bytearray(4 * 3 * 4))))
jpg = os.path.join(work, "photo.jpg")
subprocess.run([m.FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi",
                "-i", "testsrc=duration=1:size=64x48:rate=1",
                "-frames:v", "1", jpg], check=True)
vid = os.path.join(work, "clip.mp4")
subprocess.run([m.FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi",
                "-i", "testsrc=duration=1:size=64x48:rate=5",
                "-c:v", "libx264", vid], check=True)

r = tk.Tk(); r.withdraw()
app = m.App(r)
r.update()
print("drag-and-drop available:", app.dnd_ok)
assert app.dnd_ok, "drop targets were not registered"


class Ev:
    def __init__(self, data):
        self.data = data


# --- a link while the Convert tab is open
app.nb.select(1)
app._on_drop(Ev("https://youtu.be/abc123"))
r.update()
print("link ->", app.url.get(), "| tab", app.nb.index(app.nb.select()))
assert app.url.get() == "https://youtu.be/abc123"
assert app.nb.index(app.nb.select()) == 0, "did not switch to Download"

# --- a video dropped on the Download tab
app.nb.select(0)
app._on_drop(Ev("{%s}" % vid))
r.update()
print("video ->", os.path.basename(app.src.get()), "| tab",
      app.nb.index(app.nb.select()))
assert app.src.get() == vid, app.src.get()
assert app.nb.index(app.nb.select()) == 1, "did not move to Convert"

# --- a PNG on the Image tab
app.nb.select(2)
app._on_drop(Ev("{%s}" % png))
r.update()
print("PNG ->", app.img_w, "×", app.img_h)
assert (app.img_w, app.img_h) == (4, 3), "PNG did not load"

# --- JPEG: our decoder cannot read it, so it goes through ffmpeg
app._on_drop(Ev("{%s}" % jpg))
r.update()
print("JPEG ->", app.img_w, "×", app.img_h, "|", app.status.cget("text")[:50])
assert (app.img_w, app.img_h) == (64, 48), "JPEG was not read through ffmpeg"

# --- an image dropped on Download still opens on the Image tab
app.nb.select(0)
app._on_drop(Ev("{%s}" % png))
r.update()
assert app.nb.index(app.nb.select()) == 2, "image did not move to its own tab"
print("image dropped on Download moved to the Image tab: OK")

# --- paths containing spaces
spaced = os.path.join(work, "two words.png")
open(spaced, "wb").write(open(png, "rb").read())
app._on_drop(Ev("{%s}" % spaced))
r.update()
assert app.img_w == 4, "a path with a space was not parsed"
print("paths with spaces: OK")

# --- junk payload
app._on_drop(Ev("just some text"))
r.update()
print("junk ->", app.status.cget("text"))
assert "not a file or a link" in app.status.cget("text")

r.destroy()
for f in os.listdir(work):
    os.remove(os.path.join(work, f))
os.rmdir(work)
print("ALL OK")
