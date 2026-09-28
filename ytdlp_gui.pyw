# -*- coding: utf-8 -*-
"""A small GUI for yt-dlp, plus a converter built on ffmpeg.

Run it from the desktop shortcut, from "YT-DLP GUI.bat", or feed this
.pyw to any Python 3 with tkinter: missing libraries are installed on first launch.
"""

import os
import re
import sys

# The built exe can also act AS yt-dlp: it launches itself with this
# flag instead of calling an external program. Check this before anything else.
YTDLP_FLAG = "--__run_ytdlp__"
if len(sys.argv) > 1 and sys.argv[1] == YTDLP_FLAG:
    del sys.argv[1]
    # Without this the bundled yt-dlp writes in the system codepage while the
    # window reads UTF-8, turning non-ASCII titles and paths into garbage.
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


def _console_python():
    """python.exe next to pythonw.exe: child processes need real stdout/stderr,
    and CREATE_NO_WINDOW keeps the console from flashing anyway."""
    exe = sys.executable
    if os.path.basename(exe).lower() == "pythonw.exe":
        cand = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.exists(cand):
            return cand
    return exe


# Third-party modules the source version needs. The exe has them built in;
# a plain Python install does not, so on first launch we fetch them ourselves
# instead of making the user open a terminal and run pip.
DEPS = (("yt_dlp", "yt-dlp", True),         # (module, pip name, required)
        ("tkinterdnd2", "tkinterdnd2", False))


def _missing_deps():
    import importlib.util
    importlib.invalidate_caches()
    return [d for d in DEPS if importlib.util.find_spec(d[0]) is None]


def _pip(args, log):
    """Run pip with our interpreter, bootstrapping pip itself if it is absent."""
    py = _console_python()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    base = [py, "-m", "pip", "install", "--disable-pip-version-check",
            "--no-input"]

    def run(cmd):
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           creationflags=flags)
        log.append((r.stdout or "") + (r.stderr or ""))
        return r.returncode == 0

    if not run([py, "-m", "pip", "--version"]):
        run([py, "-m", "ensurepip", "--upgrade", "--default-pip"])
    # a Python installed for all users sits in Program Files, which is
    # read-only without admin rights: fall back to the per-user folder
    return run(base + args) or run(base + ["--user"] + args)


def ensure_deps():
    """Install missing libraries, with a small window so the first launch
    does not look frozen while pip is working."""
    missing = _missing_deps()
    if not missing:
        return
    import site
    import tkinter as tk
    from tkinter import ttk, messagebox

    log, done = [], threading.Event()
    names = [d[1] for d in missing]

    def work():
        try:
            _pip(names, log)
        except OSError as e:
            log.append(str(e))
        finally:
            done.set()

    win = tk.Tk()
    win.title("YT-DLP GUI")
    win.resizable(False, False)
    frm = ttk.Frame(win, padding=20)
    frm.pack()
    ttk.Label(frm, text="First launch: installing components\n"
                        + ", ".join(names) + "\n\nThis takes up to a minute…",
              justify="center").pack()
    bar = ttk.Progressbar(frm, mode="indeterminate", length=280)
    bar.pack(pady=(12, 0))
    bar.start(12)
    win.update_idletasks()
    win.geometry(f"+{(win.winfo_screenwidth() - win.winfo_width()) // 2}"
                 f"+{(win.winfo_screenheight() - win.winfo_height()) // 3}")
    win.protocol("WM_DELETE_WINDOW", lambda: None)
    threading.Thread(target=work, daemon=True).start()

    def poll():
        if done.is_set():
            win.destroy()
        else:
            win.after(100, poll)
    win.after(100, poll)
    win.mainloop()

    # a --user install may have created the user site folder just now,
    # after Python had already decided not to put it on sys.path
    try:
        user_site = site.getusersitepackages()
        if os.path.isdir(user_site) and user_site not in sys.path:
            site.addsitedir(user_site)
    except (AttributeError, OSError):
        pass

    still = _missing_deps()
    if any(req for _, _, req in still):
        tail = "\n".join("".join(log).strip().splitlines()[-8:])
        messagebox.showerror(
            "YT-DLP GUI",
            "Could not install yt-dlp automatically. Check the internet "
            "connection and restart the program, or run in a terminal:\n\n"
            f"  \"{_console_python()}\" -m pip install yt-dlp tkinterdnd2\n\n"
            + tail)


