# -*- coding: utf-8 -*-
"""Отмена конвертации не должна оставлять битый файл на диске."""
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
# длинный ролик, чтобы успеть отменить
subprocess.run([m.FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi",
                "-i", "testsrc=duration=40:size=1280x720:rate=30",
                "-c:v", "libx264", "-preset", "ultrafast", src], check=True)
print("исходник:", round(os.path.getsize(src) / 1024 / 1024, 1), "МБ")

r = tk.Tk(); r.withdraw()
app = m.App(r)
app.src.set(src)
app.cfolder.set(work)
app.cname.set("result")
app.cfmt.set("mov")            # тяжёлый кодек — конвертация небыстрая
app.comp.set("Medium")
app.cres.set("Best")
app.start_convert()

for _ in range(200):           # ждём, пока файл появится и начнёт расти
    r.update()
    time.sleep(0.05)
    hits = glob.glob(os.path.join(work, "result*.mov"))
    if hits and os.path.getsize(hits[0]) > 400_000:
        break
out = glob.glob(os.path.join(work, "result*.mov"))
print("файл начал писаться:", bool(out),
      round(os.path.getsize(out[0]) / 1024, 0) if out else 0, "КБ")
assert out, "конвертация не стартовала"

app.cancel()
for _ in range(120):           # даём воркеру доработать finally
    r.update()
    time.sleep(0.05)
    if not app.busy:
        break

left = glob.glob(os.path.join(work, "result*.mov"))
print("после отмены на диске:", [os.path.basename(f) for f in left] or "пусто")
print("статус:", app.status.cget("text"))
assert not left, "битый файл остался после отмены!"
r.destroy()

for f in glob.glob(os.path.join(work, "*")):
    os.remove(f)
os.rmdir(work)
print("ALL OK")
