# -*- coding: utf-8 -*-
"""Подсветка рамки на фокусе и клик по тексту подсказки."""
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
        # только наши поля: tk.Entry внутри tk.Frame-рамки
        # (у Combobox тоже есть внутренний Entry, но он не наш)
        if (type(ch) is tk.Entry and type(ch.master) is tk.Frame
                and ch.master.cget("bg") in (m.LINE, m.ACCENT)):
            out.append(ch)
        entries_of(ch, out)
    return out


# поля на скрытых вкладках фокус не принимают — перебираем по вкладкам
fields, bad = [], []
for i, tabname in enumerate(("Download", "Convert", "Image")):
    app.nb.select(i)
    r.update(); r.update_idletasks()
    tab = r.nametowidget(app.nb.tabs()[i])
    tab_fields = entries_of(tab)
    fields += tab_fields
    print(f"{tabname:<9} полей: {len(tab_fields)}")
    for e in tab_fields:
        wrap = e.master
        e.focus_force(); r.update(); r.update_idletasks()
        if wrap.cget("bg") != m.ACCENT:
            bad.append((tabname, str(e).rsplit(".", 3)[-1], "не загорелась"))
        r.focus_force(); r.update(); r.update_idletasks()
        if wrap.cget("bg") != m.LINE:
            bad.append((tabname, str(e).rsplit(".", 3)[-1], "не погасла"))
print("проблемы с подсветкой:", bad or "нет — все загораются и гаснут")
assert not bad, bad

# клик по подсказке должен отдавать фокус полю
hints = []
for e in fields:
    for ch in e.winfo_children():
        if isinstance(ch, tk.Label):
            hints.append((e, ch))
print("полей с подсказкой:", len(hints))
for e, lbl in hints:
    # показываем вкладку, на которой лежит поле
    # путь вкладки 0 является префиксом путей других вкладок,
    # поэтому сравниваем с точкой-разделителем
    for i in range(3):
        if str(e).startswith(str(r.nametowidget(app.nb.tabs()[i])) + "."):
            app.nb.select(i)
            break
    r.focus_force(); r.update(); r.update_idletasks()
    if lbl.winfo_manager() != "place":
        continue                       # подсказка скрыта — поле не пустое
    lbl.event_generate("<Button-1>")
    r.update(); r.update_idletasks()
    got = r.focus_get()
    assert got is e, f"клик по подсказке не сфокусировал поле: {lbl.cget('text')!r}"
    assert e.master.cget("bg") == m.ACCENT, "рамка не загорелась после клика"
    assert lbl.winfo_manager() != "place", "подсказка не спряталась"
print("клик по тексту подсказки: фокус и рамка — ОК")
r.destroy()
print("ALL OK")
