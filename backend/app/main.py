from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

import requests
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(title="PSSM Spiritual Text Work API")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):5173$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

QUALITY_OPTIONS = [
    "COMPACT_SIZE",
    "COMPACT_SIZE_SPEECH",
    "COMPACT_SIZE_MUSIC",
    "COMPACT_MUSIC_INSTRUMENTAL",
    "WHATSAPP",
    "MUSIC_CONCERT",
    "YOUTUBE_UPLOAD",
]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "yt_download_audio.py"
CONFIG_PATH = PROJECT_ROOT / "config" / "media-config.properties"
PROGRESS_PERCENT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)%")
VLC_RUNTIME_DIR = PROJECT_ROOT / "backend" / "runtime"
VLC_SUBTITLE_FILE = VLC_RUNTIME_DIR / "vlc_subtitle.txt"
VLC_UDP_URL = "udp://127.0.0.1:1234?pkt_size=1316"
VLC_PLAYER_HINT_URL = "udp://@127.0.0.1:1234"

VLC_STREAM_STATE: dict[str, object] = {
    "process": None,
    "active": False,
}


def _load_properties(props_path: Path) -> dict[str, str]:
    props: dict[str, str] = {}
    for line in props_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        props[key.strip()] = value.strip()
    return props


def _resolve_property_value(value: str, props: dict[str, str]) -> str:
    if value.startswith("${") and value.endswith("}"):
        key = value[2:-1]
        if key == "user.home":
            return str(Path.home())
        return os.environ.get(key, props.get(key, ""))
    return value


def _load_translator_settings() -> dict[str, str]:
    cfg: dict[str, str] = {}
    if not CONFIG_PATH.exists():
        return cfg

    props = _load_properties(CONFIG_PATH)
    cfg["api_key"] = _resolve_property_value(props.get("translator_api_key", ""), props).strip()
    cfg["region"] = _resolve_property_value(props.get("translator_region", ""), props).strip()
    cfg["endpoint"] = _resolve_property_value(props.get("translator_endpoint", ""), props).strip()
    cfg["from_lang"] = _resolve_property_value(props.get("translator_from", ""), props).strip()
    cfg["timeout_s"] = _resolve_property_value(props.get("translator_timeout_s", "60"), props).strip()

    if not cfg["api_key"]:
        env_var_name = props.get("translator_api_key_env", "").strip() or "AZURE_TRANSLATOR_KEY"
        cfg["api_key"] = os.environ.get(env_var_name, "").strip()

    return cfg


def _resolve_ffmpeg_executable() -> str:
    if CONFIG_PATH.exists():
        props = _load_properties(CONFIG_PATH)
        tools_dir = _resolve_property_value(props.get("tools_dir", ""), props).strip().strip('"')
        if tools_dir:
            candidate = Path(tools_dir) / "ffmpeg.exe"
            if candidate.exists():
                return str(candidate)
    return "ffmpeg"


def _drawtext_safe_path(path: Path) -> str:
    safe = str(path.resolve()).replace("\\", "/")
    return safe.replace(":", "\\:")


def _build_vlc_ffmpeg_command(ffmpeg_bin: str, subtitle_path: Path, stream_url: str) -> list[str]:
    drawtext_path = _drawtext_safe_path(subtitle_path)
    vf_expr = (
        "drawtext="
        f"textfile='{drawtext_path}':"
        "reload=1:"
        "fontcolor=white:"
        "fontsize=34:"
        "box=1:"
        "boxcolor=black@0.55:"
        "x=(w-text_w)/2:"
        "y=h-(text_h*2)-20"
    )

    return [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-re",
        "-f",
        "webm",
        "-i",
        "pipe:0",
        "-vf",
        vf_expr,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-tune",
        "zerolatency",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "44100",
        "-f",
        "mpegts",
        stream_url,
    ]


def _start_vlc_ffmpeg_process() -> subprocess.Popen | None:
    existing = VLC_STREAM_STATE.get("process")
    if isinstance(existing, subprocess.Popen) and existing.poll() is None:
        return existing

    VLC_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    VLC_SUBTITLE_FILE.write_text("Waiting for subtitles...", encoding="utf-8")

    ffmpeg_bin = _resolve_ffmpeg_executable()
    cmd = _build_vlc_ffmpeg_command(ffmpeg_bin, VLC_SUBTITLE_FILE, VLC_UDP_URL)

    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        cwd=str(PROJECT_ROOT),
    )
    VLC_STREAM_STATE["process"] = process
    VLC_STREAM_STATE["active"] = True
    _start_stderr_drain_thread(process)
    return process


