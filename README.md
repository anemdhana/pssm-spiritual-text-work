# pssm-spiritual-text-work

Initial setup for a single project with:

- React UI (`frontend/`)
- Python FastAPI backend (`backend/`)
- Local Python scripts in `scripts/`

## Current feature

- Side navigation menu
- Header text: `PSSM Text work utilities`
- Download audio from YouTube `videoId`
- Choose quality preset
- Show progress bar, info messages, error messages
- Live log streaming from backend

## Run backend

```powershell
cd pssm-spiritual-text-work/backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Run frontend

```powershell
cd pssm-spiritual-text-work/frontend
npm install
npm run dev
```

Open: `http://localhost:5173`

## Notes

- Backend uses local config and script paths:
  - `../scripts/yt_download_audio.py`
  - `../config/media-config.properties`
- Default output format is `m4a`.
- Ensure required tools from your existing setup are available (yt-dlp, ffmpeg, ffprobe, etc.).
