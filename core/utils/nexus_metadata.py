from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

__all__ = [
	"derive_changelogs_from_files",
	"extract_description_text",
	"name_from_unavailable_message",
]


def derive_changelogs_from_files(files_payload: Any) -> Dict[str, Any]:
	"""Create a minimal ``{"changelogs": [...]}`` payload from a files listing."""
	if not files_payload:
		return {}
	if isinstance(files_payload, dict):
		file_list = files_payload.get("files") or []
	elif isinstance(files_payload, list):
		file_list = files_payload
	else:
		return {}
	items: List[Dict[str, Any]] = []
	for f in file_list:
		if not isinstance(f, dict):
			continue
		version = f.get("mod_version") or f.get("version") or f.get("file_version") or ""
		if not version:
			continue
		text = (
			f.get("changelog")
			or f.get("changelog_html")
			or f.get("content")
			or f.get("description")
			or ""
		)
		uploaded_at = f.get("uploaded_time") or f.get("uploaded_at") or f.get("uploaded_timestamp")
		items.append({"mod_version": version, "changelog": text, "uploaded_time": uploaded_at})
	if not items:
		return {}
	return {"changelogs": items}


def extract_description_text(description_payload: Any) -> str:
	"""Best-effort string extractor for aggregated description payloads."""
	if isinstance(description_payload, dict):
		text = description_payload.get("description") or description_payload.get("content")
		if isinstance(text, str):
			return text
		body = description_payload.get("body")
		if isinstance(body, dict):
			text = body.get("description") or body.get("content")
			if isinstance(text, str):
				return text
	return ""


# What Nexus answers for the files of a mod it has hidden:
#   "File currently not available. <title> (Mod ID: 4380) is under moderation"
_UNAVAILABLE_MESSAGE = re.compile(
	r"^(?:File currently not available\.\s*)?(?P<title>.+?) \(Mod ID: (?P<id>\d+)\) is \S",
	re.DOTALL,
)


def name_from_unavailable_message(source: Any, mod_id: int) -> Optional[str]:
	"""A hidden mod's title, read out of the refusal Nexus sends for its files.

	The mod-info endpoint answers 200 for a mod under moderation but leaves the
	name out; the files endpoint answers 403 and, in passing, says what the mod
	is called. For a mod whose name has been lost that sentence is the only
	place left to find it. ``source`` is the message itself or the error
	payload carrying it. Returns None unless the message names this very mod.
	"""
	message: Any = source
	if isinstance(source, dict):
		body = source.get("body")
		message = body.get("message") if isinstance(body, dict) else None
		if not isinstance(message, str):
			message = source.get("message")
	if not isinstance(message, str):
		return None
	match = _UNAVAILABLE_MESSAGE.match(message.strip())
	if not match:
		return None
	try:
		if int(match.group("id")) != int(mod_id):
			return None
	except (TypeError, ValueError):
		return None
	title = match.group("title").strip()
	return title or None
