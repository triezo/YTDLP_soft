# -*- coding: utf-8 -*-
"""Border highlight on focus, and clicking the placeholder text."""
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
r.deiconify(); r.update(); r.update_idletasks()


def entries_of(widget, out=None):
    out = [] if out is None else out
    for ch in widget.winfo_children():
        # only our fields: a tk.Entry inside a tk.Frame border
        # (a Combobox has an inner Entry too, but it is not ours)
        if (type(ch) is tk.Entry and type(ch.master) is tk.Frame
                and ch.master.cget("bg") in (m.LINE, m.ACCENT)):
            out.append(ch)
        entries_of(ch, out)
    return out


# fields on hidden tabs cannot take focus, so walk tab by tab
fields, bad = [], []
for i, tabname in enumerate(("Download", "Convert", "Image")):
    app.nb.select(i)
    r.update(); r.update_idletasks()
    tab = r.nametowidget(app.nb.tabs()[i])
    tab_fields = entries_of(tab)
    fields += tab_fields
    print(f"{tabname:<9} fields: {len(tab_fields)}")
    for e in tab_fields:
        wrap = e.master
        e.focus_force(); r.update(); r.update_idletasks()
        if wrap.cget("bg") != m.ACCENT:
            bad.append((tabname, str(e).rsplit(".", 3)[-1], "did not light up"))
        r.focus_force(); r.update(); r.update_idletasks()
        if wrap.cget("bg") != m.LINE:
            bad.append((tabname, str(e).rsplit(".", 3)[-1], "did not go dark"))
print("highlight problems:", bad or "none, every field lights up and goes dark")
assert not bad, bad

# clicking the placeholder must hand focus to the entry
hints = []
for e in fields:
    for ch in e.winfo_children():
        if isinstance(ch, tk.Label):
            hints.append((e, ch))
print("fields with a placeholder:", len(hints))
for e, lbl in hints:
    # show the tab the field lives on
    # tab 0's path is a prefix of the other tabs' paths,
    # so compare with the dot separator
    for i in range(3):
        if str(e).startswith(str(r.nametowidget(app.nb.tabs()[i])) + "."):
            app.nb.select(i)
            break
    r.focus_force(); r.update(); r.update_idletasks()
    if lbl.winfo_manager() != "place":
        continue                       # placeholder hidden means the field is not empty
    lbl.event_generate("<Button-1>")
    r.update(); r.update_idletasks()
    got = r.focus_get()
    assert got is e, f"clicking the placeholder did not focus the field: {lbl.cget('text')!r}"
    assert e.master.cget("bg") == m.ACCENT, "the border did not light up after the click"
    assert lbl.winfo_manager() != "place", "the placeholder did not hide"
print("clicking the placeholder text: focus and border OK")
r.destroy()
print("ALL OK")
