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

print("коэффициент масштаба k =", round(app.k, 3))
print("размер окна:", r.winfo_width(), "x", r.winfo_height())
assert abs(app.k - 1.0) < 0.01, "на этом экране масштаб должен быть 1.0"
exp_h = min(790, r.winfo_screenheight() - 70)   # та же формула, что в коде
assert (r.winfo_width(), r.winfo_height()) == (640, exp_h), \
    f"размер при 100% неожиданный: {r.winfo_width()}x{r.winfo_height()}"

# окно по центру
x, y = r.winfo_x(), r.winfo_y()
cx = (r.winfo_screenwidth() - r.winfo_width()) // 2
print(f"позиция: {x},{y}  (ожидали x≈{cx})")
assert abs(x - cx) <= 2, "окно не по центру"

# вкладки не прыгают
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
print("границы вкладок:", set(bounds))
assert len(set(bounds)) == 1, "вкладки всё ещё скачут"

# формула для экрана 150%
for dpi in (96, 120, 144):
    k = max(dpi / 96.0, 1.0)
    print(f"  при {int(dpi/96*100)}%: окно {int(640*k)}x{int(700*k)}")
r.destroy()
print("ALL OK")
