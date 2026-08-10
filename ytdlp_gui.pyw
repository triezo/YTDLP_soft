# -*- coding: utf-8 -*-
"""Простой графический интерфейс для yt-dlp + конвертер/сжатие через ffmpeg.

Запуск: ярлык на рабочем столе, "YT-DLP GUI.bat" или этот .pyw
питоном 3.12, где установлены tkinter и yt-dlp.
"""

import os
import re
import sys

# Собранный exe умеет работать И как yt-dlp: он запускает сам себя с этим
# флагом вместо внешней программы. Проверка должна быть до всего остального.
YTDLP_FLAG = "--__run_ytdlp__"
if len(sys.argv) > 1 and sys.argv[1] == YTDLP_FLAG:
    del sys.argv[1]
    # Без этого встроенный yt-dlp пишет в кодировке системы (cp1251), а окно
    # читает UTF-8 — кириллица в названиях и путях превращается в кашу.
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    from yt_dlp import main as _ytdlp_main
    sys.exit(_ytdlp_main())

import glob
import time
import zlib
import struct
import ctypes
import ctypes.wintypes as wt
import shutil
import subprocess
import threading
import winreg
from collections import deque
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Перетаскивание из проводника и браузера. Без библиотеки программа
# работает как раньше, просто без drag-and-drop.
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES, DND_TEXT
except ImportError:
    TkinterDnD = DND_FILES = DND_TEXT = None

REG_KEY = r"Software\ytdlp-gui"


def load_reg(name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
            val, _ = winreg.QueryValueEx(k, name)
            return val
    except OSError:
        return None


def save_reg(name, value):
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
    except OSError:
        pass


def load_last_folder(name="last_folder"):
    val = load_reg(name)
    return val if val and os.path.isdir(val) else None


def save_last_folder(path, name="last_folder"):
    save_reg(name, path)


def read_clipboard_win():
    """Чтение буфера обмена напрямую через WinAPI (CF_UNICODETEXT)."""
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    u32.OpenClipboard.argtypes = [wt.HWND]
    u32.GetClipboardData.restype = wt.HANDLE
    u32.GetClipboardData.argtypes = [wt.UINT]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [wt.HANDLE]
    k32.GlobalUnlock.argtypes = [wt.HANDLE]
    if not u32.OpenClipboard(None):
        return ""
    try:
        h = u32.GetClipboardData(13)  # CF_UNICODETEXT
        if not h:
            return ""
        p = k32.GlobalLock(h)
        try:
            return ctypes.wstring_at(p) if p else ""
        finally:
            k32.GlobalUnlock(h)
    finally:
        u32.CloseClipboard()


def _png_chunk(tag, data):
    c = tag + data
    return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))


