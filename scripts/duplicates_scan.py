#!/usr/bin/env python3
"""Bounded, read-only duplicate scan for standard folders on macOS."""

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import safe_cleanup

MIN_SIZE = 1024 * 1024
MAX_ENTRIES = 10_000
MAX_HASH_BYTES = 256 * 1024 * 1024
MAX_SECONDS = 45
DATALESS_FLAG = 0x40000000
REPO_MARKERS = (".git", ".hg", ".svn")
DEPENDENCIES = {"node_modules", "venv", ".venv", "vendor"}
PACKAGES = (".app", ".bundle", ".framework", ".photoslibrary")
MANAGED = {
    "library", "caches", "cache", "application support", "containers",
    "group containers", "cloudstorage", "mobile documents",
    "system volume information", "$recycle.bin", "lost+found",
}


def stamp(st):
    return {name: getattr(st, attr) for name, attr in (
        ("dev", "st_dev"), ("ino", "st_ino"), ("size", "st_size"),
        ("mtime_ns", "st_mtime_ns"), ("ctime_ns", "st_ctime_ns"))}


def roots():
    home = Path.home()
    return [home / name for name in ("Documents", "Downloads", "Desktop", "Library/Caches", "Library/Logs")]


def repo_ancestor(path):
    for parent in (path, *path.parents):
        for marker in REPO_MARKERS:
            try:
                (parent / marker).lstat()
                return True
            except (FileNotFoundError, NotADirectoryError):
                pass
    return False


def has_symlink_ancestor(path):
    return any(stat.S_ISLNK(parent.lstat().st_mode) for parent in (path, *path.parents))


def cloud_placeholder(path, st):
    return path.name.lower().endswith(".icloud") or bool(getattr(st, "st_flags", 0) & DATALESS_FLAG)


def has_cloud_ancestor(path):
    try:
        return any(cloud_placeholder(parent, parent.lstat()) for parent in (path, *path.parents))
    except OSError:
        return True


def cloud_or_unallocated(path, st):
    return (cloud_placeholder(path, st)
            or getattr(st, "st_blocks", 1) == 0)


def excluded_directory(name):
    low = name.lower()
    return name in DEPENDENCIES or low in MANAGED or low.endswith(PACKAGES)


def under(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def valid_file(path, root, state_dir):
    try:
        if (not under(path, root) or under(path, state_dir) or has_symlink_ancestor(path)
                or has_cloud_ancestor(path) or repo_ancestor(path)):
            return None
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_size < MIN_SIZE or cloud_or_unallocated(path, st):
            return None
        if any(excluded_directory(part) for part in path.relative_to(root).parts[:-1]):
            return None
        return st
    except OSError:
        return None


def check_record_file(path):
    try:
        st = path.lstat()
    except FileNotFoundError:
        return None
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1
            or st.st_mode & 0o022 or cloud_placeholder(path, st)):
        raise ValueError("unsafe record file: " + str(path))
    return st


def read_state(path):
    expected = check_record_file(path)
    if expected is None:
        return {}
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "r", encoding="utf-8") as stream:
        opened = os.fstat(stream.fileno())
        if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.getuid() or opened.st_nlink != 1
                or opened.st_mode & 0o022 or stamp(opened) != stamp(expected)):
            raise ValueError("unsafe record file: " + str(path))
        data = json.load(stream)
    if not isinstance(data, dict) or not isinstance(data.get("files", {}), dict):
        raise ValueError("invalid scanner state: " + str(path))
    return data


