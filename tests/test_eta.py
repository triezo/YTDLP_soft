# -*- coding: utf-8 -*-
"""Our own ETA: steady speed, bursty fragments, switching streams."""
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
m.time.monotonic = lambda: clock[0]          # drive the clock by hand

app._reset_progress()
app._on_line("[info] Downloading 1 format(s): 137+140")
print("streams detected:", app._dl_streams)
assert app._dl_streams == 2

def feed(done, total, dt=0.5):
    clock[0] += dt
    app._on_progress([str(done), str(total), "NA", "NA", "NA"])

# --- video at a steady 10 MB/s, up to 75% so it does not finish
for i in range(1, 13):
    feed(i * 5 * MB, VIDEO)
print("steady speed ->", statuses[-1])
assert "Video" in statuses[-1] and "left" in statuses[-1]
# 20 MB left at 10 MB/s is exactly two seconds
assert "left 00:02" in statuses[-1], statuses[-1]

# run to the end: time-left must disappear, not go negative
for i in range(13, 20):
    feed(i * 5 * MB, VIDEO)
print("after the end ->", statuses[-1])
assert "left" not in statuses[-1] and "-" not in statuses[-1]

# --- bursts: feast then famine, the way fragments arrive
app._reset_progress(); app._dl_streams = 2; statuses.clear()
done = 0
BIG = 400 * MB                        # headroom so the transfer never completes
for i in range(30):
    step = (12 * MB) if i % 4 == 0 else (0.4 * MB)   # a burst every fourth sample
    done += step
    feed(done, BIG)
import re as _re
etas = [_re.search(r"left (\d+):(\d+)", s) for s in statuses[-8:]]
etas = [e for e in etas if e]
print("bursts, last ETA values:", [e.group(0) for e in etas])
secs = [int(e.group(1)) * 60 + int(e.group(2)) for e in etas]
spread = max(secs) - min(secs)
print("ETA spread across bursts:", spread, "s")
assert spread < 25, f"ETA still jumps around: {secs}"

# --- switching from video to audio
statuses.clear()
feed(1 * MB, AUDIO)
feed(2 * MB, AUDIO)
feed(3 * MB, AUDIO)
print("after the stream switch ->", statuses[-1])
assert "Audio" in statuses[-1], "the switch to audio went unnoticed"
assert "file 2 of 2" in statuses[-1]

# --- a single file (mp3): no "file 1 of 1" clutter
app._reset_progress(); statuses.clear()
for i in range(1, 12):
    feed(i * MB, 10 * MB)
print("single file ->", statuses[-1])
assert "Downloading" in statuses[-1] and " of " not in statuses[-1]

# --- graph: history accumulates and draws without errors
app._reset_progress()
r.deiconify(); r.geometry("640x790")       # the canvas needs a real size
if not app.graph_open:
    app._toggle_graph()
r.update(); r.update_idletasks()
print("canvas size:", app.graph.winfo_width(), "x", app.graph.winfo_height())
done = 0
for i in range(60):
    done += (3 + (i % 7)) * MB
    feed(done, 400 * MB)
r.update()
print("points in history:", len(app._speed_hist))
assert 10 < len(app._speed_hist) <= app.SPEED_POINTS
app._draw_graph()
r.update()
items = app.graph.find_all()
print("items drawn:", len(items))
assert len(items) > 4, "the graph is empty"

# an empty history must not break drawing
app._reset_progress()
app._draw_graph(); r.update()
print("an empty graph draws without errors")

r.destroy()
print("ALL OK")
