from __future__ import annotations

import base64
import ctypes
import os
from ctypes import wintypes
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> tuple[DATA_BLOB, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def protect_for_current_user(data: bytes) -> bytes:
    if os.name != "nt":
        return data
    source, keepalive = _blob(data)
    output = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source), "Local Agent Studio", None, None, None, 0, ctypes.byref(output)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)
        del keepalive


def unprotect_for_current_user(data: bytes) -> bytes:
    if os.name != "nt":
        return data
    source, keepalive = _blob(data)
    output = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)
        del keepalive


class SecretBox:
    PREFIX = "enc:v1:"

    def __init__(self, data_dir: Path) -> None:
        key_path = data_dir / "master.key"
        if key_path.exists():
            key = unprotect_for_current_user(key_path.read_bytes())
        else:
            key = AESGCM.generate_key(bit_length=256)
            key_path.write_bytes(protect_for_current_user(key))
            try:
                key_path.chmod(0o600)
            except OSError:
                pass
        self._cipher = AESGCM(key)

    def encrypt(self, value: str) -> str:
        nonce = os.urandom(12)
        payload = nonce + self._cipher.encrypt(nonce, value.encode("utf-8"), None)
        return self.PREFIX + base64.urlsafe_b64encode(payload).decode("ascii")

    def decrypt(self, value: str | None) -> str | None:
        if value is None or not value.startswith(self.PREFIX):
            return value
        payload = base64.urlsafe_b64decode(value[len(self.PREFIX) :])
        return self._cipher.decrypt(payload[:12], payload[12:], None).decode("utf-8")