def _start_stderr_drain_thread(process: subprocess.Popen) -> None:
    def _drain() -> None:
        if process.stderr is None:
            return
        for raw_line in iter(process.stderr.readline, b""):
            line = raw_line.decode(errors="replace").rstrip()
            if line:
                print(f"[vlc-ffmpeg] {line}", file=sys.stderr)

    threading.Thread(target=_drain, daemon=True).start()


def _stop_vlc_ffmpeg_process() -> None:
    process = VLC_STREAM_STATE.get("process")
    VLC_STREAM_STATE["active"] = False
    if not isinstance(process, subprocess.Popen):
        VLC_STREAM_STATE["process"] = None
        return

    if process.stdin:
        try:
            process.stdin.close()
        except OSError:
            pass
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
    VLC_STREAM_STATE["process"] = None


def line_to_progress(line: str, current: int) -> int:
    progress = current
    if "[1/2]" in line:
        progress = max(progress, 20)
    elif "[2/2]" in line:
        progress = max(progress, 70)
    elif "Validated with ffprobe" in line:
        progress = max(progress, 90)
    elif "Done:" in line:
        progress = 100

    percent_match = PROGRESS_PERCENT_RE.search(line)
    if percent_match:
        raw_percent = float(percent_match.group(1))
        mapped = min(69, int((raw_percent / 100.0) * 65) + 5)
        progress = max(progress, mapped)

    return progress


def sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=True)}\n\n"


@app.get("/api/health")
def health() -> JSONResponse:
    return JSONResponse({"ok": True})


@app.get("/api/qualities")
def qualities() -> JSONResponse:
    return JSONResponse({"qualities": QUALITY_OPTIONS})


@app.post("/api/vlc-stream/start")
def start_vlc_stream() -> JSONResponse:
    try:
        process = _start_vlc_ffmpeg_process()
    except FileNotFoundError:
        return JSONResponse(status_code=500, content={"error": "ffmpeg executable not found."})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": f"Could not start VLC stream relay: {exc}"})

    if process is None:
        return JSONResponse(status_code=500, content={"error": "Could not start VLC stream relay."})

    return JSONResponse(
        {
            "ok": True,
            "vlcUrl": VLC_PLAYER_HINT_URL,
            "status": "relay-started",
        }
    )


@app.post("/api/vlc-stream/stop")
def stop_vlc_stream() -> JSONResponse:
    _stop_vlc_ffmpeg_process()
    return JSONResponse({"ok": True, "status": "relay-stopped"})


@app.post("/api/vlc-stream/subtitle")
def update_vlc_subtitle(payload: dict) -> JSONResponse:
    text = str(payload.get("text", "")).strip()
    VLC_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    VLC_SUBTITLE_FILE.write_text(text or " ", encoding="utf-8")
    return JSONResponse({"ok": True})


@app.websocket("/api/vlc-stream/ws")
async def vlc_stream_ws(websocket: WebSocket):
    await websocket.accept()

    try:
        process = _start_vlc_ffmpeg_process()
    except Exception as exc:  # noqa: BLE001
        await websocket.send_text(f"error: {exc}")
        await websocket.close(code=1011)
        return

    if process is None or process.stdin is None:
        await websocket.send_text("error: relay process unavailable")
        await websocket.close(code=1011)
        return

    try:
        while True:
            chunk = await websocket.receive_bytes()
            if process.poll() is not None:
                await websocket.send_text("error: relay process exited")
                break
            await asyncio.to_thread(process.stdin.write, chunk)
            await asyncio.to_thread(process.stdin.flush)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


