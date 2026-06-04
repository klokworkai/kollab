from __future__ import annotations

import base64
import html
import json
import logging
import mimetypes
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("kollab.attachments")

# Permitted MIME type prefixes / exact types
_ALLOWED_MIME_PREFIXES = ("text/",)
_ALLOWED_MIME_EXACT = {
    "application/json",
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/webp",
}
_IMAGE_MIME = {"image/png", "image/jpeg", "image/webp"}

# Staging root — independent of sessions dir
STAGING_ROOT = Path("~/.kollab/staging").expanduser()


@dataclass
class AttachmentMeta:
    upload_id: str
    filename: str
    mime_type: str
    raw_path: Path
    text_path: Path
    size_bytes: int
    text_ok: bool = True      # False if PDF extraction failed
    error: str | None = None  # hard error (unsupported type, extraction failure)

    @property
    def is_image(self) -> bool:
        return self.mime_type in _IMAGE_MIME

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "text_ok": self.text_ok,
            "error": self.error,
        }


# ------------------------------------------------------------------ validation

def is_allowed_mime(mime_type: str) -> bool:
    if mime_type in _ALLOWED_MIME_EXACT:
        return True
    return any(mime_type.startswith(p) for p in _ALLOWED_MIME_PREFIXES)


def guess_mime(filename: str) -> str:
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


# ------------------------------------------------------------------ staging

def staging_dir(upload_id: str) -> Path:
    if not upload_id.replace("-", "").isalnum() or ".." in upload_id or "/" in upload_id:
        raise ValueError(f"Invalid upload_id: {upload_id!r}")
    return STAGING_ROOT / upload_id


def _validate_filename(filename: str) -> None:
    """Raise ValueError if filename contains path separators or traversal components."""
    if not filename or Path(filename).name != filename or "/" in filename or "\\" in filename or ".." in filename:
        raise ValueError(f"Invalid filename: {filename!r}")


def create_upload_id() -> str:
    return uuid.uuid4().hex[:16]


def stage_file(
    upload_id: str,
    data: bytes,
    filename: str,
    mime_type: str,
) -> AttachmentMeta:
    """Store raw bytes, derive text representation. Returns AttachmentMeta."""
    _validate_filename(filename)
    sdir = staging_dir(upload_id)
    sdir.mkdir(parents=True, exist_ok=True)

    # Touch a timestamp sentinel so cleanup knows when this dir was created
    ts_file = sdir / ".created"
    if not ts_file.exists():
        ts_file.write_text(str(time.time()))

    raw_path = sdir / filename
    raw_path.write_bytes(data)

    text_path = sdir / (filename + ".txt")
    text_ok = True
    error: str | None = None

    if mime_type == "application/pdf":
        try:
            import pdfplumber
            with pdfplumber.open(raw_path) as pdf:
                pages = [p.extract_text() or "" for p in pdf.pages]
            text = "\n".join(pages).strip()
            text_path.write_text(text, encoding="utf-8")
        except Exception as exc:
            log.warning("PDF text extraction failed for %s: %s", filename, exc)
            text_path.write_text("", encoding="utf-8")
            text_ok = False
            error = f"PDF text extraction failed: {exc}"
    elif mime_type in _IMAGE_MIME:
        text_path.write_text("", encoding="utf-8")
    else:
        # text/*, application/json, etc — store as-is
        try:
            text_path.write_text(data.decode("utf-8", errors="replace"), encoding="utf-8")
        except Exception as exc:
            text_path.write_text("", encoding="utf-8")
            text_ok = False
            error = str(exc)

    meta = AttachmentMeta(
        upload_id=upload_id,
        filename=filename,
        mime_type=mime_type,
        raw_path=raw_path,
        text_path=text_path,
        size_bytes=len(data),
        text_ok=text_ok,
        error=error,
    )
    # Write sidecar so adopt_staged_attachments can restore exact upload-time metadata.
    sidecar = sdir / (filename + ".meta.json")
    sidecar.write_text(json.dumps({
        "mime_type": mime_type,
        "text_ok": text_ok,
        "error": error,
    }), encoding="utf-8")
    return meta


def delete_staged_file(upload_id: str, filename: str) -> bool:
    _validate_filename(filename)
    sdir = staging_dir(upload_id)
    raw   = sdir / filename
    txt   = sdir / (filename + ".txt")
    meta  = sdir / (filename + ".meta.json")
    deleted = False
    for p in (raw, txt, meta):
        if p.exists():
            p.unlink()
            deleted = True
    return deleted


def delete_staging_dir(upload_id: str) -> None:
    sdir = staging_dir(upload_id)
    if sdir.exists():
        shutil.rmtree(sdir, ignore_errors=True)


