from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
from typing import Dict, Mapping, Optional


DEFAULT_SESSION_PATH = Path.home() / ".morai_login" / "session.dat"


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def save_session(session: Mapping[str, str], path: Path = DEFAULT_SESSION_PATH) -> None:
    required = ("email", "access_token", "refresh_token", "user_id", "product_uid")
    data = {key: str(session.get(key, "")).strip() for key in required}
    if any(not data[key] for key in required):
        raise ValueError("Remembered login session is incomplete")
    encrypted = _protect(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    target = path.expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(encrypted)


def load_session(path: Path = DEFAULT_SESSION_PATH) -> Optional[Dict[str, str]]:
    target = path.expanduser()
    if not target.is_file():
        return None
    try:
        data = json.loads(_unprotect(target.read_bytes()).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    required = ("email", "access_token", "refresh_token", "user_id", "product_uid")
    session = {key: str(data.get(key, "")).strip() for key in required}
    return session if all(session.values()) else None


def clear_session(path: Path = DEFAULT_SESSION_PATH) -> None:
    try:
        path.expanduser().unlink()
    except FileNotFoundError:
        pass


def _protect(data: bytes) -> bytes:
    return _crypt(data, protect=True)


def _unprotect(data: bytes) -> bytes:
    return _crypt(data, protect=False)


def _crypt(data: bytes, protect: bool) -> bytes:
    if os.name != "nt":
        raise ValueError("Remembered login requires Windows DPAPI")
    buffer = ctypes.create_string_buffer(data)
    input_blob = _DataBlob(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)),
    )
    output_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if protect:
        succeeded = crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(output_blob),
        )
    else:
        succeeded = crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(output_blob),
        )
    if not succeeded:
        raise ValueError(f"Windows DPAPI failed with error {ctypes.get_last_error()}")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)