if __name__ == "__main__" and not getattr(sys, "frozen", False):
    ensure_deps()

# Drag-and-drop from Explorer and browsers. Without the library the app
# still works, just without drag-and-drop.
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
    """Read the clipboard straight from WinAPI (CF_UNICODETEXT)."""
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
    """RGBA bytes (w*h*4) -> PNG."""
    stride = w * 4
    raw = bytearray()
    for y in range(h):
        raw += b"\x00" + rgba[y * stride:(y + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + _png_chunk(b"IEND", b""))


def decode_png(data):
    """PNG -> (rgba, w, h) or None. 8 bits per channel, no interlacing.
    Needed when the clipboard only offers PNG (browsers); a DIB already
    holds raw pixels and is much faster to read."""
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
    for y, line in enumerate(lines):                 # convert to RGBA
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
        else:                                        # palette image
            if not pal:
                return None
            for x in range(w):
                i = line[x] * 3
                out[o + x * 4:o + x * 4 + 3] = pal[i:i + 3]
                out[o + x * 4 + 3] = (trns[line[x]] if trns and line[x] < len(trns)
                                      else 255)
    return bytes(out), w, h


# ---- image transforms: slices only, which is what keeps them fast -------

def _row_mirror(row):
    """Reverse the pixel order inside one RGBA row."""
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
    """Rotate by 90°: a source row becomes a destination column, so we write
    with a stride of the full width — one operation per channel."""
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
    """Flips first, then rotation. Always recomputed from the original so
    repeated clicks never accumulate distortion."""
    if fh:
        rgba = flip_h(rgba, w, h)
    if fv:
        rgba = flip_v(rgba, w, h)
    for _ in range((rot // 90) % 4):
        rgba, w, h = rot90(rgba, w, h, cw=True)
    return rgba, w, h


def shrink_rgba(rgba, w, h, maxw, maxh):
    """Nearest-neighbour downscale for the preview, slices again."""
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
    """CF_DIB from the clipboard -> (rgba, w, h) or None."""
    size, w, h, _planes, bpp, comp = struct.unpack_from("<IiiHHI", d, 0)
    clr_used = struct.unpack_from("<I", d, 32)[0]
    if w <= 0 or bpp not in (24, 32) or comp not in (0, 3):
        return None
    off = size + clr_used * 4
    if comp == 3 and size == 40:
        off += 12  # BITFIELDS masks follow the classic header
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
        out[3::4] = b"\xff" * (w * h)  # screenshots often arrive with a zeroed alpha channel
    return bytes(out), w, h


def clipboard_image():
    """Clipboard image -> (rgba, w, h) or None.

    DIB comes first: its pixels are ready to use, while a PNG would have
    to be unfiltered row by row in Python, which is noticeably slower."""
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

# ---------------------------------------------------------------- paths

FROZEN = getattr(sys, "frozen", False)
APP_DIR = (os.path.dirname(sys.executable) if FROZEN
           else os.path.dirname(os.path.abspath(__file__)))


def res_path(name):
    """A file bundled into the build (next to the script when not frozen)."""
    return os.path.join(getattr(sys, "_MEIPASS", APP_DIR), name)


def _have_ytdlp_module():
    import importlib.util
    return importlib.util.find_spec("yt_dlp") is not None


def find_ytdlp():
    """External yt-dlp.exe if there is one. A copy next to the program wins,
    so a fresh version can be dropped in without rebuilding the exe.
    None means "run the yt_dlp module through ourselves"."""
    local = os.path.join(APP_DIR, "yt-dlp.exe")
    if os.path.exists(local):
        return local
    if not FROZEN and _have_ytdlp_module():
        return None     # the copy in our own Python, the one ensure_deps put there
    exe = shutil.which("yt-dlp")
    if exe:
        return exe
    hits = glob.glob(os.path.expandvars(
        r"%LOCALAPPDATA%\Programs\Python\Python3*\Scripts\yt-dlp.exe"))
    if hits:
        return hits[-1]
    return None if FROZEN else "yt-dlp"   # the frozen build has one bundled


YTDLP = find_ytdlp()


def ytdlp_cmd():
    """How to invoke yt-dlp: an external exe, or ourselves in yt-dlp mode."""
    if YTDLP:
        return [YTDLP]
    if FROZEN:
        return [sys.executable, YTDLP_FLAG]
    return [_console_python(), os.path.abspath(__file__), YTDLP_FLAG]


def find_ffmpeg():
    """Next to the program, then PATH, then the usual install locations."""
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


APP_ID = "triezo.ytdlpgui"          # own icon and taskbar group


def setup_windows_look():
    """Before the window exists: crisp text on scaled displays, and our own
    taskbar icon instead of the generic Python one."""
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
# YouTube increasingly asks to "confirm you're not a bot"; cookies from a
# signed-in browser fix it. Label on the left, --cookies-from-browser name right.
BROWSERS = [('No cookies', ""), ("Firefox", "firefox"), ("Chrome", "chrome"),
            ("Edge", "edge"), ("Opera", "opera"), ("Brave", "brave")]
FPS_LIST = ['Same as source', "60", "50", "30", "25", "24", "15"]
COMPRESSIONS = ['No re-encode', 'Light', 'Medium', 'Strong']
# mp4: x264 CRF (higher = smaller file); mp3: bitrate
CRF = {'Light': "20", 'Medium': "26", 'Strong': "32"}
# DNxHR for editing: every frame stands alone, so Premiere scrubs smoothly
DNX = {'No re-encode': "dnxhr_hq", 'Light': "dnxhr_hq",
       'Medium': "dnxhr_sq", 'Strong': "dnxhr_lb"}
MP3_BR = {'No re-encode': "320k", 'Light': "256k",
          'Medium': "192k", 'Strong': "128k"}

MEDIA_TYPES = [('Video and audio',
                "*.mp4 *.mkv *.webm *.avi *.mov *.wmv *.flv *.ts "
                "*.m4a *.mp3 *.wav *.flac *.opus *.ogg *.aac"),
               ('All files', "*.*")]

# ---------------------------------------------------------------- palette
# Three depth levels: window darker than cards, cards darker than fields.
# That separates blocks visually without drawing boxes around them.

BG = "#141519"          # window background
CARD = "#1c1e24"        # group card
FIELD = "#252831"       # entry, button
FIELD_HI = "#2e323d"    # the same under the cursor
LINE = "#2b2f38"        # separators and borders

FG = "#e9ebef"          # body text
FG_DIM = "#9aa1ad"      # captions
MUTE = "#6d7480"        # least important

ACCENT = "#e5484d"      # brand red, same as the icon
ACCENT_HI = "#f05a5f"
GREEN = "#4cc38a"       # success and the speed graph
GREEN_DIM = "#17342a"   # fill under the graph
WARN = "#e2b53e"

F = "Segoe UI"          # fonts
F_SEMI = "Segoe UI Semibold"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.proc = None
        self.cancelled = False
        self.busy = False            # busy flag known to the main thread
        self._reset_progress()
        self._last_download = None   # path of the last downloaded file
        self._dl_candidate = None    # candidate parsed from yt-dlp output

        root.title('YT-DLP GUI — video downloader & converter')
        ico = res_path("app.ico")
        if os.path.exists(ico):
            try:
                root.iconbitmap(ico)
            except tk.TclError:
                pass
        root.configure(bg=BG)
        # at 125/150% scaling Tk grows the fonts itself (they are in points),
        # but pixel sizes have to be scaled by hand or the window ends up cramped
        self.k = max(root.winfo_fpixels("1i") / 96.0, 1.0)
        w = int(640 * self.k)
        # tall enough for the tabs and the bottom panel, but the window must not
        # run off the screen: scaled laptop displays leave little room
        h = min(int(790 * self.k), root.winfo_screenheight() - int(70 * self.k))
        root.geometry(f"{w}x{h}")
        root.minsize(int(560 * self.k), int(520 * self.k))

        self._styles()
        self._build()
        self._setup_dnd()
        self._center()
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        if not FFMPEG:
            # without ffmpeg there is no merging of 1080p+ and no conversion at all,
            # so whoever runs the build should hear it up front, not after the fact
            self.set_status('ffmpeg not found: basic video only, no conversion. Put ffmpeg.exe next to the program', WARN)

    def _center(self):
        """Open centred on screen instead of wherever Windows decides."""
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = max((self.root.winfo_screenheight() - h) // 2 - 30, 0)
        self.root.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------ ui

    @staticmethod
    def _drop_element(layout, name):
        """Drop an element from a ttk style layout, keeping its children."""
        out = []
        for el, opts in layout:
            opts = dict(opts)
            kids = opts.get("children")
            if kids:
                opts["children"] = App._drop_element(kids, name)
            if el == name:
                out.extend(opts.get("children", []))   # lift its children up a level
            else:
                out.append((el, opts))
        return out

    def _styles(self):
        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=FG, fieldbackground=FIELD,
                    bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
        # The clam theme draws a dotted focus ring around the label, which on
        # click looks like selected text. Drop that element from the tab and
        # button layouts: focus still works, the dotted ring is gone.
        for style, elem in (("TNotebook.Tab", "Notebook.focus"),
                            ("TButton", "Button.focus")):
            try:
                s.layout(style, self._drop_element(s.layout(style), elem))
            except tk.TclError:
                pass
        s.configure("TFrame", background=BG)
        s.configure("Card.TFrame", background=CARD)
        s.configure("TLabel", background=BG, foreground=FG, font=(F, 10))
        # labels inside cards need the card background, or rectangles show up
        s.configure("Card.TLabel", background=CARD, foreground=FG, font=(F, 10))
        s.configure("Section.TLabel", background=CARD, foreground=FG_DIM,
                    font=(F_SEMI, 9))
        s.configure("Hint.TLabel", background=CARD, foreground=MUTE, font=(F, 9))
        s.configure("Muted.TLabel", background=BG, foreground=MUTE, font=(F, 9))
        s.configure("Title.TLabel", background=BG, foreground=FG, font=(F_SEMI, 15))
        s.configure("Ver.TLabel", background=BG, foreground=MUTE, font=(F, 9))

        # buttons: plain, quiet (inside a card) and primary
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
        # a combobox popup is a plain tk Listbox and ignores ttk styling,
        # so it gets coloured through the option database
        self.root.option_add("*TCombobox*Listbox.background", FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "white")
        self.root.option_add("*TCombobox*Listbox.borderWidth", 0)
        self.root.option_add("*TCombobox*Listbox.font", "{Segoe UI} 10")
        s.configure("TNotebook", background=BG, borderwidth=0,
                    tabmargins=(0, 6, 0, 0))
        # selected tab: lighter than the rest, brighter text and an accent bar
        # on top, otherwise it is nearly indistinguishable on a dark theme
        s.configure("TNotebook.Tab", background="#191b21", foreground=MUTE,
                    font=(F_SEMI, 10), padding=(18, 9), borderwidth=2,
                    bordercolor=BG, lightcolor=BG, darkcolor=BG)
        s.map("TNotebook.Tab",
              background=[("selected", CARD), ("active", "#20232a")],
              foreground=[("selected", "#ffffff"), ("active", FG_DIM)],
              lightcolor=[("selected", ACCENT)],
              bordercolor=[("selected", ACCENT)],
              # clam adds its own padding to the selected tab, which makes the
              # labels jump sideways when switching, so we pin it to one value
              padding=[("selected", (18, 9)), ("!selected", (18, 9))])
        for name, color in [("Idle", LINE), ("Run", GREEN), ("Err", ACCENT)]:
            s.configure(f"{name}.Horizontal.TProgressbar", background=color,
                        troughcolor="#1a1c22", borderwidth=0, thickness=6)

    # --- building blocks of the look ----------------------------------

    P = 18                      # inner padding of a card

    def _sec(self, parent, text, top=13):
        """Group heading: dimmer and smaller than body text."""
        ttk.Label(parent, text=text, style="Section.TLabel").pack(
            anchor="w", padx=self.P, pady=(top, 6))

    def _row(self, parent, top=0):
        r = ttk.Frame(parent, style="Card.TFrame")
        r.pack(fill="x", padx=self.P, pady=(top, 0))
        return r

    def _entry(self, parent, var, big=False, hint=""):
        """An entry in a border that lights up in the accent colour on focus.
        hint is grey placeholder text inside the field, which saves the extra
        caption line underneath."""
        wrap = tk.Frame(parent, bg=LINE)
        e = tk.Entry(wrap, textvariable=var, font=(F, 11 if big else 10),
                     bg=FIELD, fg=FG, insertbackground=ACCENT,
                     relief="flat", bd=0, highlightthickness=0)
        e.pack(fill="both", expand=True, padx=1, pady=1, ipady=7 if big else 6)
        e.bind("<FocusIn>", lambda _ev: wrap.configure(bg=ACCENT))
        e.bind("<FocusOut>", lambda _ev: wrap.configure(bg=LINE))
        self._entry_hotkeys(e)
        if hint:
            # the placeholder is a separate label on top of the field, so the
            # variable stays clean and can be read as usual
            lbl = tk.Label(e, text=hint, bg=FIELD, fg=MUTE, font=(F, 9))

            def upd(*_a):
                if var.get() or e is e.focus_displayof():
                    lbl.place_forget()
                else:
                    lbl.place(x=7, rely=0.5, anchor="w")
            var.trace_add("write", upd)
            e.bind("<FocusIn>", lambda _ev: lbl.place_forget(), add="+")
            e.bind("<FocusOut>", lambda _ev: upd(), add="+")
            # the label swallows clicks on the placeholder, so hand focus to the
            # entry, otherwise the field feels dead where the hint text is
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

        # Ctrl+V on the Image tab, outside entries, pastes from the clipboard
        self.root.bind("<Control-KeyPress>", self._root_ctrl)

        # --- shared progress bar, status and log
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

    # ------------------------------------------------------ drag-and-drop

    def _setup_dnd(self):
        """Targets go on widgets rather than the root: the drag-and-drop methods
        only exist on BaseWidget subclasses."""
        self.dnd_ok = False
        if TkinterDnD is None:
            return
        try:
            TkinterDnD._require(self.root)
        except Exception:                     # tkdnd failed to load
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
        """Whatever was dragged in: files or text. What happens next depends on
        the tab that is currently open."""
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
        # a file dropped on the Download tab is more useful sent to Convert
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
        """An image from disk. PNG we decode ourselves; other formats go through
        ffmpeg, since we have no JPEG decoder of our own."""
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

    # ------------------------------------------------------------ graph

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

        for i in range(1, 4):                     # grid
            y = top + (bot - top) * i / 4
            c.create_line(10, y, w - 10, y, fill="#1e222a")

        if not hist:
            c.create_text(w / 2, h / 2, text='speed will appear during download',
                          fill="#454b56", font=(F, 9))
            return

        scale = peak * 1.15 or 1
        # stretch across the full width: with few points the graph still fills
        # the panel instead of hugging the right edge
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

    # ------------------------------------------------------------ tabs

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
        # the registry may still hold a value from the old Russian build,
        # so use it only if it exists in the current list
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

        # --- speed graph spoiler, expands downwards
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
        tk.Frame(f, bg=CARD, height=14).pack(fill="x")   # breathing room at the bottom
        if load_reg("graph") == "1":
            self._toggle_graph()

    def _build_convert_tab(self, f):
        self._sec(f, 'File on your computer', top=14)
        self._src_row = row = self._row(f)
        self.src = tk.StringVar()
        wrap, e = self._entry(row, self.src, hint='path to a file on your computer')
        wrap.pack(side="left", fill="x", expand=True)
        # add="+" is required: without it this binding wipes out the border
        # highlight and the placeholder hiding set up in _entry
        e.bind("<FocusIn>", lambda _e: self._refresh_suggestion(), add="+")
        ttk.Button(row, text='Browse…', command=self.browse_src).pack(side="left", padx=(8, 0))

        # clickable hint: fill in the file that was just downloaded
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
                              justify="left")   # packed only when it has text

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
        self._img_orig = None       # (rgba, w, h) as pasted: the base every edit starts from
        self.img_rgba = None        # current image after transforms
        self.img_w = self.img_h = 0

        # --- flips and rotation
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
        """Ctrl+V/C/X/A bound to physical keys, so they work on any keyboard
        layout, including Cyrillic where tkinter's stock bindings stay silent.
        Plus a right-click context menu."""
        def on_ctrl(ev):
            kc = ev.keycode  # physical key, independent of the keyboard layout
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
        """Paste at the caret, replacing the selection."""
        text = self._get_clip()
        if not text:
            return
        if entry.selection_present():
            entry.delete("sel.first", "sel.last")
        entry.insert("insert", text)

    def _text_hotkeys(self, txt):
        """Ctrl+V/C/X/A for tk.Text on any keyboard layout."""
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
        # Ctrl+V outside entries on the Image tab pastes the picture
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

    # ------------------------------------------------------------ image

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
        """Shared path for both the clipboard and drag-and-drop."""
        self._img_orig = res
        self.rot.set("0°")
        self._flip_h = self._flip_v = False
        for wdg in self.tr_btns + [self.reset_btn]:
            wdg.configure(state="readonly" if wdg is self.rot_box else "normal")
        self._apply_transform()
        self.set_status(f"Loaded {source} — ready to save" if source
                        else 'Image pasted — ready to save')

    # --- flips and rotation -------------------------------------------

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
        """Always recomputed from the original, so clicks never pile up losses."""
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
        """The preview is encoded already downscaled: compressing a full-size PNG
        on every click would take close to a second."""
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
            # the full-size PNG is built only here, not on every rotation
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
        """Show or hide the hint pointing at the last downloaded file."""
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
        self.busy = True  # set synchronously: self.proc only appears later, inside the thread
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

    # ------------------------------------------------------------ download

    def build_cmd(self, url):
        folder = self.folder.get().strip() or DOWNLOADS
        name = self._clean_name(self.fname.get().strip())
        if name:
            name = name.replace("%", "%%")  # so yt-dlp does not read it as a template
            if self.playlist.get():
                name += " %(playlist_index)s"  # otherwise playlist items overwrite each other
            template = name + ".%(ext)s"
        else:
            template = "%(title)s.%(ext)s"
        cmd = ytdlp_cmd() + ["--newline", "--no-mtime",
                             "-o", os.path.join(folder, template),
                             # raw numbers instead of a ready-made line: yt-dlp's ETA is computed
                             # from the current chunk and therefore jumps around
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
            # res means the shorter side of the frame, so vertical videos (9:16)
            # keep their quality; on a tie prefer h264/aac
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
        if self.busy:  # Enter in the link field is not gated by the button state
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
        """Pick the final output path out of yt-dlp's own output. The last match
        in the stream is the real one, after merging or audio extraction."""
        for pat in (r'\[Merger\] Merging formats into "(.+?)"',
                    r'\[ExtractAudio\] Destination: (.+)$',
                    r'\[download\] Destination: (.+)$',
                    r'\[download\] (.+) has already been downloaded'):
            m = re.search(pat, line)
            if m:
                self._dl_candidate = m.group(1).strip()
                return

    # --- our own speed and time-left maths -----------------------------

    @staticmethod
    def _num(s):
        """A number from a progress-template field; 'NA' and junk become None."""
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

    SPEED_POINTS = 120           # graph history width, in samples

    def _reset_progress(self):
        self._dl_streams = 1     # how many files are being fetched (video + audio = 2)
        self._dl_index = 0       # which one is running now
        self._dl_samples = deque()
        self._dl_last = -1.0
        self._pl_index = self._pl_total = 0   # position within the playlist
        self._speed_hist = deque(maxlen=self.SPEED_POINTS)
        self._graph_at = 0.0     # when the graph was last redrawn

    def _new_media_item(self):
        """A new item started: reset the video/audio counter."""
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

        # the byte counter restarted, so the next stream has begun
        if done < self._dl_last:
            self._dl_index += 1
            self._dl_samples.clear()
        self._dl_last = done

        # a ~6 second window smooths fragment bursts without lying after a stall
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
            # the size estimate can be low, so downloaded may exceed total and
            # then there is nothing left to report
            left = max((total or 0) - done, 0)
            if left > 0:
                parts.append('left ' + self._fmt_time(left / rate))
        if self._dl_streams > 1:
            parts.append(f"file {self._dl_index + 1} of {self._dl_streams}")
        if self._pl_total > 1:
            parts.append(f"video {self._pl_index} of {self._pl_total}")
        self.set_status("  •  ".join(parts))

        # graph: collect points, redraw at most four times per second
        if rate:
            self._speed_hist.append(rate)
            if self.graph_open and now - self._graph_at > 0.25:
                self._graph_at = now
                self._draw_graph()

    def _on_line(self, line):
        if line.startswith("@P|"):
            self._on_progress(line[3:].split("|"))
            return
        # playlist position: "Downloading item 2 of 12"
        m = re.search(r"Downloading item (\d+) of (\d+)", line)
        if m:
            self._pl_index, self._pl_total = int(m.group(1)), int(m.group(2))
        # how many files to expect: "Downloading 1 format(s): 137+140" -> two.
        # This line arrives for EVERY item, so the video/audio counter is reset
        # here as well; otherwise a playlist creeps up to "file 5 of 2"
        m = re.search(r"Downloading \d+ format\(s\):\s*(\S+)", line)
        if m:
            self._dl_streams = len(m.group(1).split("+"))
            self._new_media_item()
        # fallback parsing if --progress-template is not supported
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

    # ------------------------------------------------------------ convert

    def build_ffmpeg_cmd(self, src, out):
        fmt = self.cfmt.get()
        comp = self.comp.get()
        cmd = [FFMPEG, "-hide_banner", "-loglevel", "error",
               "-progress", "pipe:1", "-nostats", "-y", "-i", src]
        if fmt in ("mp4", "mov"):
            scale = None
            m = re.match(r"(\d+)", self.cres.get())
            if m:
                # clamp the SHORTER side of the frame: landscape by height, portrait
                # (9:16) by width; never upscale a smaller video, and keep both
                # dimensions even
                h = m.group(1)
                scale = (f"scale="
                         f"'if(gt(iw,ih),-2,2*trunc(min({h}\\,iw)/2))':"
                         f"'if(gt(iw,ih),2*trunc(min({h}\\,ih)/2),-2)'")
            fps = self.cfps.get() if re.match(r"\d", self.cfps.get()) else None
            if fmt == "mov":
                # DNxHR: all-intra, hard constant frame rate and uncompressed audio,
                # which is what editors like most
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
                crf = CRF.get(comp, "20")  # "no re-encode" plus scaling means high quality
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
        while os.path.exists(out):  # never overwrite existing files
            root_, ext_ = os.path.splitext(base)
            out = f"{root_} ({n}){ext_}"
            n += 1

        # the command is built HERE, on the main thread: build_ffmpeg_cmd reads
        # tk variables, and those must not be touched from a worker thread
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
                elif "=" not in line:  # not a progress line, so it must be an error
                    self._ui(self.log_line, line)
            rc = self.proc.wait()
        except FileNotFoundError:
            self._ui(self.log_line, f"ffmpeg not found: {FFMPEG}")
        finally:
            self.proc = None
            if rc == 0:
                self._ui(self.log_line, 'Saved: ' + out)
            elif os.path.exists(out):
                # remove the half-written file on error and on cancel alike:
                # cancelling used to leave a broken file on disk that looked
                # perfectly finished
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

    # ------------------------------------------------------------ update

    @staticmethod
    def _python_for_ytdlp():
        """The interpreter that owns yt-dlp.exe (...\\Scripts\\yt-dlp.exe)."""
        if not YTDLP:
            return _console_python()
        cand = os.path.join(os.path.dirname(os.path.dirname(YTDLP)), "python.exe")
        return cand if os.path.exists(cand) else sys.executable

    def _upd_cmd(self):
        """How to update. pip is not available inside the exe build, so there we
        either update a yt-dlp.exe dropped next to us, or say plainly that we
        cannot."""
        if YTDLP and (FROZEN or YTDLP.lower().endswith("yt-dlp.exe")
                      and not os.path.exists(self._python_for_ytdlp())):
            return [YTDLP, "-U"]
        if FROZEN:
            return None
        cmd = [self._python_for_ytdlp(), "-m", "pip", "install", "-U",
               "--disable-pip-version-check", "yt-dlp"]
        if not YTDLP and self._ytdlp_in_user_site():
            cmd.insert(4, "--user")   # where ensure_deps put it without admin rights
        return cmd

    @staticmethod
    def _ytdlp_in_user_site():
        import importlib.util
        import site
        try:
            spec = importlib.util.find_spec("yt_dlp")
            user = os.path.normcase(os.path.abspath(site.getusersitepackages()))
            return bool(spec and spec.origin) and os.path.normcase(
                os.path.abspath(spec.origin)).startswith(user)
        except (AttributeError, ImportError, OSError, ValueError):
            return False

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

    # ------------------------------------------------------------ cancel

    def _ui(self, fn, *args):
        """Update the UI from a worker thread. Once the window is closed Tk is
        gone, and then we keep quiet instead of spraying tracebacks."""
        try:
            self.root.after(0, fn, *args)
        except (tk.TclError, RuntimeError):
            pass

    def _kill_proc(self):
        """yt-dlp may hold a child ffmpeg, so kill the whole process tree."""
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
        """Without this, closing the window leaves yt-dlp and ffmpeg running in
        the background: child processes do not die with their parent."""
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
