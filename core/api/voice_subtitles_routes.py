"""HTTP routes for voice subtitles (the Voice Subtitles tab).

The work itself is in core.voice_subtitles; the server attaches the one
VoiceSubtitles instance it builds with the app's settings and library.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException

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
    allowed = {k: payload[k] for k in ("folder", "model", "language", "gpu_recognition") if k in payload}
    try:
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


@router.post("/rebuild")
def rebuild() -> Dict[str, Any]:
    return _svc().rebuild_now()
