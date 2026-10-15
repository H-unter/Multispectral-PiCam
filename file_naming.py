"""Validation helpers for user-provided capture filenames."""

import re
from datetime import datetime

_KNOWN_EXTENSIONS = (".jpg", ".jpeg", ".npz", ".npy")
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename_stem(value: str | None, default_prefix: str) -> str:
    """Return a safe filename stem without path components or known extensions."""
    stem = (value or "").strip()
    for extension in _KNOWN_EXTENSIONS:
        if stem.lower().endswith(extension):
            stem = stem[: -len(extension)].rstrip()
            break
    stem = _SAFE_FILENAME.sub("_", stem).strip("._-")
    if not stem:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = f"{default_prefix}_{timestamp}"
    return stem
