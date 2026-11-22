"""Build the test app EXEs.

Two outputs land in exe/:
    Test App.exe            - always asks for administrator
    Test App (no admin).exe - plain launch, for comparison

The payload is exec'd from an encoded blob, so PyInstaller's import graph
never sees it. Every module it imports is listed as a hidden import here,
otherwise the frozen build dies with ModuleNotFoundError at start-up.

    python build_testapp.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "testapp.py"
DIST = ROOT / "exe"

HIDDEN = [
    "ctypes", "ctypes.wintypes", "datetime", "getpass", "mimetypes",
    "platform", "socket", "sqlite3", "subprocess",
    "urllib.error", "urllib.request",
    "base64", "hashlib", "json", "re", "shutil", "struct", "tempfile",
    "threading", "uuid", "zipfile",
]


def build(name: str, work: str, admin: bool) -> None:
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--onefile", "--noconsole", "--name", name,
           "--distpath", str(DIST), "--workpath", work, "--specpath", work]
    if admin:
        cmd.append("--uac-admin")
    for module in HIDDEN:
        cmd += ["--hidden-import", module]
    cmd.append(str(SOURCE))
    print(f"\n=== building {name} ===")
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode:
        raise SystemExit(f"build failed for {name}")


def verify(path: Path, want_admin: bool) -> None:
    data = path.read_bytes()
    has_admin = b"requireAdministrator" in data
    has_invoker = b"asInvoker" in data
    ok = has_admin == want_admin and has_invoker == (not want_admin)
    print(f"  {path.name:<26} {len(data) / 1048576:5.2f} MB  "
          f"admin={has_admin}  asInvoker={has_invoker}  "
          f"{'OK' if ok else 'MISMATCH'}")


def main() -> int:
    if not SOURCE.is_file():
        raise SystemExit(f"missing {SOURCE}")

    build("Test App", "exe_build_test", admin=True)
    build("Test App (no admin)", "exe_build_na", admin=False)

    print("\n=== manifest check ===")
    verify(DIST / "Test App.exe", want_admin=True)
    verify(DIST / "Test App (no admin).exe", want_admin=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
