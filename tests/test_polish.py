# -*- coding: utf-8 -*-
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
APP = _os.path.join(_ROOT, "ytdlp_gui.pyw")
EXE = _os.path.join(_ROOT, "dist", "YT-DLP GUI.exe")

import importlib.util, tkinter as tk
spec = importlib.util.spec_from_file_location("gui", APP)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

m.setup_windows_look()
r = tk.Tk()
app = m.App(r)
r.update(); r.update_idletasks()

print("scale factor k =", round(app.k, 3))
print("window size:", r.winfo_width(), "x", r.winfo_height())
assert abs(app.k - 1.0) < 0.01, "scaling on this display should be 1.0"
exp_h = min(790, r.winfo_screenheight() - 70)   # the same formula the app uses
assert (r.winfo_width(), r.winfo_height()) == (640, exp_h), \
    f"unexpected size at 100%: {r.winfo_width()}x{r.winfo_height()}"

# window is centred
x, y = r.winfo_x(), r.winfo_y()
cx = (r.winfo_screenwidth() - r.winfo_width()) // 2
print(f"position: {x},{y}  (expected x~{cx})")
assert abs(x - cx) <= 2, "the window is not centred"

# tabs do not jump
bounds = []
for i in range(3):
    app.nb.select(i)
    r.update_idletasks()
    b, last = [], None
    for px in range(0, app.nb.winfo_width(), 2):
        try:
            idx = app.nb.index("@%d,18" % px)
        except tk.TclError:
            idx = None
        if idx != last:
            b.append(px); last = idx
    bounds.append(tuple(b))
print("tab boundaries:", set(bounds))
assert len(set(bounds)) == 1, "the tabs still jump"

# what the formula gives on a 150% display
for dpi in (96, 120, 144):
    k = max(dpi / 96.0, 1.0)
    print(f"  at {int(dpi/96*100)}%: window {int(640*k)}x{int(700*k)}")
r.destroy()
print("ALL OK")
