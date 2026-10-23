#!/usr/bin/env python3
"""macOS-only, exact-manifest diagnostic-log cleanup. No permanent deletion."""

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


AGE_SECONDS = 14 * 86400
REPO_MARKERS = (".git", ".hg", ".svn")
KNOWN_LOGS = {
    "Claude/mcp.log", "Claude/main-window.log", "Claude/claude.ai-web.log",
    "DSH Desktop/harness.log", "WorkBuddy/renderer.log", "WorkBuddy/main.log",
    "PaulBot/launchd.log",
}
UPDATER_LOGS = {
    "com.microsoft.VSCode.ShipIt/ShipIt_stdout.log",
    "com.anthropic.claudefordesktop.ShipIt/ShipIt_stdout.log",
    "com.anthropic.claudefordesktop.ShipIt/ShipIt_stderr.log",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def no_links(path):
    require(path.is_absolute() and path.resolve() == path, "symlink or noncanonical path")
    for ancestor in (path, *path.parents):
        if ancestor.exists():
            require(not (ancestor.lstat().st_flags & 0x40000000), "cloud placeholder ancestor")


def no_repository(path):
    require(not any((p / m).exists() or (p / m).is_symlink()
                    for p in (path, *path.parents) for m in REPO_MARKERS),
            "repository paths are excluded")


def prepare_state(path, home):
    path = Path(os.path.abspath(path))
    no_links(path)
    no_repository(path)
    require(not any(path.is_relative_to(home / p) for p in
                    ("Library/Caches", "Library/Logs", ".Trash")), "unsafe record directory")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    s = path.lstat()
    require(stat.S_ISDIR(s.st_mode) and s.st_uid == os.getuid()
            and not (s.st_mode & 0o022), "unsafe record directory owner or permissions")
    return path


def signature(s):
    return {"dev": s.st_dev, "ino": s.st_ino, "size": s.st_size,
            "mtime_ns": str(s.st_mtime_ns), "ctime_ns": str(s.st_ctime_ns)}


def purpose(path, home):
    logs, caches = home / "Library/Logs", home / "Library/Caches"
    if path.is_relative_to(logs):
        relative = path.relative_to(logs).as_posix()
        if relative in KNOWN_LOGS or re.fullmatch(
                r"com[.]openai[.]codex/[0-9]{4}/[0-9]{2}/[0-9]{2}/codex-desktop-[A-Za-z0-9-]+[.]log",
                relative):
            return "Known application diagnostic plain-text log, individually unchanged for at least 14 days."
    if path.is_relative_to(caches) and path.relative_to(caches).as_posix() in UPDATER_LOGS:
        return "Known updater stdout/stderr diagnostic plain-text log, individually unchanged for at least 14 days."
    raise ValueError("unknown or protected file purpose")


def check_source(path, home, expected=None):
    reason = purpose(path, home)
    no_links(path)
    no_repository(path.parent)
    s = path.lstat()
    require(stat.S_ISREG(s.st_mode) and s.st_uid == os.getuid()
            and s.st_nlink == 1 and s.st_flags == 0, "protected file type, owner, link or flags")
    require(s.st_size > 0 and s.st_blocks > 0 and s.st_mtime <= time.time() - AGE_SECONDS,
            "empty, unallocated or recent file")
    require(os.access(path, os.R_OK) and os.access(path.parent, os.R_OK | os.W_OK | os.X_OK),
            "unreadable file or unwritable parent")
    if expected is not None:
        require(signature(s) == {k: expected[k] for k in signature(s)}, "file identity changed")
    return s, reason


def check_unused_text(path):
    # Check occupancy before even MIME-sniffing the file; uncertainty means skip.
    probe = subprocess.run(["/usr/sbin/lsof", "-nP", "--", str(path)],
                           capture_output=True, timeout=5)
    require(probe.returncode == 1 and not probe.stdout and not probe.stderr,
            "file in use or incomplete lsof check")
    mime = subprocess.run(["/usr/bin/file", "-b", "--mime-type", str(path)],
                          capture_output=True, timeout=5)
    require(mime.returncode == 0 and not mime.stderr and mime.stdout.strip() == b"text/plain",
            "not confirmed plain text")


def write_new(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def inspect(home, state):
    logs = home / "Library/Logs"
    paths = [logs / p for p in sorted(KNOWN_LOGS)]
    paths += [home / "Library/Caches" / p for p in sorted(UPDATER_LOGS)]
    errors = []
    codex = logs / "com.openai.codex"
    if codex.exists():
        try:
            no_links(codex)
            no_repository(codex)
            for directory, dirs, names in os.walk(codex, followlinks=False,
                    onerror=lambda e: errors.append({"path": e.filename, "error": str(e)})):
                kept = []
                for name in sorted(dirs):
                    child = Path(directory) / name
                    try:
                        no_links(child)
                        no_repository(child)
                        kept.append(name)
                    except (OSError, ValueError) as error:
                        errors.append({"path": str(child), "error": str(error)})
                dirs[:] = kept
                if any((Path(directory) / m).exists() for m in REPO_MARKERS):
                    dirs[:] = []
                    continue
                paths += [Path(directory) / n for n in sorted(names)
                          if re.fullmatch(r"codex-desktop-[A-Za-z0-9-]+[.]log", n)]
        except (OSError, ValueError) as error:
            errors.append({"path": str(codex), "error": str(error)})
    transaction = uuid.uuid4().hex
    entries, skipped = [], {}
    for path in paths:
        try:
            s, reason = check_source(path, home)
            check_unused_text(path)
            check_source(path, home, signature(s))
            entries.append({"source": str(path), **signature(s), "reason": reason,
                "trash_path": str(home / ".Trash" / ("system-cleanup-" + transaction + "-" + path.name))})
        except FileNotFoundError as error:
            if path.exists():
                errors.append({"path": str(path), "error": str(error)})
            continue
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            key = type(error).__name__ + ": " + str(error)
            skipped[key] = skipped.get(key, 0) + 1
    plan = {"schema": 1, "transaction": transaction, "created_at": now(), "home": str(home),
            "scope": "Known diagnostic logs only; unknown cache contents excluded.",
            "entries": entries, "skipped_counts": skipped, "errors": errors}
    output = state / ("plan-" + transaction + ".json")
    write_new(output, plan)
    return {"manifest": str(output), **plan, "moved_count": 0, "actual_freed_bytes": 0}


def load_plan(path, state, home):
    no_links(path)
    require(path.parent == state, "manifest must be inside the selected record directory")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "r") as handle:
        s = os.fstat(handle.fileno())
        require(stat.S_ISREG(s.st_mode) and s.st_uid == os.getuid() and s.st_nlink == 1
                and not (s.st_mode & 0o022) and s.st_size <= 1024 * 1024, "unsafe manifest")
        plan = json.load(handle)
        os.fsync(handle.fileno())
    require(plan["schema"] == 1 and plan["home"] == str(home), "wrong manifest scope")
    require(re.fullmatch(r"[0-9a-f]{32}", plan["transaction"]) is not None, "invalid transaction")
    require(path.name == "plan-" + plan["transaction"] + ".json", "wrong manifest name")
    require(isinstance(plan["entries"], list) and len(plan["entries"]) <= 1000, "invalid entry list")
    sources = [row["source"] for row in plan["entries"]]
    require(len(sources) == len(set(sources)), "duplicate manifest source")
    for row in plan["entries"]:
        source = Path(row["source"])
        purpose(source, home)
        require(source.is_absolute(), "manifest source must be absolute")
        require(Path(row["trash_path"]) == home / ".Trash" /
                ("system-cleanup-" + plan["transaction"] + "-" + source.name),
                "manifest destination outside exact Trash path")
        require(all(type(row[k]) is int for k in ("dev", "ino", "size"))
                and row["size"] > 0 and all(isinstance(row[k], str) and row[k].isdigit()
                for k in ("mtime_ns", "ctime_ns")), "invalid identity fields")
    return plan


def check_trash(home):
    trash = home / ".Trash"
    no_links(trash)
    s = trash.lstat()
    require(stat.S_ISDIR(s.st_mode) and s.st_uid == os.getuid()
            and os.access(trash, os.R_OK | os.W_OK | os.X_OK), "Trash is not safely accessible")
    fd = os.open(trash, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.listdir(fd)
        opened = os.fstat(fd)
        require((opened.st_dev, opened.st_ino) == (s.st_dev, s.st_ino), "Trash changed")
    finally:
        os.close(fd)
    return s


def verified_destination(row):
    source, target = Path(row["source"]), Path(row["trash_path"])
    no_links(target)
    dest = target.lstat()
    require(stat.S_ISREG(dest.st_mode) and
            (dest.st_dev, dest.st_ino, dest.st_size, str(dest.st_mtime_ns)) ==
            (row["dev"], row["ino"], row["size"], row["mtime_ns"]), "Trash identity mismatch")
    try:
        remaining = source.lstat()
    except FileNotFoundError:
        remaining = None
    require(remaining is None or (remaining.st_dev, remaining.st_ino) != (dest.st_dev, dest.st_ino),
            "source identity still present")


class RolledBack(ValueError):
    pass


class MoveUncertain(ValueError):
    pass


def rollback_unverified(row, home, parent, trash, record):
    source, target = Path(row["source"]), Path(row["trash_path"])
    no_links(source.parent)
    no_links(target)
    parent_now, trash_now = source.parent.stat(), check_trash(home)
    require((parent_now.st_dev, parent_now.st_ino) == (parent.st_dev, parent.st_ino)
            and (trash_now.st_dev, trash_now.st_ino) == (trash.st_dev, trash.st_ino),
            "cannot safely roll back changed parents")
    actual = target.lstat()
    require(stat.S_ISREG(actual.st_mode) and actual.st_uid == os.getuid()
            and actual.st_nlink == 1 and actual.st_flags == 0 and actual.st_dev == parent.st_dev
            and not os.path.lexists(source), "cannot safely roll back changed source or target")
    require(record is not None, "rollback requires a durable recovery journal")
    record({**row, "status": "rollback_planned", "time": now(),
            "unexpected_identity": signature(actual)})
    require(not os.path.lexists(source) and signature(target.lstat()) == signature(actual),
            "rollback identity changed")
    result = subprocess.run(["/bin/mv", "-n", str(target), str(source)], capture_output=True, timeout=10)
    require(result.returncode == 0 and not result.stderr, "rollback failed or uncertain")
    restored = source.lstat()
    require(not os.path.lexists(target) and
            (restored.st_dev, restored.st_ino, restored.st_size, restored.st_mtime_ns) ==
            (actual.st_dev, actual.st_ino, actual.st_size, actual.st_mtime_ns), "rollback not verified")


def move_one(row, transaction, home, record=None):
    source, target = Path(row["source"]), Path(row["trash_path"])
    require(target == home / ".Trash" / ("system-cleanup-" + transaction + "-" + source.name),
            "unexpected Trash destination")
    s, _ = check_source(source, home, row)
    trash = check_trash(home)
    require(s.st_dev == trash.st_dev, "cross-volume moves are excluded")
    require(not os.path.lexists(target), "Trash destination already exists")
    parent = source.parent.stat()
    check_unused_text(source)
    check_source(source, home, row)
    trash_after = check_trash(home)
    parent_after = source.parent.stat()
    require((trash.st_dev, trash.st_ino) == (trash_after.st_dev, trash_after.st_ino)
            and (parent.st_dev, parent.st_ino) == (parent_after.st_dev, parent_after.st_ino)
            and not os.path.lexists(target), "parent or destination changed")
    # A path-based rename cannot lock out other applications; verify and safely undo a raced replacement.
    try:
        result = subprocess.run(["/bin/mv", "-n", str(source), str(target)], capture_output=True, timeout=10)
        require(result.returncode == 0 and not result.stderr, "move failed or uncertain")
        verified_destination(row)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        try:
            verified_destination(row)
            return
        except (OSError, ValueError):
            pass
        if not os.path.lexists(source) and os.path.lexists(target):
            try:
                rollback_unverified(row, home, parent, trash, record)
            except (OSError, ValueError, subprocess.SubprocessError) as rollback_error:
                raise MoveUncertain("move identity mismatch; rollback unsafe or unverified: " + str(rollback_error)) from error
            raise RolledBack("source changed at move boundary; this move was safely rolled back") from error
        if os.path.lexists(target) or not os.path.lexists(source):
            raise MoveUncertain("move identity mismatch; source or target changed concurrently") from error
        raise


def trash_plan(path, state, home):
    plan = load_plan(path, state, home)
    receipt = state / ("receipt-" + plan["transaction"] + ".jsonl")
    fd = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    results = []
    with os.fdopen(fd, "w") as handle:
        def record(data):
            handle.write(json.dumps(data, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        for row in plan["entries"]:
            record({**row, "status": "planned", "time": now()})
            result = {**row, "status": "skipped"}
            try:
                move_one(row, plan["transaction"], home, record)
                result.update(status="moved_verified", moved_at=now())
            except RolledBack as error:
                result.update(status="rolled_back", error=str(error), restored_at=now())
            except MoveUncertain as error:
                result.update(status="uncertain", error=str(error))
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                result["error"] = type(error).__name__ + ": " + str(error)
                # A timed-out move may already have completed; reconcile only the recorded identities.
                try:
                    verified_destination(row)
                    result.update(status="moved_verified", moved_at=now())
                except (OSError, ValueError):
                    if not os.path.lexists(row["source"]):
                        result["status"] = "uncertain"
            record(result)
            results.append(result)
            if result["status"] in ("uncertain", "rolled_back"):
                break
        moved = [r for r in results if r["status"] == "moved_verified"]
        summary = {"manifest": str(path), "receipt": str(receipt), "results": results,
                   "moved_count": len(moved), "moved_bytes_to_trash": sum(r["size"] for r in moved),
                   "actual_freed_bytes": 0, "space_note": "Same-volume Trash rename; no Trash emptying."}
        record({"status": "summary", "time": now(), **summary})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=Path.cwd() / "work/daily-cleanup")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inspect", help="record individually checked candidates; never move files")
    trash = sub.add_parser("trash", help="recheck and move only an authorized exact manifest")
    trash.add_argument("--manifest", type=Path, required=True)
    trash.add_argument("--authorized", action="store_true", required=True,
                       help="use only after actual user authorization, including unchanged recurring scope")
    args = parser.parse_args()
    try:
        require(sys.platform == "darwin", "this version supports macOS only")
        home = Path.home()
        no_links(home)
        state = prepare_state(args.state_dir, home)
        result = inspect(home, state) if args.command == "inspect" else trash_plan(
            Path(os.path.abspath(args.manifest)), state, home)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if any(row["status"] in ("uncertain", "rolled_back") for row in result.get("results", [])):
            return 1
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"error": type(error).__name__ + ": " + str(error)}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