def encode_png(w, h, rgba):
    """RGBA-байты (w*h*4) -> PNG."""
    stride = w * 4
    raw = bytearray()
    for y in range(h):
        raw += b"\x00" + rgba[y * stride:(y + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + _png_chunk(b"IEND", b""))


def decode_png(data):
    """PNG -> (rgba, w, h) или None. 8 бит на канал, без чересстрочности.
    Нужен, когда буфер отдал только PNG (браузеры) — из DIB пиксели берутся
    напрямую и куда быстрее."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos, idat, pal, trns = 8, bytearray(), None, None
    w = h = depth = ctype = interlace = 0
    while pos + 8 <= len(data):
        ln = int.from_bytes(data[pos:pos + 4], "big")
        tag, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if tag == b"IHDR":
            w, h, depth, ctype, _cm, _fl, interlace = struct.unpack(">IIBBBBB", body)
        elif tag == b"PLTE":
            pal = body
        elif tag == b"tRNS":
            trns = body
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if depth != 8 or interlace or not ch or not w or not h:
        return None
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error:
        return None

    stride = w * ch
    lines, prev, p = [], bytearray(stride), 0
    for _y in range(h):
        if p + 1 + stride > len(raw):
            return None
        f = raw[p]
        line = bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        if f == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 255
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif f == 3:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                c = prev[i - ch] if i >= ch else 0
                b = prev[i]
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        lines.append(line)
        prev = line

    out = bytearray(w * h * 4)
    for y, line in enumerate(lines):                 # приводим к RGBA
        o, n = y * w * 4, w * 4
        if ctype == 6:
            out[o:o + n] = line
        elif ctype == 2:
            out[o + 0:o + n:4] = line[0::3]
            out[o + 1:o + n:4] = line[1::3]
            out[o + 2:o + n:4] = line[2::3]
            out[o + 3:o + n:4] = b"\xff" * w
        elif ctype == 0:
            for c in range(3):
                out[o + c:o + n:4] = line
            out[o + 3:o + n:4] = b"\xff" * w
        elif ctype == 4:
            for c in range(3):
                out[o + c:o + n:4] = line[0::2]
            out[o + 3:o + n:4] = line[1::2]
        else:                                        # палитра
            if not pal:
                return None
            for x in range(w):
                i = line[x] * 3
                out[o + x * 4:o + x * 4 + 3] = pal[i:i + 3]
                out[o + x * 4 + 3] = (trns[line[x]] if trns and line[x] < len(trns)
                                      else 255)
    return bytes(out), w, h


# ---- преобразования картинки: только срезами, поэтому быстро -------------

def _row_mirror(row):
    """Развернуть порядок пикселей в строке RGBA."""
    out = bytearray(len(row))
    for c in range(4):
        out[c::4] = row[c::4][::-1]
    return out


def flip_h(rgba, w, h):
    stride, out = w * 4, bytearray(w * h * 4)
    for y in range(h):
        out[y * stride:(y + 1) * stride] = _row_mirror(rgba[y * stride:(y + 1) * stride])
    return bytes(out)


def flip_v(rgba, w, h):
    stride, out = w * 4, bytearray(w * h * 4)
    for y in range(h):
        out[y * stride:(y + 1) * stride] = rgba[(h - 1 - y) * stride:(h - y) * stride]
    return bytes(out)


def rot90(rgba, w, h, cw=True):
    """Поворот на 90°: строка исходника становится столбцом результата,
    поэтому пишем шагом через всю ширину — это одна операция на канал."""
    stride, nw, nh = w * 4, h, w
    nstride = nw * 4
    out = bytearray(nw * nh * 4)
    for y in range(h):
        row = rgba[y * stride:(y + 1) * stride]
        if cw:
            start = (h - 1 - y) * 4
        else:
            start, row = y * 4, _row_mirror(row)
        for c in range(4):
            out[start + c::nstride] = row[c::4]
    return bytes(out), nw, nh


def transform_rgba(rgba, w, h, rot=0, fh=False, fv=False):
    """Отражения, затем поворот. Считаем всегда от оригинала, чтобы
    многократные щелчки не накапливали ошибку."""
    if fh:
        rgba = flip_h(rgba, w, h)
    if fv:
        rgba = flip_v(rgba, w, h)
    for _ in range((rot // 90) % 4):
        rgba, w, h = rot90(rgba, w, h, cw=True)
    return rgba, w, h


def shrink_rgba(rgba, w, h, maxw, maxh):
    """Уменьшение «через пиксель» для превью: тоже срезами."""
    k = max(1, -(-w // max(maxw, 1)), -(-h // max(maxh, 1)))
    if k == 1:
        return rgba, w, h
    nw, nh = max(w // k, 1), max(h // k, 1)
    stride, nstride = w * 4, nw * 4
    out = bytearray(nh * nstride)
    for y in range(nh):
        row = rgba[y * k * stride:y * k * stride + stride]
        nr = bytearray(nstride)
        for c in range(4):
            nr[c::4] = row[c::4][::k][:nw]
        out[y * nstride:(y + 1) * nstride] = nr
    return bytes(out), nw, nh


def dib_to_rgba(d):
    """CF_DIB из буфера обмена -> (rgba, w, h) или None."""
    size, w, h, _planes, bpp, comp = struct.unpack_from("<IiiHHI", d, 0)
    clr_used = struct.unpack_from("<I", d, 32)[0]
    if w <= 0 or bpp not in (24, 32) or comp not in (0, 3):
        return None
    off = size + clr_used * 4
    if comp == 3 and size == 40:
        off += 12  # маски BITFIELDS идут после классического заголовка
    top_down = h < 0
    h = abs(h)
    stride = ((w * bpp + 31) // 32) * 4
    out = bytearray(w * h * 4)
    for y in range(h):
        src = off + (y if top_down else h - 1 - y) * stride
        o = y * w * 4
        row = d[src:src + stride]
        if bpp == 32:
            out[o:o + w * 4] = row[:w * 4]
            out[o:o + w * 4:4] = row[2:w * 4:4]      # BGRA -> RGBA
            out[o + 2:o + w * 4:4] = row[0:w * 4:4]
        else:
            out[o + 0:o + w * 4:4] = row[2:w * 3:3]
            out[o + 1:o + w * 4:4] = row[1:w * 3:3]
            out[o + 2:o + w * 4:4] = row[0:w * 3:3]
            out[o + 3:o + w * 4:4] = b"\xff" * w
    if bpp == 32 and max(out[3::4]) == 0:
        out[3::4] = b"\xff" * (w * h)  # скрины часто идут с нулевым альфа-каналом
    return bytes(out), w, h


def clipboard_image():
    """Изображение из буфера обмена -> (rgba, w, h) или None.

    DIB пробуем первым: там пиксели лежат готовыми, а PNG пришлось бы
    распаковывать построчно на Python — заметно медленнее."""
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    u32.OpenClipboard.argtypes = [wt.HWND]
    u32.GetClipboardData.restype = wt.HANDLE
    u32.GetClipboardData.argtypes = [wt.UINT]
    u32.IsClipboardFormatAvailable.argtypes = [wt.UINT]
    u32.RegisterClipboardFormatW.argtypes = [wt.LPCWSTR]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [wt.HANDLE]
    k32.GlobalUnlock.argtypes = [wt.HANDLE]
    k32.GlobalSize.restype = ctypes.c_size_t
    k32.GlobalSize.argtypes = [wt.HANDLE]

    def grab(fmt):
        hnd = u32.GetClipboardData(fmt)
        if not hnd:
            return None
        p = k32.GlobalLock(hnd)
        try:
            return ctypes.string_at(p, k32.GlobalSize(hnd)) if p else None
        finally:
            k32.GlobalUnlock(hnd)

    if not u32.OpenClipboard(None):
        return None
    try:
        if u32.IsClipboardFormatAvailable(8):          # CF_DIB
            data = grab(8)
            if data:
                got = dib_to_rgba(data)
                if got:
                    return got
        fmt_png = u32.RegisterClipboardFormatW("PNG")
        if fmt_png and u32.IsClipboardFormatAvailable(fmt_png):
            data = grab(fmt_png)
            if data:
                return decode_png(data)
    finally:
        u32.CloseClipboard()
    return None

# ---------------------------------------------------------------- пути

FROZEN = getattr(sys, "frozen", False)
APP_DIR = (os.path.dirname(sys.executable) if FROZEN
           else os.path.dirname(os.path.abspath(__file__)))


def res_path(name):
    """Файл, вшитый в сборку (в обычном запуске — рядом со скриптом)."""
    return os.path.join(getattr(sys, "_MEIPASS", APP_DIR), name)


def find_ytdlp():
    """Внешний yt-dlp.exe, если есть. Рядом с программой — приоритетнее:
    так свежую версию можно подложить, не пересобирая exe."""
    local = os.path.join(APP_DIR, "yt-dlp.exe")
    if os.path.exists(local):
        return local
    exe = shutil.which("yt-dlp")
    if exe:
        return exe
    hits = glob.glob(os.path.expandvars(
        r"%LOCALAPPDATA%\Programs\Python\Python3*\Scripts\yt-dlp.exe"))
    if hits:
        return hits[-1]
    return None if FROZEN else "yt-dlp"   # в сборке есть встроенный


YTDLP = find_ytdlp()


def ytdlp_cmd():
    """Чем запускать yt-dlp: внешним exe или собой же в режиме yt-dlp."""
    return [YTDLP] if YTDLP else [sys.executable, YTDLP_FLAG]


def find_ffmpeg():
    """Рядом с программой, затем в PATH, затем в типовых местах установки."""
    for cand in (os.path.join(APP_DIR, "ffmpeg.exe"),
                 os.path.join(APP_DIR, "ffmpeg", "ffmpeg.exe"),
                 os.path.join(APP_DIR, "ffmpeg", "bin", "ffmpeg.exe")):
        if os.path.exists(cand):
            return cand
    ff = shutil.which("ffmpeg")
    if ff:
        return ff
    for pat in (r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\*FFmpeg*\*\bin\ffmpeg.exe",
                r"%ProgramFiles%\ffmpeg\bin\ffmpeg.exe",
                r"C:\ffmpeg\bin\ffmpeg.exe"):
        hits = glob.glob(os.path.expandvars(pat))
        if hits:
            return hits[0]
    return None


APP_ID = "triezo.ytdlpgui"          # своя иконка и группа в панели задач


def setup_windows_look():
    """До создания окна: чёткость на масштабированных экранах и своя
    иконка в панели задач вместо общей питоновской."""
    try:                                   # Windows 8.1+: system DPI aware
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass


FFMPEG = find_ffmpeg()
FFPROBE = (os.path.join(os.path.dirname(FFMPEG), "ffprobe.exe")
           if FFMPEG else None)
DOWNLOADS = os.path.join(os.path.expanduser("~"), "Downloads")

RESOLUTIONS = ['Best', "2160p (4K)", "1440p", "1080p", "720p", "480p", "360p"]
# YouTube всё чаще требует «подтвердить, что вы не бот» — лечится cookies
# залогиненного браузера. Слева подпись, справа имя для --cookies-from-browser.
BROWSERS = [('No cookies', ""), ("Firefox", "firefox"), ("Chrome", "chrome"),
            ("Edge", "edge"), ("Opera", "opera"), ("Brave", "brave")]
FPS_LIST = ['Same as source', "60", "50", "30", "25", "24", "15"]
COMPRESSIONS = ['No re-encode', 'Light', 'Medium', 'Strong']
# mp4: CRF x264 (больше = меньше файл); mp3: битрейт
CRF = {'Light': "20", 'Medium': "26", 'Strong': "32"}
# монтажный DNxHR: каждый кадр самостоятельный, Premiere листает без лагов
DNX = {'No re-encode': "dnxhr_hq", 'Light': "dnxhr_hq",
       'Medium': "dnxhr_sq", 'Strong': "dnxhr_lb"}
MP3_BR = {'No re-encode': "320k", 'Light': "256k",
          'Medium': "192k", 'Strong': "128k"}

MEDIA_TYPES = [('Video and audio',
                "*.mp4 *.mkv *.webm *.avi *.mov *.wmv *.flv *.ts "
                "*.m4a *.mp3 *.wav *.flac *.opus *.ogg *.aac"),
               ('All files', "*.*")]

# ---------------------------------------------------------------- палитра
# Три уровня глубины: фон окна темнее карточек, карточки темнее полей ввода.
# За счёт этого блоки читаются как отдельные, без рамок-«коробок».

BG = "#141519"          # фон окна
CARD = "#1c1e24"        # карточка-группа
FIELD = "#252831"       # поле ввода, кнопка
FIELD_HI = "#2e323d"    # оно же под курсором
LINE = "#2b2f38"        # разделители и границы

FG = "#e9ebef"          # основной текст
FG_DIM = "#9aa1ad"      # подписи
MUTE = "#6d7480"        # третьестепенное

ACCENT = "#e5484d"      # фирменный красный (как иконка)
ACCENT_HI = "#f05a5f"
GREEN = "#4cc38a"       # успех и график скорости
GREEN_DIM = "#17342a"   # заливка под графиком
WARN = "#e2b53e"

F = "Segoe UI"          # шрифты
F_SEMI = "Segoe UI Semibold"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.proc = None
        self.cancelled = False
        self.busy = False            # занятость, известная главному потоку
        self._reset_progress()
        self._last_download = None   # путь последнего скачанного файла
        self._dl_candidate = None    # кандидат, вычисляемый из вывода yt-dlp

        root.title('YT-DLP GUI — video downloader & converter')
        ico = res_path("app.ico")
        if os.path.exists(ico):
            try:
                root.iconbitmap(ico)
            except tk.TclError:
                pass
        root.configure(bg=BG)
        # на экране с масштабом 125/150% Tk увеличивает шрифты сам (они в
        # пунктах), а размеры в пикселях надо домножить, иначе окно тесное
        self.k = max(root.winfo_fpixels("1i") / 96.0, 1.0)
        w = int(640 * self.k)
        # высоты хватает на вкладки и нижнюю панель, но окно не должно
        # вылезать за экран — на ноутбуках с масштабом места мало
        h = min(int(790 * self.k), root.winfo_screenheight() - int(70 * self.k))
        root.geometry(f"{w}x{h}")
        root.minsize(int(560 * self.k), int(520 * self.k))

        self._styles()
        self._build()
        self._setup_dnd()
        self._center()
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        if not FFMPEG:
            # без ffmpeg не склеиваются 1080p+ и не работает конвертация —
            # получателю сборки надо сказать об этом сразу, а не по факту
            self.set_status('ffmpeg not found: basic video only, no conversion. Put ffmpeg.exe next to the program', WARN)

    def _center(self):
        """Открываться по центру экрана, а не в углу по усмотрению Windows."""
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = max((self.root.winfo_screenheight() - h) // 2 - 30, 0)
        self.root.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------ ui

    @staticmethod
    def _drop_element(layout, name):
        """Убрать элемент из разметки ttk-стиля, сохранив вложенных детей."""
        out = []
        for el, opts in layout:
            opts = dict(opts)
            kids = opts.get("children")
            if kids:
                opts["children"] = App._drop_element(kids, name)
            if el == name:
                out.extend(opts.get("children", []))   # детей поднимаем наверх
            else:
                out.append((el, opts))
        return out

    def _styles(self):
        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=FG, fieldbackground=FIELD,
                    bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
        # Тема clam рисует вокруг подписи пунктирную рамку фокуса — по клику
        # она выглядит как «выделенный текст». Выкидываем этот элемент из
        # разметки вкладок и кнопок: фокус остаётся, пунктир пропадает.
        for style, elem in (("TNotebook.Tab", "Notebook.focus"),
                            ("TButton", "Button.focus")):
            try:
                s.layout(style, self._drop_element(s.layout(style), elem))
            except tk.TclError:
                pass
        s.configure("TFrame", background=BG)
        s.configure("Card.TFrame", background=CARD)
        s.configure("TLabel", background=BG, foreground=FG, font=(F, 10))
        # подписи внутри карточек — фон карточки, иначе видны прямоугольники
        s.configure("Card.TLabel", background=CARD, foreground=FG, font=(F, 10))
        s.configure("Section.TLabel", background=CARD, foreground=FG_DIM,
                    font=(F_SEMI, 9))
        s.configure("Hint.TLabel", background=CARD, foreground=MUTE, font=(F, 9))
        s.configure("Muted.TLabel", background=BG, foreground=MUTE, font=(F, 9))
        s.configure("Title.TLabel", background=BG, foreground=FG, font=(F_SEMI, 15))
        s.configure("Ver.TLabel", background=BG, foreground=MUTE, font=(F, 9))

        # кнопки: обычная, тихая (в карточке) и главная
        s.configure("TButton", font=(F, 10), padding=(12, 7),
                    background=FIELD, foreground=FG, borderwidth=0, relief="flat")
        s.map("TButton", background=[("pressed", LINE), ("active", FIELD_HI)],
              foreground=[("disabled", MUTE)])
        s.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                    font=(F_SEMI, 11), padding=(14, 10))
        s.map("Accent.TButton",
              background=[("pressed", "#c93c41"), ("active", ACCENT_HI),
                          ("disabled", "#4a2b2d")],
              foreground=[("disabled", "#8d7376")])

        s.configure("Card.TRadiobutton", background=CARD, foreground=FG_DIM,
                    font=(F, 10), indicatorcolor=FIELD, indicatordiameter=11,
                    padding=(0, 3))
        s.map("Card.TRadiobutton",
              background=[("active", CARD)], foreground=[("selected", FG)],
              indicatorcolor=[("selected", ACCENT), ("active", FIELD_HI)])
        s.configure("Card.TCheckbutton", background=CARD, foreground=FG_DIM,
                    font=(F, 10), indicatorcolor=FIELD, padding=(0, 3))
        s.map("Card.TCheckbutton",
              background=[("active", CARD)], foreground=[("selected", FG)],
              indicatorcolor=[("selected", ACCENT), ("active", FIELD_HI)])

        s.configure("TSpinbox", padding=(8, 5), arrowcolor=FG_DIM, arrowsize=12,
                    borderwidth=0, relief="flat", fieldbackground=FIELD,
                    background=FIELD, foreground=FG)
        s.map("TSpinbox",
              fieldbackground=[("readonly", FIELD), ("disabled", CARD)],
              foreground=[("readonly", FG), ("disabled", MUTE)],
              background=[("active", FIELD_HI)],
              arrowcolor=[("disabled", LINE), ("active", FG)])
        s.configure("TCombobox", padding=(8, 6), arrowcolor=FG_DIM,
                    borderwidth=0, relief="flat")
        s.map("TCombobox",
              fieldbackground=[("readonly", FIELD), ("disabled", CARD)],
              foreground=[("readonly", FG), ("disabled", MUTE)],
              selectbackground=[("readonly", FIELD)],
              selectforeground=[("readonly", FG)],
              arrowcolor=[("disabled", LINE), ("active", FG)])
        # выпадающий список комбобокса — обычный tk-Listbox, стилю ttk не
        # подчиняется, красим через базу опций
        self.root.option_add("*TCombobox*Listbox.background", FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "white")
        self.root.option_add("*TCombobox*Listbox.borderWidth", 0)
        self.root.option_add("*TCombobox*Listbox.font", "{Segoe UI} 10")
        s.configure("TNotebook", background=BG, borderwidth=0,
                    tabmargins=(0, 6, 0, 0))
        # выделенная вкладка: светлее фона, ярче текст и акцентная полоса
        # сверху — иначе на тёмной теме её почти не отличить от соседей
        s.configure("TNotebook.Tab", background="#191b21", foreground=MUTE,
                    font=(F_SEMI, 10), padding=(18, 9), borderwidth=2,
                    bordercolor=BG, lightcolor=BG, darkcolor=BG)
        s.map("TNotebook.Tab",
              background=[("selected", CARD), ("active", "#20232a")],
              foreground=[("selected", "#ffffff"), ("active", FG_DIM)],
              lightcolor=[("selected", ACCENT)],
              bordercolor=[("selected", ACCENT)],
              # clam добавляет выделенной вкладке свой padding, из-за чего
              # ярлычки скачут вбок при переключении — держим его одинаковым
              padding=[("selected", (18, 9)), ("!selected", (18, 9))])
        for name, color in [("Idle", LINE), ("Run", GREEN), ("Err", ACCENT)]:
            s.configure(f"{name}.Horizontal.TProgressbar", background=color,
                        troughcolor="#1a1c22", borderwidth=0, thickness=6)

    # --- кирпичики оформления -----------------------------------------

    P = 18                      # внутренний отступ карточки

    def _sec(self, parent, text, top=13):
        """Заголовок группы: приглушённый, мельче основного текста."""
        ttk.Label(parent, text=text, style="Section.TLabel").pack(
            anchor="w", padx=self.P, pady=(top, 6))

    def _row(self, parent, top=0):
        r = ttk.Frame(parent, style="Card.TFrame")
        r.pack(fill="x", padx=self.P, pady=(top, 0))
        return r

    def _entry(self, parent, var, big=False, hint=""):
        """Поле ввода в рамке, которая на фокусе загорается акцентом.
        hint — серая подсказка внутри поля вместо отдельной строчки снизу."""
        wrap = tk.Frame(parent, bg=LINE)
        e = tk.Entry(wrap, textvariable=var, font=(F, 11 if big else 10),
                     bg=FIELD, fg=FG, insertbackground=ACCENT,
                     relief="flat", bd=0, highlightthickness=0)
        e.pack(fill="both", expand=True, padx=1, pady=1, ipady=7 if big else 6)
        e.bind("<FocusIn>", lambda _ev: wrap.configure(bg=ACCENT))
        e.bind("<FocusOut>", lambda _ev: wrap.configure(bg=LINE))
        self._entry_hotkeys(e)
        if hint:
            # подсказку кладём отдельной меткой поверх поля: значение
            # переменной остаётся чистым, читать её можно как обычно
            lbl = tk.Label(e, text=hint, bg=FIELD, fg=MUTE, font=(F, 9))

            def upd(*_a):
                if var.get() or e is e.focus_displayof():
                    lbl.place_forget()
                else:
                    lbl.place(x=7, rely=0.5, anchor="w")
            var.trace_add("write", upd)
            e.bind("<FocusIn>", lambda _ev: lbl.place_forget(), add="+")
            e.bind("<FocusOut>", lambda _ev: upd(), add="+")
            # клик по самой подсказке метка съедает — передаём фокус полю,
            # иначе по тексту подсказки поле «не нажимается»
            lbl.bind("<Button-1>", lambda _ev: e.focus_set())
            upd()
        return wrap, e

    def _build(self):
        f = ttk.Frame(self.root)
        f.pack(fill="both", expand=True)

        nb = ttk.Notebook(f)
        nb.pack(fill="x", padx=14, pady=(12, 0))
        self.nb = nb
        tab_dl = self._tab_dl = ttk.Frame(nb, style="Card.TFrame")
        tab_cv = self._tab_cv = ttk.Frame(nb, style="Card.TFrame")
        tab_im = self._tab_im = ttk.Frame(nb, style="Card.TFrame")
        nb.add(tab_dl, text='⬇   Download')
        nb.add(tab_cv, text='⚙   Convert')
        nb.add(tab_im, text='🖼   Image')

        self._build_download_tab(tab_dl)
        self._build_convert_tab(tab_cv)
        self._build_image_tab(tab_im)

        # Ctrl+V на вкладке «Картинка» (вне полей ввода) вставляет из буфера
        self.root.bind("<Control-KeyPress>", self._root_ctrl)

        # --- общие прогресс, статус и лог
        self.bar = ttk.Progressbar(f, maximum=100,
                                   style="Idle.Horizontal.TProgressbar")
        self.bar.pack(fill="x", padx=14, pady=(16, 8))
        row = ttk.Frame(f)
        row.pack(fill="x", padx=14)
        self.status = ttk.Label(row, text='Ready', style="Muted.TLabel")
        self.status.pack(side="left", fill="x", expand=True)
        self.cancel_btn = ttk.Button(row, text='Cancel', command=self.cancel,
                                     state="disabled")
        self.cancel_btn.pack(side="right")
        self.upd_btn = ttk.Button(row, text='⟳  Update yt-dlp',
                                  command=self.update_ytdlp)
        self.upd_btn.pack(side="right", padx=(0, 8))

        self.log = tk.Text(f, height=5, bg="#101216", fg=MUTE, relief="flat",
                           font=("Consolas", 9), state="disabled", wrap="word",
                           padx=12, pady=10, highlightthickness=0,
                           insertbackground=MUTE)
        self.log.pack(fill="both", expand=True, padx=14, pady=(12, 14))

    # ------------------------------------------------------ перетаскивание

    def _setup_dnd(self):
        """Цели вешаем на виджеты, а не на корень: методы перетаскивания
        появляются только у потомков BaseWidget."""
        self.dnd_ok = False
        if TkinterDnD is None:
            return
        try:
            TkinterDnD._require(self.root)
        except Exception:                     # tkdnd не подгрузился
            return
        for wdg in (self._tab_dl, self._tab_cv, self._tab_im, self.preview,
                    self.log):
            try:
                wdg.drop_target_register(DND_FILES, DND_TEXT)
                wdg.dnd_bind("<<Drop>>", self._on_drop)
            except (tk.TclError, AttributeError):
                continue
            self.dnd_ok = True

    def _on_drop(self, ev):
        """Принесённое мышью: файлы или текст. Что делать — зависит
        от того, какая вкладка сейчас открыта."""
        try:
            items = [str(p) for p in self.root.tk.splitlist(ev.data)]
        except tk.TclError:
            items = [ev.data]
        paths = [p for p in items if os.path.exists(p)]
        tab = self.nb.index(self.nb.select())
        if paths:
            self._drop_files(paths, tab)
        else:
            self._drop_text(" ".join(items).strip().strip("{}"), tab)
        return ev.action if hasattr(ev, "action") else None

    IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff")

    def _drop_files(self, paths, tab):
        path = paths[0]
        is_img = path.lower().endswith(self.IMG_EXT)
        if tab == 2 or (is_img and tab != 1):
            self.nb.select(2)
            self._load_image_file(path)
            return
        # файл на вкладке загрузки конвертировать логичнее, чем ничего
        self.src.set(path)
        self.cfolder.set(os.path.dirname(path))
        self.nb.select(1)
        extra = f"  (+{len(paths) - 1} more ignored)" if len(paths) > 1 else ""
        self.set_status('File ready to convert: ' + os.path.basename(path) + extra)

    def _drop_text(self, text, tab):
        text = text.strip()
        if text.lower().startswith(("http://", "https://")):
            self.url.set(text)
            self.nb.select(0)
            self.set_status('Link dropped — press Download')
        else:
            self.set_status('Dropped item is not a file or a link', WARN)

    def _load_image_file(self, path):
        """Картинка из файла. PNG читаем сами, остальные форматы —
        через ffmpeg, своего декодера JPEG у нас нет."""
        try:
            data = open(path, "rb").read()
        except OSError as e:
            self.set_status(f"Could not read the file: {e}", WARN)
            return
        got = decode_png(data) if data[:8] == b"\x89PNG\r\n\x1a\n" else None
        if not got and FFMPEG:
            try:
                r = subprocess.run(
                    [FFMPEG, "-v", "error", "-i", path, "-frames:v", "1",
                     "-f", "image2", "-c:v", "png", "-"],
                    capture_output=True, timeout=60,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                if r.returncode == 0 and r.stdout:
                    got = decode_png(r.stdout)
            except (OSError, subprocess.SubprocessError):
                got = None
        if not got:
            self.set_status(
                'Could not read this image' + ('' if FFMPEG else ' — ffmpeg needed'),
                WARN)
            return
        self._set_image(got, os.path.basename(path))

    # ------------------------------------------------------------ график

    def _toggle_graph(self):
        opened = not self.graph_open
        self.graph_open = opened
        self.sp_head.configure(text=("▾" if opened else "▸") + '   Speed graph',
                               fg=FG if opened else FG_DIM)
        if opened:
            self.graph.pack(fill="x", padx=self.P, pady=(8, 0))
            self._draw_graph()
        else:
            self.graph.pack_forget()
        save_reg("graph", "1" if opened else "0")

    def _draw_graph(self):
        c = self.graph
        c.delete("all")
        if not self.graph_open:
            return
        w, h = c.winfo_width(), c.winfo_height()
        if w < 20 or h < 20:
            return
        hist = self._speed_hist
        top, bot = 18, h - 6
        peak = max(hist) if hist else 0

        for i in range(1, 4):                     # сетка
            y = top + (bot - top) * i / 4
            c.create_line(10, y, w - 10, y, fill="#1e222a")

        if not hist:
            c.create_text(w / 2, h / 2, text='speed will appear during download',
                          fill="#454b56", font=(F, 9))
            return

        scale = peak * 1.15 or 1
        # растягиваем на всю ширину: пока точек мало, график всё равно
        # занимает панель целиком, а не жмётся к правому краю
        step = (w - 20) / max(len(hist) - 1, 1)
        x0 = 10
        pts = [(x0 + i * step, bot - (v / scale) * (bot - top))
               for i, v in enumerate(hist)]

        if len(pts) > 1:
            flat = [k for p in pts for k in p]
            c.create_polygon([pts[0][0], bot] + flat + [pts[-1][0], bot],
                             fill=GREEN_DIM, outline="")
            c.create_line(flat, fill=GREEN, width=2)
        c.create_oval(pts[-1][0] - 3, pts[-1][1] - 3,
                      pts[-1][0] + 3, pts[-1][1] + 3, fill=GREEN, outline="")
        c.create_text(12, 10, anchor="w", fill=MUTE, font=(F, 8),
                      text='peak ' + self._fmt_rate(peak))
        c.create_text(w - 12, 10, anchor="e", fill=GREEN, font=(F_SEMI, 9),
                      text=self._fmt_rate(hist[-1]))

    # ------------------------------------------------------------ вкладки

    def _build_download_tab(self, f):
        self._sec(f, 'Video link', top=14)
        row = self._row(f)
        self.url = tk.StringVar()
        wrap, e = self._entry(row, self.url, big=True,
                              hint='paste a video link')
        wrap.pack(side="left", fill="x", expand=True)
        e.bind("<Return>", lambda _e: self.start())
        ttk.Button(row, text='Paste', command=self.paste).pack(side="left", padx=(8, 0))

        self._sec(f, 'Format')
        row = self._row(f)
        self.fmt = tk.StringVar(value="mp4")
        for val, text in [("mp4", 'MP4 · video'), ("mp3", 'MP3 · audio'),
                          ("wav", 'WAV · audio')]:
            ttk.Radiobutton(row, text=text, value=val, variable=self.fmt,
                            style="Card.TRadiobutton",
                            command=self._fmt_changed).pack(side="left", padx=(0, 20))

        row = self._row(f, top=12)
        ttk.Label(row, text='Resolution', style="Card.TLabel").pack(side="left")
        self.res = tk.StringVar(value="1080p")
        self.res_box = ttk.Combobox(row, textvariable=self.res, values=RESOLUTIONS,
                                    state="readonly", width=13)
        self.res_box.pack(side="left", padx=(10, 0))
        self.playlist = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text='Whole playlist', variable=self.playlist,
                        style="Card.TCheckbutton").pack(side="left", padx=(22, 0))

        row = self._row(f, top=12)
        ttk.Label(row, text="Cookies", style="Card.TLabel").pack(side="left")
        # в реестре могло остаться значение от старой русской версии —
        # берём его, только если оно есть в текущем списке
        saved = load_reg("cookies")
        names = [b[0] for b in BROWSERS]
        self.cookies = tk.StringVar(value=saved if saved in names else names[0])
        ttk.Combobox(row, textvariable=self.cookies, state="readonly", width=13,
                     values=[b[0] for b in BROWSERS]).pack(side="left", padx=(10, 0))
        ttk.Label(row, text='for age-restricted videos and bot checks',
                  style="Hint.TLabel").pack(side="left", padx=(12, 0))

        self._sec(f, 'Save to')
        row = self._row(f)
        self.folder = tk.StringVar(value=load_last_folder() or DOWNLOADS)
        wrap, _ = self._entry(row, self.folder)
        wrap.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text='Browse…', command=self.browse).pack(side="left", padx=(8, 0))
        ttk.Button(row, text='Open',
                   command=lambda: self.open_folder(self.folder.get())).pack(side="left", padx=(6, 0))

        row = self._row(f, top=10)
        self.fname = tk.StringVar()
        wrap, _ = self._entry(row, self.fname, hint='file name — defaults to the video title')
        wrap.pack(fill="x")

        self.btn = ttk.Button(f, text='⬇   Download', style="Accent.TButton",
                              command=self.start)
        self.btn.pack(fill="x", padx=self.P, pady=(16, 0))

        # --- спойлер с графиком скорости: раскрывается вниз
        self.graph_open = False
        head = tk.Frame(f, bg=CARD)
        head.pack(fill="x", padx=self.P, pady=(14, 0))
        self.sp_head = tk.Label(head, text='▸   Speed graph', bg=CARD,
                                fg=FG_DIM, font=(F, 9), cursor="hand2")
        self.sp_head.pack(side="left")
        for w_ in (head, self.sp_head):
            w_.bind("<Button-1>", lambda _e: self._toggle_graph())
        self.sp_head.bind("<Enter>", lambda _e: self.sp_head.configure(fg=FG))
        self.sp_head.bind("<Leave>", lambda _e: self.sp_head.configure(
            fg=FG if self.graph_open else FG_DIM))

        self.graph = tk.Canvas(f, height=96, bg="#101216", relief="flat",
                               highlightthickness=0)
        self.graph.bind("<Configure>", lambda _e: self._draw_graph())
        tk.Frame(f, bg=CARD, height=14).pack(fill="x")   # нижний воздух
        if load_reg("graph") == "1":
            self._toggle_graph()

    def _build_convert_tab(self, f):
        self._sec(f, 'File on your computer', top=14)
        self._src_row = row = self._row(f)
        self.src = tk.StringVar()
        wrap, e = self._entry(row, self.src, hint='path to a file on your computer')
        wrap.pack(side="left", fill="x", expand=True)
        # add="+" обязателен: без него эта привязка затирает подсветку рамки
        # и скрытие подсказки, навешенные в _entry
        e.bind("<FocusIn>", lambda _e: self._refresh_suggestion(), add="+")
        ttk.Button(row, text='Browse…', command=self.browse_src).pack(side="left", padx=(8, 0))

        # кликабельная подсказка: подставить только что скачанный файл
        self.suggest = tk.Label(f, text="", bg=CARD, fg=ACCENT, cursor="hand2",
                                font=(F, 9), anchor="w", justify="left")
        self.suggest.bind("<Button-1>", lambda _e: self._use_last_download())

        self._sec(f, 'Convert to')
        row = self._row(f)
        self.cfmt = tk.StringVar(value="mp4")
        for val, text in [("mp4", "MP4"), ("mov", 'MOV · editing'),
                          ("mp3", "MP3"), ("wav", "WAV")]:
            ttk.Radiobutton(row, text=text, value=val, variable=self.cfmt,
                            style="Card.TRadiobutton",
                            command=self._cfmt_changed).pack(side="left", padx=(0, 18))

        row = self._row(f, top=12)
        ttk.Label(row, text='Compression', style="Card.TLabel").pack(side="left")
        self.comp = tk.StringVar(value='Medium')
        self.comp_box = ttk.Combobox(row, textvariable=self.comp, values=COMPRESSIONS,
                                     state="readonly", width=15)
        self.comp_box.pack(side="left", padx=(10, 0))
        ttk.Label(row, text='Resolution', style="Card.TLabel").pack(side="left", padx=(18, 0))
        self.cres = tk.StringVar(value='Best')
        self.cres_box = ttk.Combobox(row, textvariable=self.cres, values=RESOLUTIONS,
                                     state="readonly", width=11)
        self.cres_box.pack(side="left", padx=(10, 0))

        self._fps_row = row = self._row(f, top=12)
        ttk.Label(row, text='Frame rate', style="Card.TLabel").pack(side="left")
        self.cfps = tk.StringVar(value='Same as source')
        self.cfps_box = ttk.Combobox(row, textvariable=self.cfps, values=FPS_LIST,
                                     state="readonly", width=15)
        self.cfps_box.pack(side="left", padx=(10, 0))

        self.hint = ttk.Label(f, text="", style="Hint.TLabel", wraplength=540,
                              justify="left")   # пакуется только когда есть текст

        self._sec(f, 'Save to')
        row = self._row(f)
        self.cfolder = tk.StringVar()
        wrap, _ = self._entry(row, self.cfolder)
        wrap.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text='Browse…', command=self.browse_cfolder).pack(side="left", padx=(8, 0))
        ttk.Button(row, text='Open',
                   command=lambda: self.open_folder(self.cfolder.get())).pack(side="left", padx=(6, 0))

        row = self._row(f, top=10)
        self.cname = tk.StringVar()
        wrap, _ = self._entry(row, self.cname, hint='file name — defaults to the source name')
        wrap.pack(fill="x")

        self.cbtn = ttk.Button(f, text='⚙   Convert', style="Accent.TButton",
                               command=self.start_convert)
        self.cbtn.pack(fill="x", padx=self.P, pady=(16, 16))

    def _build_image_tab(self, f):
        self._sec(f, 'Image from clipboard', top=14)
        row = self._row(f)
        ttk.Button(row, text='📋   Paste  (Ctrl+V)',
                   command=self.paste_image).pack(side="left")
        self.img_info = ttk.Label(row, text="", style="Hint.TLabel")
        self.img_info.pack(side="left", padx=(12, 0))

        holder = tk.Frame(f, bg=LINE)
        holder.pack(fill="x", padx=self.P, pady=(10, 0))
        inner = tk.Frame(holder, bg="#101216", height=150)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        inner.pack_propagate(False)
        self.preview = tk.Label(
            inner, bg="#101216", fg=MUTE, font=(F, 10),
            text='Paste a screenshot here (Ctrl+V)\nor drag an image file in')
        self.preview.pack(fill="both", expand=True)
        self.preview.bind("<Button-1>", lambda _e: self.paste_image())
        self._preview_img = None
        self._img_orig = None       # (rgba, w, h) как вставили — база правок
        self.img_rgba = None        # текущая картинка после преобразований
        self.img_w = self.img_h = 0

        # --- отражения и поворот
        row = self._row(f, top=10)
        self.tr_btns = []
        for text, cmd in (('⇋  Flip H', lambda: self._flip("h")),
                          ('⇵  Flip V', lambda: self._flip("v"))):
            b = ttk.Button(row, text=text, command=cmd, state="disabled")
            b.pack(side="left", padx=(0, 8))
            self.tr_btns.append(b)

        ttk.Label(row, text='Rotate', style="Card.TLabel").pack(side="left", padx=(10, 0))
        self.rot = tk.StringVar(value="0°")
        self.rot_box = ttk.Spinbox(row, textvariable=self.rot, width=6,
                                   values=("0°", "90°", "180°", "270°"),
                                   state="disabled", wrap=True,
                                   command=self._apply_transform)
        self.rot_box.pack(side="left", padx=(8, 0))
        self.tr_btns.append(self.rot_box)

        self.reset_btn = ttk.Button(row, text='Reset', state="disabled",
                                    command=self._reset_transform)
        self.reset_btn.pack(side="right")

        self._sec(f, 'Note  ·  saved as .txt alongside', top=14)
        nwrap = tk.Frame(f, bg=LINE)
        nwrap.pack(fill="x", padx=self.P)
        self.note = tk.Text(nwrap, height=2, bg=FIELD, fg=FG, insertbackground=ACCENT,
                            relief="flat", font=(F, 10), wrap="word",
                            padx=8, pady=6, highlightthickness=0)
        self.note.pack(fill="both", expand=True, padx=1, pady=1)
        self.note.bind("<FocusIn>", lambda _e: nwrap.configure(bg=ACCENT))
        self.note.bind("<FocusOut>", lambda _e: nwrap.configure(bg=LINE))
        self._text_hotkeys(self.note)

        self._sec(f, 'Save to')
        row = self._row(f)
        self.ifolder = tk.StringVar(
            value=load_last_folder("last_img_folder")
            or os.path.join(os.path.expanduser("~"), "Pictures"))
        wrap, _ = self._entry(row, self.ifolder)
        wrap.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text='Browse…', command=self.browse_ifolder).pack(side="left", padx=(8, 0))
        ttk.Button(row, text='Open',
                   command=lambda: self.open_folder(self.ifolder.get())).pack(side="left", padx=(6, 0))

        row = self._row(f, top=10)
        self.iname = tk.StringVar()
        wrap, _ = self._entry(row, self.iname, hint='name — defaults to date and time')
        wrap.pack(fill="x")

        self.ibtn = ttk.Button(f, text='💾   Save', style="Accent.TButton",
                               command=self.save_image)
        self.ibtn.pack(fill="x", padx=self.P, pady=(16, 16))

    # ------------------------------------------------------------ helpers

    def _fmt_changed(self):
        self.res_box.configure(state="readonly" if self.fmt.get() == "mp4" else "disabled")

    def _cfmt_changed(self):
        fmt = self.cfmt.get()
        video = fmt in ("mp4", "mov")
        self.cres_box.configure(state="readonly" if video else "disabled")
        self.cfps_box.configure(state="readonly" if video else "disabled")
        self.comp_box.configure(state="readonly" if fmt != "wav" else "disabled")
        if fmt == "mov":
            self.hint.configure(
                text='DNxHR editing codec: Premiere scrubs without lag, but files get much heavier.')
            if self.hint.winfo_manager() != "pack":
                self.hint.pack(anchor="w", padx=self.P, pady=(8, 0),
                               after=self._fps_row)
        else:
            self.hint.pack_forget()

    def _entry_hotkeys(self, entry):
        """Ctrl+V/C/X/A по физическим клавишам — работает на любой раскладке,
        включая кириллическую (стандартные бинды tkinter на ней молчат).
        Плюс контекстное меню по правой кнопке."""
        def on_ctrl(ev):
            kc = ev.keycode  # физическая клавиша, не зависит от раскладки
            if kc == 86:                       # V
                self._insert_clip(entry)
            elif kc == 67:                     # C
                entry.event_generate("<<Copy>>")
            elif kc == 88:                     # X
                entry.event_generate("<<Cut>>")
            elif kc == 65:                     # A
                entry.select_range(0, "end")
                entry.icursor("end")
            else:
                return None
            return "break"
        entry.bind("<Control-KeyPress>", on_ctrl)

        menu = tk.Menu(entry, tearoff=0, bg=FIELD, fg=FG,
                       activebackground=ACCENT, activeforeground="white")
        menu.add_command(label='Paste', command=lambda: self._insert_clip(entry))
        menu.add_command(label='Copy', command=lambda: entry.event_generate("<<Copy>>"))
        menu.add_command(label='Cut', command=lambda: entry.event_generate("<<Cut>>"))
        menu.add_separator()
        menu.add_command(label='Select all',
                         command=lambda: (entry.select_range(0, "end"), entry.icursor("end")))
        entry.bind("<Button-3>", lambda ev: menu.tk_popup(ev.x_root, ev.y_root))

    def _get_clip(self):
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            text = ""
        if not text:
            try:
                text = read_clipboard_win()
            except OSError:
                text = ""
        return text.strip()

    def _insert_clip(self, entry):
        """Вставить из буфера в позицию курсора (заменяя выделение)."""
        text = self._get_clip()
        if not text:
            return
        if entry.selection_present():
            entry.delete("sel.first", "sel.last")
        entry.insert("insert", text)

    def _text_hotkeys(self, txt):
        """Ctrl+V/C/X/A для tk.Text на любой раскладке."""
        def on_ctrl(ev):
            kc = ev.keycode
            if kc == 86:
                text = self._get_clip()
                if text:
                    try:
                        txt.delete("sel.first", "sel.last")
                    except tk.TclError:
                        pass
                    txt.insert("insert", text)
            elif kc == 67:
                txt.event_generate("<<Copy>>")
            elif kc == 88:
                txt.event_generate("<<Cut>>")
            elif kc == 65:
                txt.tag_add("sel", "1.0", "end-1c")
            else:
                return None
            return "break"
        txt.bind("<Control-KeyPress>", on_ctrl)

    def _root_ctrl(self, ev):
        # Ctrl+V вне полей ввода на вкладке «Картинка» — вставить изображение
        if ev.keycode != 86:
            return
        if self.nb.index(self.nb.select()) != 2:
            return
        w = self.root.focus_get()
        if isinstance(w, (tk.Entry, tk.Text)):
            return
        self.paste_image()

    def paste(self):
        text = self._get_clip()
        if text:
            self.url.set(text)
        else:
            self.set_status('Clipboard is empty or holds no text', WARN)

    # ------------------------------------------------------------ картинка

    def paste_image(self):
        try:
            res = clipboard_image()
        except OSError:
            res = None
        if not res:
            self.set_status('No image in the clipboard', WARN)
            return
        self._set_image(res)

    def _set_image(self, res, source=""):
        """Общий путь для буфера обмена и перетаскивания."""
        self._img_orig = res
        self.rot.set("0°")
        self._flip_h = self._flip_v = False
        for wdg in self.tr_btns + [self.reset_btn]:
            wdg.configure(state="readonly" if wdg is self.rot_box else "normal")
        self._apply_transform()
        self.set_status(f"Loaded {source} — ready to save" if source
                        else 'Image pasted — ready to save')

    # --- отражения и поворот ------------------------------------------

    def _flip(self, axis):
        if not self._img_orig:
            return
        if axis == "h":
            self._flip_h = not self._flip_h
        else:
            self._flip_v = not self._flip_v
        self._apply_transform()

    def _reset_transform(self):
        self.rot.set("0°")
        self._flip_h = self._flip_v = False
        self._apply_transform()

    def _apply_transform(self):
        """Пересчёт всегда от оригинала: повторные щелчки не копят искажения."""
        if not self._img_orig:
            return
        rgba, w, h = self._img_orig
        try:
            rot = int(re.sub(r"\D", "", self.rot.get()) or 0)
        except ValueError:
            rot = 0
        self.img_rgba, self.img_w, self.img_h = transform_rgba(
            rgba, w, h, rot=rot, fh=self._flip_h, fv=self._flip_v)
        self._show_preview()

    def _show_preview(self):
        """Превью кодируем уже уменьшенным — полноразмерный PNG на каждый
        щелчок сжимался бы почти секунду."""
        rgba, w, h = self.img_rgba, self.img_w, self.img_h
        box = self.preview.winfo_width() or 560
        small, sw, sh = shrink_rgba(rgba, w, h, max(box - 8, 80), 142)
        try:
            img = tk.PhotoImage(data=encode_png(sw, sh, small))
            self._preview_img = img
            self.preview.configure(image=img, text="")
        except tk.TclError:
            self._preview_img = None
            self.preview.configure(image="", text=f"Image {w}×{h}\n(preview unavailable)")
        marks = []
        if self._flip_h:
            marks.append("flip H")
        if self._flip_v:
            marks.append("flip V")
        if self.rot.get() != "0°":
            marks.append(self.rot.get())
        self.img_info.configure(
            text=f"{w}×{h}" + ("  ·  " + ", ".join(marks) if marks else ""))

    def browse_ifolder(self):
        d = filedialog.askdirectory(initialdir=self.ifolder.get() or DOWNLOADS)
        if d:
            self.ifolder.set(d)

    def save_image(self):
        if not self.img_rgba:
            messagebox.showwarning('No image',
                                   'Paste an image from the clipboard first.')
            return
        folder = self.ifolder.get().strip() or os.path.join(os.path.expanduser("~"), "Pictures")
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            messagebox.showerror('Folder', f"Could not create the folder:\n{e}")
            return
        name = self._clean_name(self.iname.get().strip()) \
            or 'Screenshot ' + time.strftime("%Y-%m-%d %H-%M-%S")
        out = os.path.join(folder, name + ".png")
        n = 1
        while os.path.exists(out):
            out = os.path.join(folder, f"{name} ({n}).png")
            n += 1
        try:
            # полноразмерный PNG собираем только здесь, а не на каждый поворот
            with open(out, "wb") as fp:
                fp.write(encode_png(self.img_w, self.img_h, self.img_rgba))
        except OSError as e:
            messagebox.showerror('Saving', f"Could not save:\n{e}")
            return
        note = self.note.get("1.0", "end").strip()
        if note:
            try:
                with open(os.path.splitext(out)[0] + ".txt", "w", encoding="utf-8") as fp:
                    fp.write(note + "\n")
            except OSError:
                pass
        save_last_folder(folder, "last_img_folder")
        self.log_line('Saved: ' + out)
        self.set_status('✔ Saved: ' + os.path.basename(out)
                        + ('  (+ note)' if note else ""), GREEN)

    def browse(self):
        d = filedialog.askdirectory(initialdir=self.folder.get() or DOWNLOADS)
        if d:
            self.folder.set(d)

    def open_folder(self, path):
        path = (path or "").strip()
        if not path or not os.path.isdir(path):
            self.set_status('Folder not found: ' + (path or "—"), WARN)
            return
        os.startfile(path)

    def browse_src(self):
        p = filedialog.askopenfilename(filetypes=MEDIA_TYPES,
                                       initialdir=self.cfolder.get() or DOWNLOADS)
        if p:
            self.src.set(p)
            self.cfolder.set(os.path.dirname(p))

    def _refresh_suggestion(self):
        """Показать/скрыть подсказку с последним скачанным файлом."""
        if self._last_download and os.path.isfile(self._last_download):
            name = os.path.basename(self._last_download)
            if len(name) > 60:
                name = name[:57] + "…"
            self.suggest.configure(text='↳ Use the last download:  ' + name)
            if self.suggest.winfo_manager() != "pack":
                self.suggest.pack(fill="x", padx=16, pady=(3, 0), after=self._src_row)
        else:
            self.suggest.pack_forget()

    def _use_last_download(self):
        if self._last_download and os.path.isfile(self._last_download):
            self.src.set(self._last_download)
            self.cfolder.set(os.path.dirname(self._last_download))
            self.set_status('File set: ' + os.path.basename(self._last_download))

    def _set_last_download(self, path):
        self._last_download = os.path.normpath(path)
        self._refresh_suggestion()

    def browse_cfolder(self):
        d = filedialog.askdirectory(initialdir=self.cfolder.get() or DOWNLOADS)
        if d:
            self.cfolder.set(d)

    def log_line(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def log_clear(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def set_status(self, text, color=MUTE):
        self.status.configure(text=text, foreground=color)

    def _job_begin(self):
        self.cancelled = False
        self.busy = True  # ставится синхронно: self.proc появится лишь в потоке
        self.btn.configure(state="disabled")
        self.cbtn.configure(state="disabled")
        self.upd_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.bar.configure(value=0, style="Run.Horizontal.TProgressbar")
        self.log_clear()

    def _job_end(self, rc, ok_text):
        self.busy = False
        self.btn.configure(state="normal")
        self.cbtn.configure(state="normal")
        self.upd_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        if self.cancelled:
            self.bar.configure(value=0, style="Idle.Horizontal.TProgressbar")
            self.set_status('Cancelled', WARN)
        elif rc == 0:
            self.bar.configure(value=100, style="Run.Horizontal.TProgressbar")
            self.set_status(ok_text, GREEN)
        else:
            self.bar.configure(value=100, style="Err.Horizontal.TProgressbar")
            self.set_status('Error — see the log below', ACCENT)

    @staticmethod
    def _clean_name(name):
        name = re.sub(r'[\\/:*?"<>|]', "", name).strip().rstrip(".")
        return re.sub(r"\.(mp4|mov|mp3|wav|mkv|webm|m4a)$", "", name, flags=re.I)

    # ------------------------------------------------------------ загрузка

    def build_cmd(self, url):
        folder = self.folder.get().strip() or DOWNLOADS
        name = self._clean_name(self.fname.get().strip())
        if name:
            name = name.replace("%", "%%")  # чтобы yt-dlp не принял за шаблон
            if self.playlist.get():
                name += " %(playlist_index)s"  # иначе файлы плейлиста затрут друг друга
            template = name + ".%(ext)s"
        else:
            template = "%(title)s.%(ext)s"
        cmd = ytdlp_cmd() + ["--newline", "--no-mtime",
                             "-o", os.path.join(folder, template),
                             # свои числа вместо готовой строки: ETA у yt-dlp
                             # считается по текущему куску и потому скачет
                             "--progress-template",
                             "download:@P|%(progress.downloaded_bytes)s"
                             "|%(progress.total_bytes)s"
                             "|%(progress.total_bytes_estimate)s"
                             "|%(progress.fragment_index)s"
                             "|%(progress.fragment_count)s"]
        if FFMPEG:
            cmd += ["--ffmpeg-location", FFMPEG]
        if not self.playlist.get():
            cmd += ["--no-playlist"]
        browser = dict(BROWSERS).get(self.cookies.get(), "")
        if browser:
            cmd += ["--cookies-from-browser", browser]

        fmt = self.fmt.get()
        if fmt == "mp4":
            cmd += ["-f", "bestvideo+bestaudio/best"]
            # res = меньшая сторона кадра, поэтому вертикальные видео (9:16)
            # не теряют качество; при равном качестве предпочитаем h264/aac
            m = re.match(r"(\d+)", self.res.get())
            res_key = f"res:{m.group(1)}" if m else "res"
            cmd += ["-S", f"{res_key},vcodec:h264,acodec:m4a"]
            cmd += ["--merge-output-format", "mp4"]
        elif fmt == "mp3":
            cmd += ["-x", "--audio-format", "mp3", "--audio-quality", "0"]
        elif fmt == "wav":
            cmd += ["-x", "--audio-format", "wav"]

        cmd.append(url)
        return cmd

    def start(self):
        if self.busy:  # Enter в поле ссылки не блокируется состоянием кнопки
            return
        url = self.url.get().strip()
        if not url.lower().startswith(("http://", "https://")):
            messagebox.showwarning('No link', 'Paste a video link (http/https).')
            return
        folder = self.folder.get().strip() or DOWNLOADS
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            messagebox.showerror('Folder', f"Could not create the folder:\n{e}")
            return
        save_last_folder(folder)
        save_reg("cookies", self.cookies.get())

        self._dl_candidate = None
        self._reset_progress()
        self._job_begin()
        self.set_status('Starting…')
        threading.Thread(target=self._worker, args=(self.build_cmd(url), folder),
                         daemon=True).start()

    def _worker(self, cmd, folder):
        rc = -1
        try:
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW)
            for line in self.proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                self._ui(self._on_line, line)
            rc = self.proc.wait()
        except FileNotFoundError:
            self._ui(self.log_line,
                            'Could not start yt-dlp: ' + " ".join(ytdlp_cmd()))
        finally:
            self.proc = None
            if rc == 0 and self._dl_candidate:
                self._ui(self._set_last_download, self._dl_candidate)
            self._ui(self._job_end, rc, '✔ Done! Saved to: ' + folder)

    def _track_output_path(self, line):
        """Вылавливаем итоговый путь скачанного файла из вывода yt-dlp.
        Последнее совпадение в потоке — итоговое (после слияния/извлечения)."""
        for pat in (r'\[Merger\] Merging formats into "(.+?)"',
                    r'\[ExtractAudio\] Destination: (.+)$',
                    r'\[download\] Destination: (.+)$',
                    r'\[download\] (.+) has already been downloaded'):
            m = re.search(pat, line)
            if m:
                self._dl_candidate = m.group(1).strip()
                return

    # --- собственный счёт скорости и остатка ---------------------------

    @staticmethod
    def _num(s):
        """Число из поля шаблона; 'NA' и мусор -> None."""
        try:
            v = float(s)
        except (TypeError, ValueError):
            return None
        return v if v > 0 else None

    @staticmethod
    def _fmt_rate(bps):
        for unit, div in (('GB/s', 1 << 30), ('MB/s', 1 << 20), ('KB/s', 1 << 10)):
            if bps >= div:
                return f"{bps / div:.1f} {unit}"
        return f"{bps:.0f} B/s"

    @staticmethod
    def _fmt_time(sec):
        sec = max(int(sec), 0)
        if sec >= 3600:
            return f"{sec // 3600}:{sec // 60 % 60:02d}:{sec % 60:02d}"
        return f"{sec // 60:02d}:{sec % 60:02d}"

    SPEED_POINTS = 120           # ширина истории графика в отсчётах

    def _reset_progress(self):
        self._dl_streams = 1     # сколько файлов качается (видео + звук = 2)
        self._dl_index = 0       # какой идёт сейчас
        self._dl_samples = deque()
        self._dl_last = -1.0
        self._pl_index = self._pl_total = 0   # позиция в плейлисте
        self._speed_hist = deque(maxlen=self.SPEED_POINTS)
        self._graph_at = 0.0     # когда последний раз перерисовывали

    def _new_media_item(self):
        """Начался следующий ролик: счётчик видео/звук — заново."""
        self._dl_index = 0
        self._dl_last = -1.0
        self._dl_samples.clear()

    def _on_progress(self, fields):
        done = self._num(fields[0])
        total = self._num(fields[1]) or self._num(fields[2])
        frag_i, frag_n = self._num(fields[3]), self._num(fields[4])
        if done is None:
            return
        now = time.monotonic()

        # счётчик байт пошёл сначала — значит начался следующий поток
        if done < self._dl_last:
            self._dl_index += 1
            self._dl_samples.clear()
        self._dl_last = done

        # окно ~6 секунд: сглаживает рывки фрагментов, но не врёт при обрыве
        self._dl_samples.append((now, done))
        while len(self._dl_samples) > 2 and now - self._dl_samples[0][0] > 6:
            self._dl_samples.popleft()

        if total:
            pct = min(done / total * 100, 100)
        elif frag_n:
            pct = min((frag_i or 0) / frag_n * 100, 100)
        else:
            pct = None
        if pct is not None:
            self.bar.configure(value=pct)

        rate = None
        if len(self._dl_samples) >= 2:
            (t0, b0), (t1, b1) = self._dl_samples[0], self._dl_samples[-1]
            if t1 - t0 >= 0.7 and b1 > b0:
                rate = (b1 - b0) / (t1 - t0)

        if self._dl_streams > 1:
            name = ('Video', 'Audio')[self._dl_index] if self._dl_index < 2 \
                else f"File {self._dl_index + 1}"
        else:
            name = 'Downloading'

        parts = [f"{name}: {pct:.1f}%" if pct is not None else name]
        if rate:
            parts.append(self._fmt_rate(rate))
            # оценка размера бывает занижена: скачано может превысить total,
            # и тогда «осталось» показывать уже нечего
            left = max((total or 0) - done, 0)
            if left > 0:
                parts.append('left ' + self._fmt_time(left / rate))
        if self._dl_streams > 1:
            parts.append(f"file {self._dl_index + 1} of {self._dl_streams}")
        if self._pl_total > 1:
            parts.append(f"video {self._pl_index} of {self._pl_total}")
        self.set_status("  •  ".join(parts))

        # график: копим точки и перерисовываем не чаще 4 раз в секунду
        if rate:
            self._speed_hist.append(rate)
            if self.graph_open and now - self._graph_at > 0.25:
                self._graph_at = now
                self._draw_graph()

    def _on_line(self, line):
        if line.startswith("@P|"):
            self._on_progress(line[3:].split("|"))
            return
        # позиция в плейлисте: «Downloading item 2 of 12»
        m = re.search(r"Downloading item (\d+) of (\d+)", line)
        if m:
            self._pl_index, self._pl_total = int(m.group(1)), int(m.group(2))
        # сколько файлов будет: «Downloading 1 format(s): 137+140» -> два.
        # Строка приходит на КАЖДЫЙ ролик, поэтому здесь же обнуляем счётчик
        # видео/звук — иначе на плейлисте он растёт до «file 5 of 2»
        m = re.search(r"Downloading \d+ format\(s\):\s*(\S+)", line)
        if m:
            self._dl_streams = len(m.group(1).split("+"))
            self._new_media_item()
        # запасной разбор, если --progress-template не поддержан
        m = re.search(r"\[download\]\s+([\d.]+)%", line)
        if m:
            pct = float(m.group(1))
            self.bar.configure(value=pct)
            self.set_status(f"Downloading: {pct:.1f}%")
            return
        self._track_output_path(line)
        if "[Merger]" in line or "[ExtractAudio]" in line:
            self.set_status('Processing (ffmpeg)…')
        self.log_line(line)

    # ------------------------------------------------------------ конвертация

    def build_ffmpeg_cmd(self, src, out):
        fmt = self.cfmt.get()
        comp = self.comp.get()
        cmd = [FFMPEG, "-hide_banner", "-loglevel", "error",
               "-progress", "pipe:1", "-nostats", "-y", "-i", src]
        if fmt in ("mp4", "mov"):
            scale = None
            m = re.match(r"(\d+)", self.cres.get())
            if m:
                # ограничиваем МЕНЬШУЮ сторону кадра: горизонтальное видео —
                # по высоте, вертикальное (9:16) — по ширине; меньшее видео
                # не растягиваем, стороны делаем чётными
                h = m.group(1)
                scale = (f"scale="
                         f"'if(gt(iw,ih),-2,2*trunc(min({h}\\,iw)/2))':"
                         f"'if(gt(iw,ih),2*trunc(min({h}\\,ih)/2),-2)'")
            fps = self.cfps.get() if re.match(r"\d", self.cfps.get()) else None
            if fmt == "mov":
                # DNxHR: all-intra, жёстко постоянный FPS и несжатый звук —
                # то, что монтажки любят больше всего
                if scale:
                    cmd += ["-vf", scale]
                if fps:
                    cmd += ["-r", fps]
                cmd += ["-c:v", "dnxhd", "-profile:v", DNX.get(comp, "dnxhr_sq"),
                        "-pix_fmt", "yuv422p", "-fps_mode", "cfr",
                        "-c:a", "pcm_s16le"]
            elif comp == 'No re-encode' and not scale and not fps:
                cmd += ["-c", "copy"]
            else:
                crf = CRF.get(comp, "20")  # «без пережатия» + масштаб => высокое качество
                if scale:
                    cmd += ["-vf", scale]
                if fps:
                    cmd += ["-r", fps]
                cmd += ["-c:v", "libx264", "-crf", crf, "-preset", "veryfast",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]
        elif fmt == "mp3":
            cmd += ["-vn", "-c:a", "libmp3lame", "-b:a", MP3_BR.get(comp, "192k")]
        else:  # wav
            cmd += ["-vn", "-c:a", "pcm_s16le"]
        cmd.append(out)
        return cmd

    def start_convert(self):
        if self.busy:
            return
        if not FFMPEG:
            messagebox.showerror("ffmpeg", 'ffmpeg not found — conversion unavailable.')
            return
        src = self.src.get().strip().strip('"')
        if not src or not os.path.isfile(src):
            messagebox.showwarning('No file', 'Choose a file to convert.')
            return
        folder = self.cfolder.get().strip() or os.path.dirname(src)
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            messagebox.showerror('Folder', f"Could not create the folder:\n{e}")
            return

        fmt = self.cfmt.get()
        name = self._clean_name(self.cname.get().strip()) \
            or os.path.splitext(os.path.basename(src))[0]
        out = os.path.join(folder, f"{name}.{fmt}")
        if os.path.normcase(out) == os.path.normcase(src):
            out = os.path.join(folder, f"{name}_conv.{fmt}")
        n = 1
        base = out
        while os.path.exists(out):  # не затираем существующие файлы
            root_, ext_ = os.path.splitext(base)
            out = f"{root_} ({n}){ext_}"
            n += 1

        # команду собираем ЗДЕСЬ, в главном потоке: build_ffmpeg_cmd читает
        # tk-переменные, а обращаться к ним из фонового потока нельзя
        cmd = self.build_ffmpeg_cmd(src, out)

        self._job_begin()
        self.set_status('Preparing…')
        threading.Thread(target=self._conv_worker, args=(src, out, cmd),
                         daemon=True).start()

    def _probe_duration(self, src):
        if not FFPROBE or not os.path.exists(FFPROBE):
            return 0.0
        try:
            r = subprocess.run(
                [FFPROBE, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", src],
                capture_output=True, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW)
            return float(r.stdout.strip())
        except (ValueError, subprocess.SubprocessError, OSError):
            return 0.0

    def _conv_worker(self, src, out, cmd):
        rc = -1
        duration = self._probe_duration(src)
        try:
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW)
            speed = ""
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("speed="):
                    speed = line.split("=", 1)[1].strip()
                elif line.startswith("out_time_ms="):
                    try:
                        sec = int(line.split("=", 1)[1]) / 1_000_000
                    except ValueError:
                        continue
                    self._ui(self._on_conv_progress, sec, duration, speed)
                elif "=" not in line:  # не служебная строка прогресса — значит ошибка
                    self._ui(self.log_line, line)
            rc = self.proc.wait()
        except FileNotFoundError:
            self._ui(self.log_line, f"ffmpeg not found: {FFMPEG}")
        finally:
            self.proc = None
            if rc == 0:
                self._ui(self.log_line, 'Saved: ' + out)
            elif os.path.exists(out):
                # недоделанный файл убираем и при ошибке, и при отмене:
                # раньше после отмены на диске оставался битый файл,
                # который выглядел как готовый
                try:
                    os.remove(out)
                except OSError:
                    pass
            self._ui(self._job_end, rc, '✔ Done! ' + os.path.basename(out))

    def _on_conv_progress(self, sec, duration, speed):
        if duration > 0:
            pct = min(sec / duration * 100, 100)
            self.bar.configure(value=pct)
            text = f"Converting: {pct:.1f}%"
        else:
            text = f"Converting: {sec:.0f} s processed"
        if speed:
            text += f"  •  speed {speed}"
        self.set_status(text)

    # ------------------------------------------------------------ обновление

    @staticmethod
    def _python_for_ytdlp():
        """Интерпретатор, которому принадлежит yt-dlp.exe (…\\Scripts\\yt-dlp.exe)."""
        cand = os.path.join(os.path.dirname(os.path.dirname(YTDLP)), "python.exe")
        return cand if os.path.exists(cand) else sys.executable

    def _upd_cmd(self):
        """Чем обновляться. В exe-сборке pip недоступен: там либо обновляем
        подложенный рядом yt-dlp.exe, либо честно говорим, что нечем."""
        if YTDLP and (FROZEN or YTDLP.lower().endswith("yt-dlp.exe")
                      and not os.path.exists(self._python_for_ytdlp())):
            return [YTDLP, "-U"]
        if FROZEN:
            return None
        return [self._python_for_ytdlp(), "-m", "pip", "install", "-U",
                "--disable-pip-version-check", "yt-dlp"]

    def update_ytdlp(self):
        if self.busy:
            return
        if self._upd_cmd() is None:
            messagebox.showinfo(
                'Update',
                'yt-dlp is bundled into this build and ships with it.\n\nTo update right now, download a fresh yt-dlp.exe from github.com/yt-dlp/yt-dlp and put it next to this program — it will be picked up automatically.')
            return
        self._job_begin()
        self.bar.configure(mode="indeterminate")
        self.bar.start(12)
        self.set_status('Updating yt-dlp… (may take a minute)')
        threading.Thread(target=self._upd_worker, daemon=True).start()

    def _upd_worker(self):
        rc, ver = -1, ""
        cmd = self._upd_cmd()
        try:
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW)
            for line in self.proc.stdout:
                line = line.rstrip()
                if line:
                    self._ui(self.log_line, line)
            rc = self.proc.wait()
        except OSError as e:
            self._ui(self.log_line, f"Could not start the update: {e}")
        finally:
            self.proc = None
        if rc == 0:
            try:
                ver = subprocess.run(ytdlp_cmd() + ["--version"], capture_output=True,
                                     text=True, timeout=60,
                                     creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                pass
        self._ui(self._upd_done, rc, ver)

    def _upd_done(self, rc, ver):
        self.bar.stop()
        self.bar.configure(mode="determinate", value=0)
        self._job_end(rc, '✔ yt-dlp updated' + (f" — version {ver}" if ver else ""))

    # ------------------------------------------------------------ отмена

    def _ui(self, fn, *args):
        """Обновление интерфейса из рабочего потока. После закрытия окна
        Tk уже мёртв — тогда просто молчим, а не сыплем трейсбеком."""
        try:
            self.root.after(0, fn, *args)
        except (tk.TclError, RuntimeError):
            pass

    def _kill_proc(self):
        """yt-dlp может держать дочерний ffmpeg — валим всё дерево."""
        p = self.proc
        if not p:
            return
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                       creationflags=subprocess.CREATE_NO_WINDOW,
                       capture_output=True)

    def cancel(self):
        if not self.proc:
            return
        self.cancelled = True
        self._kill_proc()

    def on_close(self):
        """Без этого закрытое окно оставляет yt-dlp и ffmpeg работать в фоне:
        дочерние процессы не умирают вместе с родителем."""
        if self.busy and not messagebox.askokcancel(
                'Quit', 'A job is still running. Stop it and quit?'):
            return
        self.cancelled = True
        self._kill_proc()
        self.root.destroy()


if __name__ == "__main__":
    setup_windows_look()
    root = TkinterDnD.Tk() if TkinterDnD else tk.Tk()
    App(root)
    root.mainloop()
