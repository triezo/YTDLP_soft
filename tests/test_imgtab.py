# -*- coding: utf-8 -*-
"""Вкладка «Картинка» целиком: вставка -> поворот/отражение -> сохранение."""
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
APP = _os.path.join(_ROOT, "ytdlp_gui.pyw")
EXE = _os.path.join(_ROOT, "dist", "YT-DLP GUI.exe")

import importlib.util, os, subprocess, tempfile, tkinter as tk
spec = importlib.util.spec_from_file_location("gui", APP)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# кладём в буфер свою картинку — тест не должен зависеть от того,
# что там оставили предыдущие запуски
subprocess.run(["powershell", "-NoProfile", "-Command", """
Add-Type -AssemblyName System.Drawing,System.Windows.Forms
$b = New-Object Drawing.Bitmap 320,200
$g = [Drawing.Graphics]::FromImage($b)
$g.FillRectangle([Drawing.Brushes]::Red,0,0,160,100)
$g.FillRectangle([Drawing.Brushes]::Lime,160,0,160,100)
$g.FillRectangle([Drawing.Brushes]::Blue,0,100,160,100)
$g.FillRectangle([Drawing.Brushes]::Yellow,160,100,160,100)
$g.Dispose(); [Windows.Forms.Clipboard]::SetImage($b)
"""], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)

work = tempfile.mkdtemp(prefix="imgtab_")
r = tk.Tk(); r.withdraw()
app = m.App(r)
app.nb.select(2)
r.update()

# кнопки заблокированы, пока картинки нет
states = [str(b.cget("state")) for b in app.tr_btns] + [str(app.reset_btn.cget("state"))]
print("состояние кнопок до вставки:", set(states))
assert set(states) == {"disabled"}

app.paste_image()
r.update()
assert app.img_rgba, "картинка из буфера не прочиталась"
w0, h0 = app.img_w, app.img_h
print(f"вставлено: {w0}×{h0}")
states = [str(b.cget("state")) for b in app.tr_btns]
print("после вставки кнопки:", set(states))
assert "disabled" not in states


def corner(rgba, w, x, y):
    i = (y * w + x) * 4
    return tuple(rgba[i:i + 3])


tl = corner(app.img_rgba, w0, 0, 0)
tr = corner(app.img_rgba, w0, w0 - 1, 0)
print("верхние углы оригинала:", tl, tr)

# отражение по горизонтали меняет углы местами
app._flip("h"); r.update()
assert corner(app.img_rgba, app.img_w, 0, 0) == tr, "flip H не сработал"
print("flip H через интерфейс — ОК")

app._flip("h"); r.update()          # обратно
assert corner(app.img_rgba, app.img_w, 0, 0) == tl, "повторный flip H не вернул как было"
print("повторный flip H вернул исходное — ОК")

# поворот меняет местами стороны
app.rot.set("90°"); app._apply_transform(); r.update()
print("после 90°:", app.img_w, "×", app.img_h)
assert (app.img_w, app.img_h) == (h0, w0), "стороны не поменялись"

app.rot.set("180°"); app._apply_transform(); r.update()
assert (app.img_w, app.img_h) == (w0, h0), "на 180° стороны должны вернуться"
print("90° и 180° меняют размер правильно — ОК")

# сброс
app._flip("v")
app._reset_transform(); r.update()
assert app.rot.get() == "0°" and not app._flip_h and not app._flip_v
assert (app.img_w, app.img_h) == (w0, h0)
assert app.img_rgba == app._img_orig[0], "сброс не вернул оригинал"
print("Reset вернул оригинал — ОК")

# сохранение повёрнутой картинки
app.rot.set("90°"); app._apply_transform(); r.update()
app.ifolder.set(work); app.iname.set("rotated")
app.note.insert("1.0", "проверка")
app.save_image(); r.update()
p = os.path.join(work, "rotated.png")
assert os.path.exists(p), "файл не сохранился"
got = m.decode_png(open(p, "rb").read())
print("сохранено:", got[1], "×", got[2], f"({os.path.getsize(p)//1024} КБ)")
assert (got[1], got[2]) == (h0, w0), "на диск лёг неповёрнутый файл!"
assert got[0] == app.img_rgba, "пиксели на диске не совпали с превью"
assert os.path.exists(os.path.join(work, "rotated.txt")), "заметка не сохранилась"
print("на диск лёг именно повёрнутый вариант — ОК")

r.destroy()
for f in os.listdir(work):
    os.remove(os.path.join(work, f))
os.rmdir(work)
print("ALL OK")
