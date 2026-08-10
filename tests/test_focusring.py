# -*- coding: utf-8 -*-
"""The dotted focus ring is gone, everything else still in place."""
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
    assert gone not in els, f"{gone} is still in the layout"
    assert must in els, f"{must} went missing!"
print("dotted ring removed, labels still there")

# tabs still switch and still do not jump sideways
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
assert len(set(bounds)) == 1, "the tabs moved"
assert app.nb.index("current") == 2, "switching broke"

# buttons are alive and focusable
app.nb.select(1)
r.update_idletasks()
print("Convert button:", app.cbtn.cget("text"), "| state:", app.cbtn.state())
app.cbtn.focus_force(); r.update()
print("focus on the button:", r.focus_get() is app.cbtn)
r.destroy()
print("ALL OK")
