# -*- coding: utf-8 -*-
"""Перетаскивание: регистрация целей и поведение по типам содержимого."""
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
print("перетаскивание доступно:", app.dnd_ok)
assert app.dnd_ok, "цели не зарегистрировались"


class Ev:
    def __init__(self, data):
        self.data = data


# --- ссылка на вкладке загрузки
app.nb.select(1)
app._on_drop(Ev("https://youtu.be/abc123"))
r.update()
print("ссылка ->", app.url.get(), "| вкладка", app.nb.index(app.nb.select()))
assert app.url.get() == "https://youtu.be/abc123"
assert app.nb.index(app.nb.select()) == 0, "не переключилось на загрузку"

# --- видеофайл, брошенный на вкладку загрузки
app.nb.select(0)
app._on_drop(Ev("{%s}" % vid))
r.update()
print("видео ->", os.path.basename(app.src.get()), "| вкладка",
      app.nb.index(app.nb.select()))
assert app.src.get() == vid, app.src.get()
assert app.nb.index(app.nb.select()) == 1, "не ушло в конвертацию"

# --- PNG на вкладку картинки
app.nb.select(2)
app._on_drop(Ev("{%s}" % png))
r.update()
print("PNG ->", app.img_w, "×", app.img_h)
assert (app.img_w, app.img_h) == (4, 3), "PNG не загрузился"

# --- JPEG (свой декодер не умеет, идёт через ffmpeg)
app._on_drop(Ev("{%s}" % jpg))
r.update()
print("JPEG ->", app.img_w, "×", app.img_h, "|", app.status.cget("text")[:50])
assert (app.img_w, app.img_h) == (64, 48), "JPEG не прочитался через ffmpeg"

# --- картинка, бронённая на вкладку загрузки, всё равно откроется как картинка
app.nb.select(0)
app._on_drop(Ev("{%s}" % png))
r.update()
assert app.nb.index(app.nb.select()) == 2, "картинка не ушла на свою вкладку"
print("картинка с вкладки загрузки уехала на вкладку Image — ОК")

# --- пути с пробелами
spaced = os.path.join(work, "two words.png")
open(spaced, "wb").write(open(png, "rb").read())
app._on_drop(Ev("{%s}" % spaced))
r.update()
assert app.img_w == 4, "путь с пробелом не разобрался"
print("путь с пробелами — ОК")

# --- мусор
app._on_drop(Ev("просто текст"))
r.update()
print("мусор ->", app.status.cget("text"))
assert "not a file or a link" in app.status.cget("text")

r.destroy()
for f in os.listdir(work):
    os.remove(os.path.join(work, f))
os.rmdir(work)
print("ALL OK")