def write_json(path, value):
    safe_cleanup.prepare_state(path.parent, Path.home())
    check_record_file(path)
    temporary = path.parent / ("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    safe_cleanup.prepare_state(path.parent, Path.home())
    check_record_file(path)
    os.replace(temporary, path)
    dirfd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.fsync(dirfd)
    finally:
        os.close(dirfd)


def is_cache_root(root):
    return root.name in ("Caches", "Logs") and root.parent.name == "Library"


def eligible_file(path, root, state_dir, expected=None):
    st = valid_file(path, root, state_dir)
    if st is None:
        return None
    if is_cache_root(root):
        try:
            safe_cleanup.purpose(path, Path.home())
            helper_expected = None if expected is None else {
                **expected, "mtime_ns": str(expected["mtime_ns"]), "ctime_ns": str(expected["ctime_ns"])}
            st, _ = safe_cleanup.check_source(path, Path.home(), helper_expected)
            if st.st_size < MIN_SIZE:
                return None
            safe_cleanup.check_unused_text(path)
            safe_cleanup.check_source(path, Path.home(), safe_cleanup.signature(st))
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
    return st


def scan(state_dir=None, scan_roots=None, max_entries=MAX_ENTRIES, max_bytes=MAX_HASH_BYTES, max_seconds=MAX_SECONDS):
    started = time.monotonic()
    cwd = Path.cwd()
    default_state = state_dir is None
    state_dir = Path(state_dir) if state_dir is not None else cwd / "work/daily-cleanup"
    state_dir = Path(os.path.abspath(state_dir))
    if default_state and repo_ancestor(cwd):
        raise RuntimeError("default state directory is inside a Git or Mercurial repository; pass external --state-dir")
    state_dir = safe_cleanup.prepare_state(state_dir, Path.home())
    roots_to_scan = [Path(p).absolute() for p in (scan_roots if scan_roots is not None else roots())]
    state_path, report_path = state_dir / "duplicates-state.json", state_dir / "duplicates-report.json"
    state = read_state(state_path)
    previous = state.get("files", {}) if isinstance(state.get("files"), dict) else {}
    cursor_before = state.get("cursor")
    cursor_before = cursor_before if isinstance(cursor_before, int) else None
    # shortcut: cursor assumes entry order stays stable between batches; clear state after broad tree edits.
    cursor = None
    position = 0
    files, candidates, errors, exclusions = {}, defaultdict(list), [], defaultdict(int)
    enumerated = files_enumerated = hash_bytes = 0
    roots_attempted, roots_visited = [], []
    truncation = set()
    stopped = False

    def expired():
        return time.monotonic() - started >= max_seconds

    def consider(path, root):
        st = eligible_file(path, root, state_dir)
        if st is None:
            exclusions["ineligible"] += 1
            return
        key = str(path)
        record = {"stat": stamp(st)}
        cached = previous.get(key)
        if isinstance(cached, dict) and cached.get("stat") == record["stat"] and isinstance(cached.get("sha256"), str):
            record["sha256"] = cached["sha256"]
        files[key] = record
        candidates[st.st_size].append((path, st, record, root))

    for root in roots_to_scan:
        roots_attempted.append(str(root))
        try:
            root_st = root.lstat()
            if stat.S_ISLNK(root_st.st_mode):
                exclusions["symlink_root"] += 1
                continue
            if has_symlink_ancestor(root):
                exclusions["symlink_root"] += 1
                continue
            if has_cloud_ancestor(root):
                exclusions["cloud_placeholder_root"] += 1
                continue
            if not stat.S_ISDIR(root_st.st_mode):
                errors.append({"path": str(root), "error": "root_not_directory"})
                continue
            if repo_ancestor(root):
                exclusions["repository_tree"] += 1
                continue
        except OSError as exc:
            errors.append({"path": str(root), "error": type(exc).__name__})
            continue
        for here, dirs, names in os.walk(root, topdown=True, followlinks=False,
                                         onerror=lambda exc: errors.append({"path": exc.filename, "error": type(exc).__name__})):
            if expired():
                truncation.add("time_limit")
                stopped = True
                break
            here = Path(here)
            if here == root and str(root) not in roots_visited:
                roots_visited.append(str(root))
            if has_cloud_ancestor(here):
                exclusions["cloud_placeholder_directory"] += 1
                dirs[:] = []
                continue
            try:
                if repo_ancestor(here):
                    exclusions["repository_tree"] += 1
                    dirs[:] = []
                    continue
            except OSError as exc:
                errors.append({"path": str(here), "error": type(exc).__name__})
                dirs[:] = []
                continue
            if under(here, state_dir):
                dirs[:] = []
                continue
            kept_dirs = []
            for name in sorted(dirs):
                child = here / name
                if excluded_directory(name) or under(child, state_dir):
                    continue
                try:
                    child_stat = child.lstat()
                    if stat.S_ISLNK(child_stat.st_mode):
                        exclusions["symlink"] += 1
                    elif cloud_placeholder(child, child_stat):
                        exclusions["cloud_placeholder_directory"] += 1
                    else:
                        kept_dirs.append(name)
                except OSError as exc:
                    errors.append({"path": str(child), "error": type(exc).__name__})
            dirs[:] = kept_dirs
            file_names = set(names)
            for name in sorted(dirs + names):
                path = here / name
                position += 1
                if cursor_before is not None and position <= cursor_before:
                    continue
                if expired():
                    truncation.add("time_limit")
                    stopped = True
                    break
                if enumerated >= max_entries:
                    truncation.add("file_limit")
                    stopped = True
                    break
                enumerated += 1
                cursor = position
                if name not in file_names:
                    continue
                files_enumerated += 1
                consider(path, root)
            if stopped:
                break
        if stopped:
            break

    # Revalidate prior batches so duplicates split across bounded runs remain discoverable.
    for key, old in previous.items():
        if expired():
            truncation.add("time_limit")
            break
        if key in files or not isinstance(key, str) or not isinstance(old, dict):
            continue
        path = Path(key)
        root = next((r for r in roots_to_scan if under(path, r)), None)
        if root is None:
            continue
        st = eligible_file(path, root, state_dir, old.get("stat"))
        if st is not None and stamp(st) == old.get("stat") and isinstance(old.get("sha256"), str):
            files[key] = old
            candidates[st.st_size].append((path, st, old, root))

    enumeration_stopped = stopped
    stopped = False
    for entries in candidates.values():
        inodes = {(st.st_dev, st.st_ino) for _, st, _, _ in entries}
        if len(inodes) < 2:
            continue
        for path, original, record, root in entries:
            if record.get("sha256") or original.st_size > max_bytes:
                if original.st_size > max_bytes:
                    exclusions["too_large_for_hash"] += 1
                continue
            if hash_bytes + original.st_size > max_bytes:
                truncation.add("hash_byte_limit")
                stopped = True
                break
            if expired():
                truncation.add("time_limit")
                stopped = True
                break
            digest = hashlib.sha256()
            try:
                if eligible_file(path, root, state_dir, record["stat"]) is None or stamp(path.lstat()) != stamp(original):
                    files.pop(str(path), None)
                    continue
                fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
                try:
                    before = os.fstat(fd)
                    if stamp(before) != stamp(original):
                        files.pop(str(path), None)
                        continue
                    while True:
                        if expired():
                            truncation.add("time_limit")
                            stopped = True
                            break
                        block = os.read(fd, min(1024 * 1024, max_bytes - hash_bytes))
                        if not block:
                            break
                        hash_bytes += len(block)
                        if hash_bytes > max_bytes:
                            truncation.add("hash_byte_limit")
                            stopped = True
                            break
                        digest.update(block)
                    after = os.fstat(fd)
                finally:
                    os.close(fd)
                if stopped:
                    break
                if (eligible_file(path, root, state_dir, record["stat"]) is None
                        or stamp(after) != stamp(original) or stamp(path.lstat()) != stamp(original)):
                    files.pop(str(path), None)
                    continue
                record["sha256"] = digest.hexdigest()
            except OSError as exc:
                errors.append({"path": str(path), "error": type(exc).__name__})
                files.pop(str(path), None)
        if stopped:
            break

    groups = defaultdict(list)
    for path, record in files.items():
        if record.get("sha256"):
            sig = record["stat"]
            groups[(sig["size"], record["sha256"])].append((path, sig))
    duplicates = []
    for (size, sha), members in groups.items():
        unique = {}
        for path, sig in sorted(members):
            unique.setdefault((sig["dev"], sig["ino"]), path)
        if len(unique) > 1:
            duplicates.append({"size": size, "sha256": sha, "paths": sorted(unique.values())})
    duplicates.sort(key=lambda item: (-item["size"], item["paths"]))
    seen = set(state.get("seen_duplicates", []))
    def group_key(group):
        return hashlib.sha256(json.dumps(group, sort_keys=True).encode()).hexdigest()
    new_duplicates = [g for g in duplicates if group_key(g) not in seen]
    state.update(version=1, files=files, cursor=cursor if enumeration_stopped else None,
                 seen_duplicates=sorted(seen | {group_key(g) for g in duplicates}))
    run = {"time": datetime.now(timezone.utc).isoformat(), "roots": roots_visited,
           "roots_attempted": roots_attempted, "scope": "bounded_batch" if enumeration_stopped else "tail",
           "whole_scan_complete": False,
           "entries_enumerated": enumerated, "files_enumerated": files_enumerated,
           "eligible_files_recorded": len(files), "hash_bytes_read": hash_bytes,
           "duplicate_groups": len(duplicates), "new_duplicate_groups": len(new_duplicates),
           "errors": errors, "truncation": sorted(truncation), "excluded_counts": dict(sorted(exclusions.items())),
           "coverage": "partial" if errors or truncation else "bounded_cycle",
           "elapsed_seconds": round(time.monotonic() - started, 3)}
    state.setdefault("runs", []).append(run)
    state["runs"] = state["runs"][-100:]
    write_json(state_path, state)
    write_json(report_path, {"run": run, "duplicates": duplicates, "new_duplicates": new_duplicates})
    return run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", type=Path, default=None)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("this scanner supports macOS only")
    run = scan(state_dir=args.state_dir)
    print(json.dumps(run, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
