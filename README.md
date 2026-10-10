# Grab — YouTube downloader backend

Local FastAPI + yt-dlp server for `index.html`.

## Setup (local)

```powershell
cd server
pip install -r requirements.txt
# ffmpeg is required for audio (mp3/m4a/wav) and muxing mp4
winget install ffmpeg        # Windows
# brew install ffmpeg        # macOS
ffmpeg -version              # verify

uvicorn app:app --port 8000 --reload
# health
curl http://127.0.0.1:8000/health
```

Keep it running, then open `index.html` by double-click — the page auto-detects
`http://127.0.0.1:8000` and switches to real downloads. If the server is not
running, the page falls back to demo files.

## Deploy the backend (Render — free)

1. Push this repo to GitHub (see below).
2. On https://dashboard.render.com → New + → Web Service → connect `grab-it` repo.
3. Render auto-reads `render.yaml` (or set manually: Build `pip install -r server/requirements.txt`, Start `uvicorn server.app:app --host 0.0.0.0 --port $PORT`).
4. After deploy, copy your Render URL (e.g. `https://grab-it.onrender.com`) and paste it into
   `index.html` as `REMOTE_BACKEND` (search that string) → commit + push again.
5. GitHub Pages will then hit the live backend. Local still hits `127.0.0.1:8000`.

## GitHub Pages (frontend)

Settings → Pages → Source: Deploy from a branch → Branch `main` / root.
Your site appears at `https://<you>.github.io/grab-it/`.

## API

- `GET /health` — `{ok, ffmpeg}`
- `GET /api/info?url=...` — `{id, kind, title, channel, thumbnail, url}`
- `GET /api/grab?url=...&fmt=mp4-720` — file download (`Content-Disposition: attachment`)

Formats: `mp4-1080` `mp4-720` `mp4-480` `mp4-360` `mp3-320` `mp3-128` `m4a-128` `wav`
Kinds: `video` `shorts` `music` (auto-detected).

## Notes

- CORS is `*` so `file://` and GitHub Pages both work.
- Files cached in OS temp `grab/` — re-grab of same `id+fmt` is instant.
- Respect creators — only save content you have the right to keep.