def adopt_staged_attachments(staging_id: str, session_id: str, sessions_dir: Path) -> list[AttachmentMeta]:
    """Move staging dir → session attachments dir. Returns list of AttachmentMeta."""
    sdir = staging_dir(staging_id)
    if not sdir.exists():
        return []

    dest = sessions_dir / session_id / "attachments"
    dest.mkdir(parents=True, exist_ok=True)

    metas: list[AttachmentMeta] = []
    for raw_path in sorted(sdir.iterdir()):
        if (raw_path.name.startswith(".")
                or raw_path.suffix == ".txt"
                or raw_path.name.endswith(".meta.json")):
            continue
        txt_path  = sdir / (raw_path.name + ".txt")
        meta_path = sdir / (raw_path.name + ".meta.json")
        dest_raw = dest / raw_path.name
        dest_txt = dest / (raw_path.name + ".txt")
        try:
            shutil.move(str(raw_path), str(dest_raw))
            if txt_path.exists():
                shutil.move(str(txt_path), str(dest_txt))
            else:
                dest_txt.write_text("", encoding="utf-8")
        except Exception as exc:
            log.warning("Failed to move attachment %s: %s", raw_path.name, exc)
            continue

        # Restore upload-time metadata from sidecar; fall back to guessing.
        mime_type = guess_mime(raw_path.name)
        text_ok = True
        error: str | None = None
        if meta_path.exists():
            try:
                sidecar = json.loads(meta_path.read_text(encoding="utf-8"))
                mime_type = sidecar.get("mime_type", mime_type)
                text_ok   = sidecar.get("text_ok", text_ok)
                error     = sidecar.get("error")
            except Exception as exc:
                log.warning("Could not read sidecar for %s: %s", raw_path.name, exc)

        size_bytes = dest_raw.stat().st_size
        metas.append(AttachmentMeta(
            upload_id=staging_id,
            filename=raw_path.name,
            mime_type=mime_type,
            raw_path=dest_raw,
            text_path=dest_txt,
            size_bytes=size_bytes,
            text_ok=text_ok,
            error=error,
        ))

    shutil.rmtree(sdir, ignore_errors=True)
    return metas


def cleanup_stale_staging(max_age_hours: float = 2.0) -> None:
    """Delete staging dirs older than max_age_hours. Called at server startup."""
    if not STAGING_ROOT.exists():
        return
    cutoff = time.time() - max_age_hours * 3600
    for d in STAGING_ROOT.iterdir():
        if not d.is_dir():
            continue
        ts_file = d / ".created"
        try:
            if ts_file.exists():
                created = float(ts_file.read_text())
            else:
                created = d.stat().st_mtime
            if created < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                log.info("Cleaned up stale staging dir %s", d.name)
        except Exception as exc:
            log.warning("Error checking staging dir %s: %s", d, exc)


# ------------------------------------------------------------------ delivery

def build_text_attachment_block(attachments: list[AttachmentMeta]) -> str:
    """Return XML-style attachment blocks for all text-representable files."""
    parts: list[str] = []
    for att in attachments:
        if att.is_image:
            continue
        if not att.text_ok or not att.text_path.exists():
            continue
        content = att.text_path.read_text(encoding="utf-8").strip()
        if content:
            parts.append(f'<attachment name="{html.escape(att.filename, quote=True)}">\n{content}\n</attachment>')
    return "\n\n".join(parts)


def build_image_content_blocks_claude(attachments: list[AttachmentMeta]) -> list[dict]:
    """Return Anthropic-format image content blocks for image attachments."""
    blocks: list[dict] = []
    for att in attachments:
        if not att.is_image or not att.raw_path.exists():
            continue
        data = base64.standard_b64encode(att.raw_path.read_bytes()).decode("ascii")
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": att.mime_type,
                "data": data,
            },
        })
    return blocks


def collect_image_paths(attachments: list[AttachmentMeta]) -> list[Path]:
    """Return raw file paths for image attachments (for Codex -i flags)."""
    return [att.raw_path for att in attachments if att.is_image and att.raw_path.exists()]


# ------------------------------------------------------------------ staging quota helpers

def _is_raw_file(p: Path) -> bool:
    return (not p.name.startswith(".")
            and p.suffix != ".txt"
            and not p.name.endswith(".meta.json"))


def get_staged_count(upload_id: str) -> int:
    sdir = staging_dir(upload_id)
    if not sdir.exists():
        return 0
    return sum(1 for p in sdir.iterdir() if _is_raw_file(p))


def get_staged_total_bytes(upload_id: str) -> int:
    sdir = staging_dir(upload_id)
    if not sdir.exists():
        return 0
    return sum(p.stat().st_size for p in sdir.iterdir() if _is_raw_file(p))
