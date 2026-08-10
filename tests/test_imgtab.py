# -*- coding: utf-8 -*-
"""The whole Image tab: paste -> rotate/flip -> save."""
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
APP = _os.path.join(_ROOT, "ytdlp_gui.pyw")
EXE = _os.path.join(_ROOT, "dist", "YT-DLP GUI.exe")

import importlib.util, os, subprocess, tempfile, tkinter as tk
spec = importlib.util.spec_from_file_location("gui", APP)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# put our own picture on the clipboard; the test must not depend on
# whatever an earlier run left behind
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

# buttons stay disabled until there is an image
states = [str(b.cget("state")) for b in app.tr_btns] + [str(app.reset_btn.cget("state"))]
print("button state before pasting:", set(states))
assert set(states) == {"disabled"}

app.paste_image()
r.update()
assert app.img_rgba, "the clipboard image was not read"
w0, h0 = app.img_w, app.img_h
print(f"pasted: {w0}x{h0}")
states = [str(b.cget("state")) for b in app.tr_btns]
print("buttons after pasting:", set(states))
assert "disabled" not in states


def corner(rgba, w, x, y):
    i = (y * w + x) * 4
    return tuple(rgba[i:i + 3])


tl = corner(app.img_rgba, w0, 0, 0)
tr = corner(app.img_rgba, w0, w0 - 1, 0)
print("top corners of the original:", tl, tr)

# a horizontal flip swaps the corners
app._flip("h"); r.update()
assert corner(app.img_rgba, app.img_w, 0, 0) == tr, "flip H did nothing"
print("flip H through the UI: OK")

app._flip("h"); r.update()          # and back
assert corner(app.img_rgba, app.img_w, 0, 0) == tl, "a second flip H did not restore the original"
print("a second flip H restored the original: OK")

# rotation swaps the sides
app.rot.set("90°"); app._apply_transform(); r.update()
print("after 90°:", app.img_w, "×", app.img_h)
assert (app.img_w, app.img_h) == (h0, w0), "the sides did not swap"

app.rot.set("180°"); app._apply_transform(); r.update()
assert (app.img_w, app.img_h) == (w0, h0), "at 180° the sides must come back"
print("90° and 180° resize correctly: OK")

# reset
app._flip("v")
app._reset_transform(); r.update()
assert app.rot.get() == "0°" and not app._flip_h and not app._flip_v
assert (app.img_w, app.img_h) == (w0, h0)
assert app.img_rgba == app._img_orig[0], "reset did not restore the original"
print("Reset restored the original: OK")

# save the rotated picture
app.rot.set("90°"); app._apply_transform(); r.update()
app.ifolder.set(work); app.iname.set("rotated")
app.note.insert("1.0", "check")
app.save_image(); r.update()
p = os.path.join(work, "rotated.png")
assert os.path.exists(p), "the file was not saved"
got = m.decode_png(open(p, "rb").read())
print("saved:", got[1], "×", got[2], f"({os.path.getsize(p)//1024} KB)")
assert (got[1], got[2]) == (h0, w0), "an unrotated file landed on disk!"
assert got[0] == app.img_rgba, "pixels on disk differ from the preview"
assert os.path.exists(os.path.join(work, "rotated.txt")), "the note was not saved"
print("the rotated version is what reached the disk: OK")

r.destroy()
for f in os.listdir(work):
    os.remove(os.path.join(work, f))
os.rmdir(work)
print("ALL OK")
