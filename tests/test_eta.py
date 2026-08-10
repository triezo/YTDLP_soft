# -*- coding: utf-8 -*-
"""Проверка своего ETA: ровная скорость, рывки фрагментов, смена потока."""
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
APP = _os.path.join(_ROOT, "ytdlp_gui.pyw")
EXE = _os.path.join(_ROOT, "dist", "YT-DLP GUI.exe")

import importlib.util, time

spec = importlib.util.spec_from_file_location("gui", APP)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
import tkinter as tk
r = tk.Tk(); r.withdraw()
app = m.App(r); r.update()

statuses = []
app.set_status = lambda t, c=None: statuses.append(t)

MB = 1 << 20
VIDEO, AUDIO = 80 * MB, 6 * MB
clock = [1000.0]
m.time.monotonic = lambda: clock[0]          # управляем временем вручную

app._reset_progress()
app._on_line("[info] Downloading 1 format(s): 137+140")
print("потоков определено:", app._dl_streams)
assert app._dl_streams == 2

def feed(done, total, dt=0.5):
    clock[0] += dt
    app._on_progress([str(done), str(total), "NA", "NA", "NA"])

# --- видео: ровные 10 МБ/с, до 75% (не добегая до конца)
for i in range(1, 13):
    feed(i * 5 * MB, VIDEO)
print("ровная скорость ->", statuses[-1])
assert "Video" in statuses[-1] and "left" in statuses[-1]
# 20 МБ осталось при 10 МБ/с -> ровно 2 секунды
assert "left 00:02" in statuses[-1], statuses[-1]

# добегаем до конца: «осталось» должно исчезнуть, а не уйти в минус
for i in range(13, 20):
    feed(i * 5 * MB, VIDEO)
print("после конца ->", statuses[-1])
assert "left" not in statuses[-1] and "-" not in statuses[-1]

# --- рывки: то густо, то пусто (как на фрагментах)
app._reset_progress(); app._dl_streams = 2; statuses.clear()
done = 0
BIG = 400 * MB                        # запас, чтобы не добежать до конца
for i in range(30):
    step = (12 * MB) if i % 4 == 0 else (0.4 * MB)   # рывок раз в 4 отсчёта
    done += step
    feed(done, BIG)
import re as _re
etas = [_re.search(r"left (\d+):(\d+)", s) for s in statuses[-8:]]
etas = [e for e in etas if e]
print("рывки, последние ETA:", [e.group(0) for e in etas])
secs = [int(e.group(1)) * 60 + int(e.group(2)) for e in etas]
spread = max(secs) - min(secs)
print("разброс ETA на рывках:", spread, "с")
assert spread < 25, f"ETA всё ещё скачет: {secs}"

# --- переключение видео -> звук
statuses.clear()
feed(1 * MB, AUDIO)
feed(2 * MB, AUDIO)
feed(3 * MB, AUDIO)
print("после смены потока ->", statuses[-1])
assert "Audio" in statuses[-1], "не заметил переключение на звук"
assert "file 2 of 2" in statuses[-1]

# --- одиночный файл (mp3): без «файл 1 из 1»
app._reset_progress(); statuses.clear()
for i in range(1, 12):
    feed(i * MB, 10 * MB)
print("одиночный ->", statuses[-1])
assert "Downloading" in statuses[-1] and " of " not in statuses[-1]

# --- график: копится история и рисуется без ошибок
app._reset_progress()
r.deiconify(); r.geometry("640x790")       # канве нужен реальный размер
if not app.graph_open:
    app._toggle_graph()
r.update(); r.update_idletasks()
print("размер канвы:", app.graph.winfo_width(), "x", app.graph.winfo_height())
done = 0
for i in range(60):
    done += (3 + (i % 7)) * MB
    feed(done, 400 * MB)
r.update()
print("точек в истории:", len(app._speed_hist))
assert 10 < len(app._speed_hist) <= app.SPEED_POINTS
app._draw_graph()
r.update()
items = app.graph.find_all()
print("элементов нарисовано:", len(items))
assert len(items) > 4, "график пустой"

# пустая история не роняет отрисовку
app._reset_progress()
app._draw_graph(); r.update()
print("пустой график рисуется без ошибки")

r.destroy()
print("ALL OK")
