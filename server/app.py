#!/usr/bin/env python3
"""
Grab — local yt-dlp backend for youtube-downloader.html

Usage:
  pip install -r requirements.txt
  uvicorn app:app --port 8000 --reload

Frontend: open youtube-downloader.html (file:// works — server has CORS *)
"""
import re
import asyncio
import tempfile
import pathlib
import shutil
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

import yt_dlp

app = FastAPI(title="Grab", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Keep tmp files we served for a short while so re-grabs are instant
TMPDIR = pathlib.Path(tempfile.gettempdir()) / "grab"
TMPDIR.mkdir(parents=True, exist_ok=True)

YT_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/|music\.youtube\.com/watch\?v=)([A-Za-z0-9_-]{11})"
)

ALLOWED_FMT = {
    "mp4-1080", "mp4-720", "mp4-480", "mp4-360",
    "mp3-320", "mp3-128", "m4a-128", "wav",
}

def _safe_filename(title: str, fmt: str, ext: str) -> str:
    raw = re.sub(r"[^\w\- ]+", "", title or "").strip()[:42] or "video"
    base = re.sub(r"\s+", "_", raw)
    return f"{base}_{fmt}.{ext}"

def _ext_for(fmt: str) -> str:
    if fmt == "wav": return "wav"
    if fmt.startswith("m4a"): return "m4a"
    if fmt.startswith("mp3"): return "mp3"
    return "mp4"

@app.get("/health")
def health():
    return {"ok": True, "ffmpeg": bool(shutil.which("ffmpeg"))}

@app.get("/api/info")
def info(url: str = Query(..., description="Any YouTube URL")):
    m = YT_RE.search(url)
    if not m:
        raise HTTPException(400, "Not a YouTube link. Try youtube.com/watch?v=..., youtu.be/..., youtube.com/shorts/..., or music.youtube.com/...")
    vid = m.group(1)
    kind = "shorts" if "/shorts/" in url else "music" if "music.youtube.com" in url else "video"
    # Try to resolve real title/thumbnail/uploader via yt-dlp --extract-info (no download)
    title = None
    channel = None
    thumb = f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
    try:
        ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            data = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
            title = data.get("title")
            channel = data.get("uploader") or data.get("channel")
            # best thumb
            thumbs = data.get("thumbnails") or []
            if thumbs:
                # pick largest
                best = max(thumbs, key=lambda t: (t.get("width") or 0) * (t.get("height") or 0) or 0)
                if best.get("url"):
                    thumb = best["url"]
    except Exception as e:
        # fall back to oEmbed-ish title via yt-dlp error; still return id
        pass
    return {
        "id": vid,
        "kind": kind,
        "title": title or f"YouTube — {vid}",
        "channel": channel or "youtube.com",
        "thumbnail": thumb,
        "url": f"https://www.youtube.com/watch?v={vid}",
    }

@app.get("/api/grab")
async def grab(
    url: str = Query(..., description="YouTube URL"),
    fmt: str = Query("mp4-720", description="One of: mp4-1080, mp4-720, mp4-480, mp4-360, mp3-320, mp3-128, m4a-128, wav"),
):
    m = YT_RE.search(url)
    if not m:
        raise HTTPException(400, "Not a YouTube link.")
    if fmt not in ALLOWED_FMT:
        raise HTTPException(400, f"Unknown format {fmt!r}. Allowed: {sorted(ALLOWED_FMT)}")
    vid = m.group(1)
    ext = _ext_for(fmt)

    # Probe title for filename (fast, no download)
    title = vid
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}) as ydl:
            data = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
            title = data.get("title") or vid
    except Exception:
        pass
    out_name = _safe_filename(title, fmt, ext)
    out_path = TMPDIR / out_name
    # If file already exists from a recent grab, serve it directly
    if out_path.exists() and out_path.stat().st_size > 0:
        # re-validate it's the same fmt (name encodes fmt, so safe)
        pass
    else:
        # Build yt-dlp options per format
        tmp_tpl = str(TMPDIR / f"%(title)s.%(ext)s")
        # sanitize title in template is handled by yt-dlp; we rename after
        ydl_opts = {
            "quiet": False,
            "no_warnings": False,
            "noplaylist": True,
            "outtmpl": tmp_tpl,
            "restrictfilenames": False,
            "windowsfilenames": False,
        }
        if fmt.startswith("mp4-"):
            h = fmt.split("-")[1]
            # progressive mp4 (video+audio) preferred; fallback to best
            ydl_opts["format"] = f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/b[height<={h}][ext=mp4]/bv*[height<={h}]+ba/b[height<={h}]"
            ydl_opts["merge_output_format"] = "mp4"
        elif fmt == "mp3-320":
            ydl_opts["format"] = "bestaudio/best"
            ydl_opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "320"}]
        elif fmt == "mp3-128":
            ydl_opts["format"] = "bestaudio/best"
            ydl_opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "128"}]
        elif fmt == "m4a-128":
            ydl_opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"
            ydl_opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a", "preferredquality": "128"}]
        elif fmt == "wav":
            ydl_opts["format"] = "bestaudio/best"
            ydl_opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}]

        # Check ffmpeg for audio & merge
        needs_ffmpeg = fmt in ("mp3-320", "mp3-128", "m4a-128", "wav") or fmt.startswith("mp4-")
        if needs_ffmpeg and not shutil.which("ffmpeg"):
            raise HTTPException(500, "ffmpeg is required for this format but was not found. Install ffmpeg and restart the server (winget install ffmpeg / brew install ffmpeg).")

        def _download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={vid}"])

        try:
            await asyncio.to_thread(_download)
        except yt_dlp.utils.DownloadError as e:
            raise HTTPException(502, f"Download failed: {e}")
        except Exception as e:
            raise HTTPException(500, f"Unexpected error: {e}")

        # yt-dlp wrote to TMPDIR with original title; find newest file matching ext
        # Prefer the file we just produced (mtime)
        candidates = sorted(TMPDIR.glob(f"*.{ext}"), key=lambda p: p.stat().st_mtime, reverse=True)
        # also consider m4a/mp3 produced as postprocessed
        if not candidates and ext in ("mp3", "m4a", "wav"):
            for e2 in ("mp3", "m4a", "wav", "mp4", "webm", "m4a"):
                cand2 = sorted(TMPDIR.glob(f"*.{e2}"), key=lambda p: p.stat().st_mtime, reverse=True)
                if cand2:
                    candidates = cand2
                    ext = e2
                    break
        if not candidates:
            raise HTTPException(500, "Download finished but no output file was produced.")
        newest = candidates[0]
        # Rename to our safe name so the download filename is clean
        try:
            if newest.name != out_name:
                # avoid overwrite race
                target = TMPDIR / out_name
                if target.exists():
                    target.unlink()
                newest.rename(target)
                out_path = target
            else:
                out_path = newest
        except Exception:
            out_path = newest
            out_name = newest.name

    media = {
        "mp4": "video/mp4", "mp3": "audio/mpeg", "m4a": "audio/mp4", "wav": "audio/wav",
    }.get(out_path.suffix.lstrip(".").lower(), "application/octet-stream")

    return FileResponse(
        path=str(out_path),
        media_type=media,
        filename=out_path.name,
        headers={"Cache-Control": "no-store"},
    )
