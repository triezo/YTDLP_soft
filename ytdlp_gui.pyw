# -*- coding: utf-8 -*-
"""Простой графический интерфейс для yt-dlp + конвертер/сжатие через ffmpeg.

Запуск: ярлык на рабочем столе, "YT-DLP GUI.bat" или этот .pyw
питоном 3.12, где установлены tkinter и yt-dlp.
"""

import os
import re
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
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

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


def dib_to_png(d):
    """CF_DIB из буфера обмена -> (png_bytes, w, h) или None."""
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
    return encode_png(w, h, bytes(out)), w, h


def clipboard_image_png():
    """Изображение из буфера обмена -> (png_bytes, w, h) или None."""
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
        fmt_png = u32.RegisterClipboardFormatW("PNG")
        if fmt_png and u32.IsClipboardFormatAvailable(fmt_png):
            data = grab(fmt_png)
            if data and data[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", data[16:24])
                return data, w, h
        if u32.IsClipboardFormatAvailable(8):  # CF_DIB
            data = grab(8)
            if data:
                return dib_to_png(data)
    finally:
        u32.CloseClipboard()
    return None

# ---------------------------------------------------------------- пути

def find_ytdlp():
    exe = shutil.which("yt-dlp")
    if exe:
        return exe
    hits = glob.glob(os.path.expandvars(
        r"%LOCALAPPDATA%\Programs\Python\Python3*\Scripts\yt-dlp.exe"))
    return hits[-1] if hits else "yt-dlp"


YTDLP = find_ytdlp()


def find_ffmpeg():
    ff = shutil.which("ffmpeg")
    if ff:
        return ff
    hits = glob.glob(os.path.expandvars(
        r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\ffmpeg-*\bin\ffmpeg.exe"))
    return hits[0] if hits else None


FFMPEG = find_ffmpeg()
FFPROBE = (os.path.join(os.path.dirname(FFMPEG), "ffprobe.exe")
           if FFMPEG else None)
DOWNLOADS = os.path.join(os.path.expanduser("~"), "Downloads")

RESOLUTIONS = ["Лучшее", "2160p (4K)", "1440p", "1080p", "720p", "480p", "360p"]
FPS_LIST = ["Как в оригинале", "60", "50", "30", "25", "24", "15"]
COMPRESSIONS = ["Без пережатия", "Лёгкое сжатие", "Среднее сжатие", "Сильное сжатие"]
# mp4: CRF x264 (больше = меньше файл); mp3: битрейт
CRF = {"Лёгкое сжатие": "20", "Среднее сжатие": "26", "Сильное сжатие": "32"}
# монтажный DNxHR: каждый кадр самостоятельный, Premiere листает без лагов
DNX = {"Без пережатия": "dnxhr_hq", "Лёгкое сжатие": "dnxhr_hq",
       "Среднее сжатие": "dnxhr_sq", "Сильное сжатие": "dnxhr_lb"}
MP3_BR = {"Без пережатия": "320k", "Лёгкое сжатие": "256k",
          "Среднее сжатие": "192k", "Сильное сжатие": "128k"}

MEDIA_TYPES = [("Видео и аудио",
                "*.mp4 *.mkv *.webm *.avi *.mov *.wmv *.flv *.ts "
                "*.m4a *.mp3 *.wav *.flac *.opus *.ogg *.aac"),
               ("Все файлы", "*.*")]

# ---------------------------------------------------------------- цвета

BG = "#1e1f24"
BG2 = "#2a2b32"
FG = "#e8e8ea"
ACCENT = "#e5484d"
GREEN = "#46a758"
MUTE = "#8b8d98"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.proc = None
        self.cancelled = False
        self._last_download = None   # путь последнего скачанного файла
        self._dl_candidate = None    # кандидат, вычисляемый из вывода yt-dlp

        root.title("YT-DLP — загрузчик видео")
        ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico")
        if os.path.exists(ico):
            try:
                root.iconbitmap(ico)
            except tk.TclError:
                pass
        root.configure(bg=BG)
        root.geometry("640x700")
        root.minsize(580, 620)

        self._styles()
        self._build()

    # ------------------------------------------------------------ ui

    def _styles(self):
        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=FG, fieldbackground=BG2,
                    bordercolor=BG2, lightcolor=BG2, darkcolor=BG2)
        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG, foreground=FG, font=("Segoe UI", 10))
        s.configure("Muted.TLabel", foreground=MUTE, font=("Segoe UI", 9))
        s.configure("Big.TLabel", font=("Segoe UI Semibold", 14))
        s.configure("TButton", font=("Segoe UI", 10), padding=6,
                    background=BG2, foreground=FG, borderwidth=0)
        s.map("TButton", background=[("active", "#3a3b44")])
        s.configure("Accent.TButton", background=ACCENT, foreground="white",
                    font=("Segoe UI Semibold", 11), padding=8)
        s.map("Accent.TButton", background=[("active", "#f2555a"), ("disabled", "#5a3033")])
        s.configure("TRadiobutton", background=BG, foreground=FG, font=("Segoe UI", 10))
        s.map("TRadiobutton", background=[("active", BG)])
        s.configure("TCheckbutton", background=BG, foreground=FG, font=("Segoe UI", 10))
        s.map("TCheckbutton", background=[("active", BG)])
        s.configure("TCombobox", padding=4, arrowcolor=FG)
        s.map("TCombobox",
              fieldbackground=[("readonly", BG2), ("disabled", "#232429")],
              foreground=[("readonly", FG), ("disabled", "#5c5e6a")],
              selectbackground=[("readonly", BG2)],
              selectforeground=[("readonly", FG)],
              arrowcolor=[("disabled", "#5c5e6a")])
        # выпадающий список комбобокса — обычный tk-Listbox, стилю ttk не
        # подчиняется, красим через базу опций
        self.root.option_add("*TCombobox*Listbox.background", BG2)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "white")
        self.root.option_add("*TCombobox*Listbox.borderWidth", 0)
        self.root.option_add("*TCombobox*Listbox.font", "{Segoe UI} 10")
        s.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(12, 8, 12, 0))
        s.configure("TNotebook.Tab", background=BG2, foreground=MUTE,
                    font=("Segoe UI Semibold", 10), padding=(18, 8), borderwidth=0)
        s.map("TNotebook.Tab",
              background=[("selected", ACCENT), ("active", "#3a3b44")],
              foreground=[("selected", "white"), ("active", FG)])
        for name, color in [("Idle", "#111114"), ("Run", GREEN), ("Err", ACCENT)]:
            s.configure(f"{name}.Horizontal.TProgressbar", background=color,
                        troughcolor=BG2, borderwidth=0, thickness=14)

    def _build(self):
        pad = {"padx": 16}
        f = ttk.Frame(self.root)
        f.pack(fill="both", expand=True)

        nb = ttk.Notebook(f)
        nb.pack(fill="x", pady=(10, 0))
        self.nb = nb
        tab_dl = ttk.Frame(nb)
        tab_cv = ttk.Frame(nb)
        tab_im = ttk.Frame(nb)
        nb.add(tab_dl, text="⬇  Загрузка")
        nb.add(tab_cv, text="⚙  Конвертация")
        nb.add(tab_im, text="🖼  Картинка")

        self._build_download_tab(tab_dl, pad)
        self._build_convert_tab(tab_cv, pad)
        self._build_image_tab(tab_im, pad)

        # Ctrl+V на вкладке «Картинка» (вне полей ввода) вставляет из буфера
        self.root.bind("<Control-KeyPress>", self._root_ctrl)

        # --- общие прогресс, статус и лог
        self.bar = ttk.Progressbar(f, maximum=100, style="Idle.Horizontal.TProgressbar")
        self.bar.pack(fill="x", pady=(14, 4), **pad)
        row = ttk.Frame(f)
        row.pack(fill="x", **pad)
        self.status = ttk.Label(row, text="Готов к работе", style="Muted.TLabel")
        self.status.pack(side="left", fill="x", expand=True)
        self.cancel_btn = ttk.Button(row, text="Отмена", command=self.cancel,
                                     state="disabled")
        self.cancel_btn.pack(side="right")

        self.log = tk.Text(f, height=7, bg="#17181c", fg=MUTE, relief="flat",
                           font=("Consolas", 9), state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, padx=16, pady=(8, 14))

    def _build_download_tab(self, f, pad):
        ttk.Label(f, text="Ссылка на видео:").pack(anchor="w", pady=(12, 2), **pad)
        row = ttk.Frame(f)
        row.pack(fill="x", **pad)
        self.url = tk.StringVar()
        e = tk.Entry(row, textvariable=self.url, font=("Segoe UI", 11),
                     bg=BG2, fg=FG, insertbackground=FG, relief="flat")
        e.pack(side="left", fill="x", expand=True, ipady=6)
        e.bind("<Return>", lambda _e: self.start())
        self._entry_hotkeys(e)
        ttk.Button(row, text="Вставить", command=self.paste).pack(side="left", padx=(8, 0))

        ttk.Label(f, text="Формат:").pack(anchor="w", pady=(14, 2), **pad)
        row = ttk.Frame(f)
        row.pack(fill="x", **pad)
        self.fmt = tk.StringVar(value="mp4")
        for val, text in [("mp4", "MP4 (видео)"), ("mp3", "MP3 (аудио)"), ("wav", "WAV (аудио)")]:
            ttk.Radiobutton(row, text=text, value=val, variable=self.fmt,
                            command=self._fmt_changed).pack(side="left", padx=(0, 18))

        row = ttk.Frame(f)
        row.pack(fill="x", pady=(12, 0), **pad)
        ttk.Label(row, text="Разрешение:").pack(side="left")
        self.res = tk.StringVar(value="1080p")
        self.res_box = ttk.Combobox(row, textvariable=self.res, values=RESOLUTIONS,
                                    state="readonly", width=14)
        self.res_box.pack(side="left", padx=(10, 0))

        self.playlist = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="Скачать весь плейлист",
                        variable=self.playlist).pack(side="left", padx=(24, 0))

        ttk.Label(f, text="Папка сохранения:").pack(anchor="w", pady=(14, 2), **pad)
        row = ttk.Frame(f)
        row.pack(fill="x", **pad)
        self.folder = tk.StringVar(value=load_last_folder() or DOWNLOADS)
        e2 = tk.Entry(row, textvariable=self.folder, font=("Segoe UI", 10),
                      bg=BG2, fg=FG, insertbackground=FG, relief="flat")
        e2.pack(side="left", fill="x", expand=True, ipady=5)
        self._entry_hotkeys(e2)
        ttk.Button(row, text="Обзор…", command=self.browse).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Открыть",
                   command=lambda: self.open_folder(self.folder.get())).pack(side="left", padx=(6, 0))

        ttk.Label(f, text="Имя файла (пусто — название видео):").pack(
            anchor="w", pady=(14, 2), **pad)
        self.fname = tk.StringVar()
        e3 = tk.Entry(f, textvariable=self.fname, font=("Segoe UI", 10),
                      bg=BG2, fg=FG, insertbackground=FG, relief="flat")
        e3.pack(fill="x", ipady=5, **pad)
        self._entry_hotkeys(e3)

        self.btn = ttk.Button(f, text="⬇  Скачать", style="Accent.TButton",
                              command=self.start)
        self.btn.pack(fill="x", pady=(16, 14), **pad)

    def _build_convert_tab(self, f, pad):
        ttk.Label(f, text="Файл на компьютере:").pack(anchor="w", pady=(12, 2), **pad)
        self._src_row = row = ttk.Frame(f)
        row.pack(fill="x", **pad)
        self.src = tk.StringVar()
        e = tk.Entry(row, textvariable=self.src, font=("Segoe UI", 10),
                     bg=BG2, fg=FG, insertbackground=FG, relief="flat")
        e.pack(side="left", fill="x", expand=True, ipady=6)
        self._entry_hotkeys(e)
        e.bind("<FocusIn>", lambda _e: self._refresh_suggestion())
        ttk.Button(row, text="Обзор…", command=self.browse_src).pack(side="left", padx=(8, 0))

        # кликабельная подсказка: подставить только что скачанный файл
        self.suggest = tk.Label(f, text="", bg=BG, fg=ACCENT, cursor="hand2",
                                font=("Segoe UI", 9), anchor="w", justify="left")
        self.suggest.bind("<Button-1>", lambda _e: self._use_last_download())

        ttk.Label(f, text="Конвертировать в:").pack(anchor="w", pady=(14, 2), **pad)
        row = ttk.Frame(f)
        row.pack(fill="x", **pad)
        self.cfmt = tk.StringVar(value="mp4")
        for val, text in [("mp4", "MP4 (видео)"), ("mov", "MOV (для монтажа)"),
                          ("mp3", "MP3 (аудио)"), ("wav", "WAV (аудио)")]:
            ttk.Radiobutton(row, text=text, value=val, variable=self.cfmt,
                            command=self._cfmt_changed).pack(side="left", padx=(0, 14))

        row = ttk.Frame(f)
        row.pack(fill="x", pady=(12, 0), **pad)
        ttk.Label(row, text="Сжатие:").pack(side="left")
        self.comp = tk.StringVar(value="Среднее сжатие")
        self.comp_box = ttk.Combobox(row, textvariable=self.comp, values=COMPRESSIONS,
                                     state="readonly", width=16)
        self.comp_box.pack(side="left", padx=(10, 0))
        ttk.Label(row, text="Разрешение:").pack(side="left", padx=(18, 0))
        self.cres = tk.StringVar(value="Лучшее")
        self.cres_box = ttk.Combobox(row, textvariable=self.cres, values=RESOLUTIONS,
                                     state="readonly", width=12)
        self.cres_box.pack(side="left", padx=(10, 0))

        self.hint = ttk.Label(f, text="", style="Muted.TLabel", wraplength=560,
                              justify="left")
        self.hint.pack(anchor="w", pady=(6, 0), **pad)

        row = ttk.Frame(f)
        row.pack(fill="x", pady=(12, 0), **pad)
        ttk.Label(row, text="Кадров/с (FPS):").pack(side="left")
        self.cfps = tk.StringVar(value="Как в оригинале")
        self.cfps_box = ttk.Combobox(row, textvariable=self.cfps, values=FPS_LIST,
                                     state="readonly", width=16)
        self.cfps_box.pack(side="left", padx=(10, 0))

        ttk.Label(f, text="Папка сохранения:").pack(anchor="w", pady=(14, 2), **pad)
        row = ttk.Frame(f)
        row.pack(fill="x", **pad)
        self.cfolder = tk.StringVar()
        e2 = tk.Entry(row, textvariable=self.cfolder, font=("Segoe UI", 10),
                      bg=BG2, fg=FG, insertbackground=FG, relief="flat")
        e2.pack(side="left", fill="x", expand=True, ipady=5)
        self._entry_hotkeys(e2)
        ttk.Button(row, text="Обзор…", command=self.browse_cfolder).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Открыть",
                   command=lambda: self.open_folder(self.cfolder.get())).pack(side="left", padx=(6, 0))

        ttk.Label(f, text="Имя файла (пусто — имя исходника):").pack(
            anchor="w", pady=(14, 2), **pad)
        self.cname = tk.StringVar()
        e3 = tk.Entry(f, textvariable=self.cname, font=("Segoe UI", 10),
                      bg=BG2, fg=FG, insertbackground=FG, relief="flat")
        e3.pack(fill="x", ipady=5, **pad)
        self._entry_hotkeys(e3)

        self.cbtn = ttk.Button(f, text="⚙  Конвертировать", style="Accent.TButton",
                               command=self.start_convert)
        self.cbtn.pack(fill="x", pady=(16, 14), **pad)

    def _build_image_tab(self, f, pad):
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(12, 0), **pad)
        ttk.Button(row, text="📋  Вставить из буфера (Ctrl+V)",
                   command=self.paste_image).pack(side="left")
        self.img_info = ttk.Label(row, text="", style="Muted.TLabel")
        self.img_info.pack(side="left", padx=(12, 0))

        holder = tk.Frame(f, bg="#17181c", height=190)
        holder.pack(fill="x", pady=(10, 0), **pad)
        holder.pack_propagate(False)
        self.preview = tk.Label(holder, bg="#17181c", fg=MUTE,
                                text="Скопируйте скрин или картинку\nи вставьте сюда (Ctrl+V)",
                                font=("Segoe UI", 10))
        self.preview.pack(fill="both", expand=True)
        self.preview.bind("<Button-1>", lambda _e: self.paste_image())
        self._preview_img = None
        self.img_png = None  # PNG-байты текущей картинки

        ttk.Label(f, text="Заметка (сохранится в .txt рядом с картинкой):").pack(
            anchor="w", pady=(10, 2), **pad)
        self.note = tk.Text(f, height=3, bg=BG2, fg=FG, insertbackground=FG,
                            relief="flat", font=("Segoe UI", 10), wrap="word")
        self.note.pack(fill="x", **pad)
        self._text_hotkeys(self.note)

        row = ttk.Frame(f)
        row.pack(fill="x", pady=(10, 0), **pad)
        ttk.Label(row, text="Папка:").pack(side="left")
        self.ifolder = tk.StringVar(
            value=load_last_folder("last_img_folder")
            or os.path.join(os.path.expanduser("~"), "Pictures"))
        e = tk.Entry(row, textvariable=self.ifolder, font=("Segoe UI", 10),
                     bg=BG2, fg=FG, insertbackground=FG, relief="flat")
        e.pack(side="left", fill="x", expand=True, ipady=5, padx=(10, 0))
        self._entry_hotkeys(e)
        ttk.Button(row, text="Обзор…", command=self.browse_ifolder).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Открыть",
                   command=lambda: self.open_folder(self.ifolder.get())).pack(side="left", padx=(6, 0))

        row = ttk.Frame(f)
        row.pack(fill="x", pady=(10, 0), **pad)
        ttk.Label(row, text="Имя (пусто — дата и время):").pack(side="left")
        self.iname = tk.StringVar()
        e2 = tk.Entry(row, textvariable=self.iname, font=("Segoe UI", 10),
                      bg=BG2, fg=FG, insertbackground=FG, relief="flat")
        e2.pack(side="left", fill="x", expand=True, ipady=5, padx=(10, 0))
        self._entry_hotkeys(e2)

        self.ibtn = ttk.Button(f, text="💾  Сохранить", style="Accent.TButton",
                               command=self.save_image)
        self.ibtn.pack(fill="x", pady=(14, 14), **pad)

    # ------------------------------------------------------------ helpers

    def _fmt_changed(self):
        self.res_box.configure(state="readonly" if self.fmt.get() == "mp4" else "disabled")

    def _cfmt_changed(self):
        fmt = self.cfmt.get()
        video = fmt in ("mp4", "mov")
        self.cres_box.configure(state="readonly" if video else "disabled")
        self.cfps_box.configure(state="readonly" if video else "disabled")
        self.comp_box.configure(state="readonly" if fmt != "wav" else "disabled")
        self.hint.configure(
            text=("Монтажный формат DNxHR: Premiere листает без лагов, "
                  "но файл выходит в разы тяжелее." if fmt == "mov" else ""))

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

        menu = tk.Menu(entry, tearoff=0, bg=BG2, fg=FG,
                       activebackground=ACCENT, activeforeground="white")
        menu.add_command(label="Вставить", command=lambda: self._insert_clip(entry))
        menu.add_command(label="Копировать", command=lambda: entry.event_generate("<<Copy>>"))
        menu.add_command(label="Вырезать", command=lambda: entry.event_generate("<<Cut>>"))
        menu.add_separator()
        menu.add_command(label="Выделить всё",
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
            self.set_status("Буфер обмена пуст или в нём не текст", "#e2b53e")

    # ------------------------------------------------------------ картинка

    def paste_image(self):
        try:
            res = clipboard_image_png()
        except OSError:
            res = None
        if not res:
            self.set_status("В буфере обмена нет изображения", "#e2b53e")
            return
        png, w, h = res
        self.img_png = png
        try:
            img = tk.PhotoImage(data=png)
            k = max(1, -(-w // 560), -(-h // 180))  # вписываем в превью
            if k > 1:
                img = img.subsample(k, k)
            self._preview_img = img
            self.preview.configure(image=img, text="")
        except tk.TclError:
            self._preview_img = None
            self.preview.configure(image="", text=f"Изображение {w}×{h}\n(превью недоступно)")
        self.img_info.configure(text=f"{w}×{h}, {len(png) // 1024} КБ")
        self.set_status("Изображение вставлено — можно сохранять")

    def browse_ifolder(self):
        d = filedialog.askdirectory(initialdir=self.ifolder.get() or DOWNLOADS)
        if d:
            self.ifolder.set(d)

    def save_image(self):
        if not self.img_png:
            messagebox.showwarning("Нет изображения",
                                   "Сначала вставьте картинку из буфера обмена.")
            return
        folder = self.ifolder.get().strip() or os.path.join(os.path.expanduser("~"), "Pictures")
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Папка", f"Не удалось создать папку:\n{e}")
            return
        name = self._clean_name(self.iname.get().strip()) \
            or "Скрин " + time.strftime("%Y-%m-%d %H-%M-%S")
        out = os.path.join(folder, name + ".png")
        n = 1
        while os.path.exists(out):
            out = os.path.join(folder, f"{name} ({n}).png")
            n += 1
        try:
            with open(out, "wb") as fp:
                fp.write(self.img_png)
        except OSError as e:
            messagebox.showerror("Сохранение", f"Не удалось сохранить:\n{e}")
            return
        note = self.note.get("1.0", "end").strip()
        if note:
            try:
                with open(os.path.splitext(out)[0] + ".txt", "w", encoding="utf-8") as fp:
                    fp.write(note + "\n")
            except OSError:
                pass
        save_last_folder(folder, "last_img_folder")
        self.log_line("Сохранено: " + out)
        self.set_status("✔ Сохранено: " + os.path.basename(out)
                        + ("  (+ заметка)" if note else ""), GREEN)

    def browse(self):
        d = filedialog.askdirectory(initialdir=self.folder.get() or DOWNLOADS)
        if d:
            self.folder.set(d)

    def open_folder(self, path):
        path = (path or "").strip()
        if not path or not os.path.isdir(path):
            self.set_status("Папка не найдена: " + (path or "—"), "#e2b53e")
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
            self.suggest.configure(text="↳ Взять последнюю загрузку:  " + name)
            if self.suggest.winfo_manager() != "pack":
                self.suggest.pack(fill="x", padx=16, pady=(3, 0), after=self._src_row)
        else:
            self.suggest.pack_forget()

    def _use_last_download(self):
        if self._last_download and os.path.isfile(self._last_download):
            self.src.set(self._last_download)
            self.cfolder.set(os.path.dirname(self._last_download))
            self.set_status("Подставлен файл: " + os.path.basename(self._last_download))

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
        self.btn.configure(state="disabled")
        self.cbtn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.bar.configure(value=0, style="Run.Horizontal.TProgressbar")
        self.log_clear()

    def _job_end(self, rc, ok_text):
        self.btn.configure(state="normal")
        self.cbtn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        if self.cancelled:
            self.bar.configure(value=0, style="Idle.Horizontal.TProgressbar")
            self.set_status("Отменено", "#e2b53e")
        elif rc == 0:
            self.bar.configure(value=100, style="Run.Horizontal.TProgressbar")
            self.set_status(ok_text, GREEN)
        else:
            self.bar.configure(value=100, style="Err.Horizontal.TProgressbar")
            self.set_status("Ошибка — подробности в логе ниже", ACCENT)

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
        cmd = [YTDLP, "--newline", "--no-mtime",
               "-o", os.path.join(folder, template)]
        if FFMPEG:
            cmd += ["--ffmpeg-location", FFMPEG]
        if not self.playlist.get():
            cmd += ["--no-playlist"]

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
        if self.proc:
            return
        url = self.url.get().strip()
        if not url.lower().startswith(("http://", "https://")):
            messagebox.showwarning("Нет ссылки", "Вставьте ссылку на видео (http/https).")
            return
        folder = self.folder.get().strip() or DOWNLOADS
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Папка", f"Не удалось создать папку:\n{e}")
            return
        save_last_folder(folder)

        self._dl_candidate = None
        self._job_begin()
        self.set_status("Запуск…")
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
                self.root.after(0, self._on_line, line)
            rc = self.proc.wait()
        except FileNotFoundError:
            self.root.after(0, self.log_line, f"Не найден yt-dlp: {YTDLP}")
        finally:
            self.proc = None
            if rc == 0 and self._dl_candidate:
                self.root.after(0, self._set_last_download, self._dl_candidate)
            self.root.after(0, self._job_end, rc, "✔ Готово! Файл в папке: " + folder)

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

    def _on_line(self, line):
        m = re.search(r"\[download\]\s+([\d.]+)%", line)
        if m:
            pct = float(m.group(1))
            self.bar.configure(value=pct)
            extra = re.search(r"at\s+(\S+)\s+ETA\s+(\S+)", line)
            if extra:
                self.set_status(f"Загрузка: {pct:.1f}%  •  {extra.group(1)}  •  осталось {extra.group(2)}")
            else:
                self.set_status(f"Загрузка: {pct:.1f}%")
            return
        self._track_output_path(line)
        if "[Merger]" in line or "[ExtractAudio]" in line:
            self.set_status("Обработка (ffmpeg)…")
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
            elif comp == "Без пережатия" and not scale and not fps:
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
        if self.proc:
            return
        if not FFMPEG:
            messagebox.showerror("ffmpeg", "ffmpeg не найден — конвертация недоступна.")
            return
        src = self.src.get().strip().strip('"')
        if not src or not os.path.isfile(src):
            messagebox.showwarning("Нет файла", "Выберите файл для конвертации.")
            return
        folder = self.cfolder.get().strip() or os.path.dirname(src)
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Папка", f"Не удалось создать папку:\n{e}")
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

        self._job_begin()
        self.set_status("Подготовка…")
        threading.Thread(target=self._conv_worker, args=(src, out), daemon=True).start()

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

    def _conv_worker(self, src, out):
        rc = -1
        duration = self._probe_duration(src)
        cmd = self.build_ffmpeg_cmd(src, out)
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
                    self.root.after(0, self._on_conv_progress, sec, duration, speed)
                elif "=" not in line:  # не служебная строка прогресса — значит ошибка
                    self.root.after(0, self.log_line, line)
            rc = self.proc.wait()
        except FileNotFoundError:
            self.root.after(0, self.log_line, f"Не найден ffmpeg: {FFMPEG}")
        finally:
            self.proc = None
            if rc == 0:
                self.root.after(0, self.log_line, "Сохранено: " + out)
            elif not self.cancelled and os.path.exists(out):
                try:
                    os.remove(out)  # убираем недоделанный файл
                except OSError:
                    pass
            self.root.after(0, self._job_end, rc, "✔ Готово! " + os.path.basename(out))

    def _on_conv_progress(self, sec, duration, speed):
        if duration > 0:
            pct = min(sec / duration * 100, 100)
            self.bar.configure(value=pct)
            text = f"Конвертация: {pct:.1f}%"
        else:
            text = f"Конвертация: {sec:.0f} c обработано"
        if speed:
            text += f"  •  скорость {speed}"
        self.set_status(text)

    # ------------------------------------------------------------ отмена

    def cancel(self):
        p = self.proc
        if not p:
            return
        self.cancelled = True
        # yt-dlp может держать дочерний ffmpeg — убиваем всё дерево процессов
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                       creationflags=subprocess.CREATE_NO_WINDOW,
                       capture_output=True)


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
