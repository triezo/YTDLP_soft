# -*- coding: utf-8 -*-
"""Пунктирная рамка фокуса убрана, но всё остальное на месте."""
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
APP = _os.path.join(_ROOT, "ytdlp_gui.pyw")
EXE = _os.path.join(_ROOT, "dist", "YT-DLP GUI.exe")

import importlib.util, tkinter as tk
from tkinter import ttk
spec = importlib.util.spec_from_file_location("gui", APP)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

m.setup_windows_look()
r = tk.Tk()
app = m.App(r)
r.deiconify(); r.update(); r.update_idletasks()
s = ttk.Style(r)


def flatten(layout, out=None):
    out = [] if out is None else out
    for el, opts in layout:
        out.append(el)
        if opts.get("children"):
            flatten(opts["children"], out)
    return out


for style, gone, must in (("TNotebook.Tab", "Notebook.focus", "Notebook.label"),
                          ("TButton", "Button.focus", "Button.label")):
    els = flatten(s.layout(style))
    print(f"{style:<16} {els}")
    assert gone not in els, f"{gone} всё ещё в разметке"
    assert must in els, f"потеряли {must}!"
print("пунктир убран, подписи на месте")

# вкладки по-прежнему переключаются и не скачут
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
assert len(set(bounds)) == 1, "вкладки поехали"
assert app.nb.index("current") == 2, "переключение сломалось"

# кнопки живы и жмутся
app.nb.select(1)
r.update_idletasks()
print("кнопка Convert:", app.cbtn.cget("text"), "| состояние:", app.cbtn.state())
app.cbtn.focus_force(); r.update()
print("фокус на кнопке:", r.focus_get() is app.cbtn)
r.destroy()
print("ALL OK")
