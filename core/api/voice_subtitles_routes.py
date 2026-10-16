"""HTTP routes for voice subtitles (the Voice Subtitles tab).

The work itself is in core.voice_subtitles; the server attaches the one
VoiceSubtitles instance it builds with the app's settings and library.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse

from core.voice_subtitles import VoiceSubtitles

router = APIRouter(prefix="/api/voice-subtitles", tags=["voice-subtitles"])
_service: Optional[VoiceSubtitles] = None


def attach(service: VoiceSubtitles) -> None:
    global _service
    _service = service


def _svc() -> VoiceSubtitles:
    if _service is None:  # pragma: no cover - the server attaches it at import
        raise HTTPException(status_code=503, detail="Voice subtitles are not ready yet")
    return _service


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("")
def status() -> Dict[str, Any]:
    return _svc().status()


@router.put("/settings")
def settings(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    allowed = {k: payload[k] for k in ("model", "language", "gpu_recognition") if k in payload}
    try:
        if payload.get("folder"):
            _svc().move_folder(payload["folder"])  # gigabytes: in the background, with its progress
        if allowed:
            _svc().set_config(**allowed)
    except (ValueError, OSError) as exc:
        raise _bad(exc)
    return _svc().status()


@router.post("/install")
def install(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    try:
        job = _svc().install(str(payload.get("what") or ""))
    except ValueError as exc:
        raise _bad(exc)
    return job.public()


@router.post("/remove")
def remove(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    try:
        _svc().remove(str(payload.get("what") or ""))
    except ValueError as exc:
        raise _bad(exc)
    return _svc().status()


@router.post("/rescan")
def rescan() -> Dict[str, Any]:
    _svc().rescan()
    return {"ok": True}


@router.post("/make")
def make(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    try:
        job = _svc().make(str(payload.get("key") or ""), payload.get("language") or None)
    except KeyError:
        raise HTTPException(status_code=404, detail="That voice mod is no longer there; look for voice mods again")
    except ValueError as exc:
        raise _bad(exc)
    return job.public()


@router.post("/make-all")
def make_all(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    try:
        jobs = _svc().make_all(payload.get("language") or None)
    except ValueError as exc:
        raise _bad(exc)
    return {"jobs": [job.public() for job in jobs]}


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: str) -> Dict[str, Any]:
    try:
        _svc().cancel(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="No such job")
    return {"ok": True}


@router.get("/voice-mods/{key}/lines")
def lines(key: str, language: str) -> Dict[str, Any]:
    try:
        return {"lines": _svc().lines(key, language)}
    except KeyError:
        raise HTTPException(status_code=404, detail="No such voice mod")
    except ValueError as exc:
        raise _bad(exc)


@router.put("/voice-mods/{key}/lines")
def edit_line(key: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    text = payload.get("text")
    if text is not None and not isinstance(text, str):
        raise HTTPException(status_code=400, detail="text must be a string or null")
    try:
        return _svc().edit(key, str(payload.get("language") or ""), str(payload.get("line") or ""), text)
    except KeyError:
        raise HTTPException(status_code=404, detail="No such voice mod or line")
    except ValueError as exc:
        raise _bad(exc)


@router.get("/downloads")
def for_downloads(ids: str = "") -> Dict[str, Any]:
    """The voice mods inside these library downloads (ids=1,2,3), with their subtitles."""
    try:
        wanted = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="ids must be numbers separated by commas")
    return _svc().for_downloads(wanted)


@router.get("/hero-icons/{avatar}.png")
def hero_icon(avatar: str) -> FileResponse:
    path = _svc().hero_icon(avatar)
    if path is None:
        raise HTTPException(status_code=404, detail="No picture for that hero")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "max-age=86400"})


@router.post("/reveal")
def reveal(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    try:
        path = _svc().reveal(str(payload.get("key") or ""), str(payload.get("language") or ""),
                             str(payload.get("what") or ""))
    except (KeyError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="That file is not there")
    except ValueError as exc:
        raise _bad(exc)
    return {"path": path}


@router.post("/rebuild")
def rebuild() -> Dict[str, Any]:
    return _svc().rebuild_now()