@app.get("/api/translate-text")
def translate_text_endpoint(
    text: str = Query(..., min_length=1, max_length=5000),
    source_language: str = Query("auto"),
    target_language: str = Query("hi"),
    target_languages: str = Query(""),
) -> JSONResponse:
    translator_cfg = _load_translator_settings()
    api_key = translator_cfg.get("api_key", "").strip()
    region = translator_cfg.get("region", "").strip()
    endpoint = translator_cfg.get("endpoint", "").strip()

    if not api_key or not region or not endpoint:
        return JSONResponse(
            status_code=500,
            content={"error": "Azure Translator is not configured for this project."},
        )

    try:
        timeout_s = int(translator_cfg.get("timeout_s", "60"))
    except ValueError:
        return JSONResponse(status_code=500, content={"error": "Translator timeout is invalid."})

    target_list = [item.strip() for item in target_languages.split(",") if item.strip()]
    if not target_list:
        target_list = [target_language.strip()]

    target_list = [lang for lang in target_list if lang]
    if not target_list:
        return JSONResponse(status_code=400, content={"error": "No target language selected."})

    headers = {
        "Ocp-Apim-Subscription-Key": api_key,
        "Ocp-Apim-Subscription-Region": region,
        "Content-type": "application/json",
    }
    params: list[tuple[str, str]] = [("api-version", "3.0")]
    for lang in target_list:
        params.append(("to", lang))
    if source_language and source_language.lower() != "auto":
        params.append(("from", source_language))

    try:
        response = requests.post(
            f"{endpoint.rstrip('/')}/translate",
            params=params,
            headers=headers,
            json=[{"text": text}],
            timeout=timeout_s,
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=502, content={"error": f"Translation request failed: {exc}"})

    try:
        payload = response.json()
        translations = payload[0]["translations"]
        translated_map = {
            item["to"]: item["text"]
            for item in translations
            if isinstance(item, dict) and item.get("to") and item.get("text")
        }
        if not translated_map:
            raise KeyError("No translations returned")
    except (ValueError, KeyError, IndexError):
        return JSONResponse(status_code=502, content={"error": "Translator returned an unexpected response."})

    first_lang = target_list[0]
    return JSONResponse(
        {
            "translatedText": translated_map.get(first_lang, ""),
            "translations": translated_map,
            "targets": target_list,
        }
    )


@app.get("/api/download-audio/stream")
async def download_audio_stream(
    video_id: str = Query(..., min_length=11, max_length=200),
    quality: str = Query("COMPACT_SIZE_SPEECH"),
    output_format: str = Query("m4a"),
):
    if quality not in QUALITY_OPTIONS:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid quality '{quality}'."},
        )

    if output_format not in {"m4a", "mp3"}:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid output format. Use m4a or mp3."},
        )

    if not SCRIPT_PATH.exists():
        return JSONResponse(
            status_code=500,
            content={"error": f"Script not found: {SCRIPT_PATH}"},
        )

    if not CONFIG_PATH.exists():
        return JSONResponse(
            status_code=500,
            content={"error": f"Config not found: {CONFIG_PATH}"},
        )

    async def event_generator():
        progress = 0
        yield sse_event(
            {
                "type": "status",
                "message": "Starting audio download pipeline...",
                "progress": progress,
            }
        )

        cmd = [
            sys.executable,
            "-u",
            str(SCRIPT_PATH),
            "--config",
            str(CONFIG_PATH),
            "--video-id",
            video_id,
            "--quality",
            quality,
            "--output-format",
            output_format,
        ]

        env = os.environ.copy()
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                cwd=str(PROJECT_ROOT),
                env=env,
            )
        except Exception as exc:  # noqa: BLE001
            yield sse_event(
                {
                    "type": "failed",
                    "message": f"Failed to start download process: {exc}",
                    "progress": progress,
                }
            )
            return

        assert process.stdout is not None

        while True:
            line = await asyncio.to_thread(process.stdout.readline)
            if not line:
                break

            line = line.rstrip()
            progress = line_to_progress(line, progress)
            event_type = "error" if "ERROR" in line else "log"
            yield sse_event(
                {
                    "type": event_type,
                    "message": line,
                    "progress": progress,
                }
            )

        return_code = await asyncio.to_thread(process.wait)
        if return_code == 0:
            yield sse_event(
                {
                    "type": "done",
                    "message": "Audio download completed successfully.",
                    "progress": 100,
                }
            )
        else:
            yield sse_event(
                {
                    "type": "failed",
                    "message": f"Process failed with exit code {return_code}.",
                    "progress": progress,
                }
            )

    return StreamingResponse(event_generator(), media_type="text/event-stream")
