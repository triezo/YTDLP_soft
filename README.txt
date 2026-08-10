YT-DLP GUI — video downloader and converter
===========================================

Just double-click "YT-DLP GUI.exe". Nothing to install: Python and yt-dlp
are already inside.

WHAT IT DOES
  Download  — paste a link, pick quality and format (MP4 / MP3 / WAV),
              grab a single video or a whole playlist.
  Convert   — re-encode your own files: change format, compress, resize,
              change frame rate. MOV (DNxHR) is included for editing —
              Premiere and Resolve scrub through it without lag.
  Image     — paste a screenshot from the clipboard (Ctrl+V), flip and
              rotate it, add a note and save it as PNG.

DRAG AND DROP
  Drop things straight onto the window, any tab:
    a link from the browser  -> goes to the Download tab
    a video or audio file    -> goes to the Convert tab
    an image file            -> opens on the Image tab
  Non-PNG images (JPEG, WebP, ...) need ffmpeg to be readable.

ABOUT FFMPEG (important)
  ffmpeg is required to merge high-quality video (1080p and above), to make
  MP3/WAV, and for the whole Convert tab. Without it you still get basic
  medium-quality video — the app warns you about this on startup.

  Any of these works:
   1) Put ffmpeg.exe and ffprobe.exe next to "YT-DLP GUI.exe"
      (or into an "ffmpeg" folder next to it).
   2) Install it from PowerShell:  winget install Gyan.FFmpeg
   3) Download from ffmpeg.org and add it to PATH.

  The app finds ffmpeg in any of those places automatically.

IF DOWNLOADS STOP WORKING
  YouTube keeps changing its protections, so yt-dlp needs regular updates.
  Download a fresh yt-dlp.exe from github.com/yt-dlp/yt-dlp/releases and
  drop it next to this program — it will be used instead of the bundled one.

  If you see "Sign in to confirm you're not a bot", open the Download tab
  and pick your browser in the "Cookies" list.

FIRST LAUNCH
  Windows may show "Windows protected your PC". The app is simply not
  code-signed (a certificate costs money). Click "More info" → "Run anyway".

WHERE FILES GO
  Downloads folder by default. You can change it, and it is remembered.
