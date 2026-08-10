# -*- coding: utf-8 -*-
"""Правильность отражений и поворотов — по конкретным пикселям."""
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
APP = _os.path.join(_ROOT, "ytdlp_gui.pyw")
EXE = _os.path.join(_ROOT, "dist", "YT-DLP GUI.exe")

import importlib.util, time
spec = importlib.util.spec_from_file_location("gui", APP)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

W, H = 4, 3


def mk():
    """Картинка, где в красный канал зашит x, в зелёный y — легко проверять."""
    b = bytearray()
    for y in range(H):
        for x in range(W):
            b += bytes((x * 10, y * 10, 0, 255))
    return bytes(b)


def px(rgba, w, x, y):
    i = (y * w + x) * 4
    return rgba[i], rgba[i + 1]


src = mk()
print("исходник 4x3, пиксель (x,y) = (x*10, y*10)")

# --- отражение по горизонтали
out = m.flip_h(src, W, H)
assert px(out, W, 0, 0) == (30, 0), px(out, W, 0, 0)
assert px(out, W, 3, 2) == (0, 20), px(out, W, 3, 2)
print("flip_h: левый верх стал правым верхом — ОК")

# --- по вертикали
out = m.flip_v(src, W, H)
assert px(out, W, 0, 0) == (0, 20)
assert px(out, W, 3, 0) == (30, 20)
print("flip_v: верх и низ поменялись — ОК")

# --- поворот по часовой: (x,y) -> (h-1-y, x), размер меняется
out, nw, nh = m.rot90(src, W, H, cw=True)
assert (nw, nh) == (3, 4), (nw, nh)
for y in range(H):
    for x in range(W):
        assert px(out, nw, H - 1 - y, x) == (x * 10, y * 10), (x, y)
print("rot90 по часовой: размер 3x4, все пиксели на местах — ОК")

# --- против часовой: (x,y) -> (y, w-1-x)
out, nw, nh = m.rot90(src, W, H, cw=False)
assert (nw, nh) == (3, 4)
for y in range(H):
    for x in range(W):
        assert px(out, nw, y, W - 1 - x) == (x * 10, y * 10), (x, y)
print("rot90 против часовой — ОК")

# --- четыре поворота возвращают оригинал
cur, w, h = src, W, H
for _ in range(4):
    cur, w, h = m.rot90(cur, w, h, cw=True)
assert (w, h) == (W, H) and cur == src
print("четыре поворота = исходник — ОК")

# --- 180° = оба отражения
a, aw, ah = m.transform_rgba(src, W, H, rot=180)
b = m.flip_v(m.flip_h(src, W, H), W, H)
assert (aw, ah) == (W, H) and a == b
print("поворот 180° совпал с двойным отражением — ОК")

# --- кодирование и обратное чтение PNG
png = m.encode_png(W, H, src)
back = m.decode_png(png)
assert back and back[1:] == (W, H) and back[0] == src
print("PNG: закодировали и прочитали обратно без потерь — ОК")

# --- уменьшение для превью
big = bytes(bytearray(800 * 600 * 4))
t = time.time()
small, sw, sh = m.shrink_rgba(big, 800, 600, 200, 150)
print(f"уменьшение 800x600 -> {sw}x{sh} за {(time.time()-t)*1000:.0f} мс")
assert (sw, sh) == (200, 150)

# --- скорость на настоящем размере скрина
big = bytes(bytearray(1920 * 1080 * 4))
for name, fn in (("flip_h", lambda: m.flip_h(big, 1920, 1080)),
                 ("flip_v", lambda: m.flip_v(big, 1920, 1080)),
                 ("rot90", lambda: m.rot90(big, 1920, 1080))):
    t = time.time(); fn()
    dt = (time.time() - t) * 1000
    print(f"{name} на 1920x1080: {dt:.0f} мс")
    assert dt < 900, f"{name} слишком медленный"
print("ALL OK")
