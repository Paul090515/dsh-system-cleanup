import importlib.util
import json
import os
import stat
import sys
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "duplicates_scan.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("duplicates_scan", SCRIPT)
scanner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scanner)


class DuplicateScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "Documents"
        self.root.mkdir()
        self.state = self.base / "external-state"

    def tearDown(self):
        self.temp.cleanup()

    def put(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def scan(self, **kwargs):
        return scanner.scan(state_dir=self.state, scan_roots=[self.root], **kwargs)

    def test_same_size_nonduplicate_and_size_mismatch(self):
        self.put("small", b"s" * (scanner.MIN_SIZE - 1))
        self.put("a", b"a" * scanner.MIN_SIZE)
        self.put("b", b"b" * scanner.MIN_SIZE)
        self.put("c", b"a" * (scanner.MIN_SIZE + 1))
        run = self.scan()
        self.assertEqual(run["eligible_files_recorded"], 3)
        report = json.loads((self.state / "duplicates-report.json").read_text())
        self.assertEqual(report["duplicates"], [])

    def test_full_hash_duplicate(self):
        data = b"same" * (scanner.MIN_SIZE // 4)
        self.put("a", data)
        self.put("b", data)
        self.scan()
        report = json.loads((self.state / "duplicates-report.json").read_text())
        self.assertEqual(report["duplicates"][0]["paths"], [str(self.root / "a"), str(self.root / "b")])

    def test_hardlinks_count_once(self):
        first = self.put("a", b"x" * scanner.MIN_SIZE)
        os.link(first, self.root / "b")
        self.scan()
        report = json.loads((self.state / "duplicates-report.json").read_text())
        self.assertEqual(report["duplicates"], [])

    def test_symlink_file_and_ancestor_are_skipped(self):
        real = self.put("real", b"x" * scanner.MIN_SIZE)
        (self.root / "linked").symlink_to(real)
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "inside").symlink_to(self.root, target_is_directory=True)
        run = scanner.scan(state_dir=self.state, scan_roots=[self.root, outside / "inside"])
        self.assertEqual(run["eligible_files_recorded"], 1)
        self.assertGreaterEqual(run["excluded_counts"].get("ineligible", 0), 1)
        self.assertGreaterEqual(run["excluded_counts"].get("symlink_root", 0), 1)

    def test_cloud_flag_is_skipped(self):
        self.put("cloud", b"x" * scanner.MIN_SIZE)
        real_lstat = Path.lstat

        def fake_lstat(path):
            result = real_lstat(path)
            if path.name == "cloud":
                attrs = {name: getattr(result, name) for name in dir(result) if name.startswith("st_")}
                attrs["st_flags"] = scanner.DATALESS_FLAG
                return SimpleNamespace(**attrs)
            return result

        with mock.patch.object(Path, "lstat", fake_lstat):
            self.scan()
        state = json.loads((self.state / "duplicates-state.json").read_text())
        self.assertNotIn(str(self.root / "cloud"), state["files"])

    def test_cloud_ancestor_is_pruned_before_descent(self):
        cloud_dir = self.root / "cloud-dir"
        cloud_dir.mkdir()
        (cloud_dir / "payload").write_bytes(b"x" * scanner.MIN_SIZE)
        real_lstat = Path.lstat

        def fake_lstat(path):
            result = real_lstat(path)
            if path == cloud_dir:
                attrs = {name: getattr(result, name) for name in dir(result) if name.startswith("st_")}
                attrs["st_flags"] = scanner.DATALESS_FLAG
                return SimpleNamespace(**attrs)
            return result

        with mock.patch.object(Path, "lstat", fake_lstat):
            run = self.scan()
        state = json.loads((self.state / "duplicates-state.json").read_text())
        self.assertNotIn(str(cloud_dir / "payload"), state["files"])
        self.assertEqual(run["excluded_counts"].get("cloud_placeholder_directory"), 1)

    def test_repository_root_and_stale_record_revalidation(self):
        first = self.put("inside-repo", b"x" * scanner.MIN_SIZE)
        self.scan()
        repo = self.root / ".git"
        repo.mkdir()
        self.put(".git/other", b"x" * scanner.MIN_SIZE)
        second = self.base / "RepoRoot"
        second.mkdir()
        (second / ".hg").mkdir()
        (second / "payload").write_bytes(b"y" * scanner.MIN_SIZE)
        run = scanner.scan(state_dir=self.state, scan_roots=[self.root, second])
        state = json.loads((self.state / "duplicates-state.json").read_text())
        self.assertNotIn(str(first), state["files"])
        self.assertNotIn(str(self.root / ".git/other"), state["files"])
        self.assertEqual(run["eligible_files_recorded"], 0)

    def test_dependency_and_application_bundle_exclusion(self):
        self.put("node_modules/x", b"x" * scanner.MIN_SIZE)
        self.put("Thing.app/Contents/x", b"x" * scanner.MIN_SIZE)
        self.put("ordinary", b"y" * scanner.MIN_SIZE)
        run = self.scan()
        self.assertEqual(run["eligible_files_recorded"], 1)

    def test_unchanged_hash_is_reused(self):
        data = b"x" * scanner.MIN_SIZE
        self.put("a", data)
        self.put("b", data)
        self.assertEqual(self.scan()["hash_bytes_read"], scanner.MIN_SIZE * 2)
        self.assertEqual(self.scan()["hash_bytes_read"], 0)

    def test_batch_limit_and_cursor_resume(self):
        for name in "abcde":
            self.put(name, name.encode() * scanner.MIN_SIZE)
        first = self.scan(max_entries=2)
        state = json.loads((self.state / "duplicates-state.json").read_text())
        self.assertEqual(first["files_enumerated"], 2)
        self.assertEqual(first["coverage"], "partial")
        self.assertIsNotNone(state["cursor"])
        second = self.scan(max_entries=2)
        self.assertEqual(second["files_enumerated"], 2)
        third = self.scan(max_entries=2)
        self.assertEqual(third["files_enumerated"], 1)
        state = json.loads((self.state / "duplicates-state.json").read_text())
        self.assertIsNone(state["cursor"])
        self.assertEqual(set(state["files"]), {str(self.root / n) for n in "abcde"})

    def test_batch_counts_directories_and_files(self):
        self.put("nested/deeper/file", b"x" * scanner.MIN_SIZE)
        run = self.scan(max_entries=2)
        self.assertEqual(run["entries_enumerated"], 2)
        self.assertEqual(run["coverage"], "partial")

    def test_total_hash_byte_limit(self):
        self.put("a", b"x" * scanner.MIN_SIZE)
        self.put("b", b"x" * scanner.MIN_SIZE)
        run = self.scan(max_bytes=scanner.MIN_SIZE)
        self.assertEqual(run["hash_bytes_read"], scanner.MIN_SIZE)
        self.assertIn("hash_byte_limit", run["truncation"])
        self.assertEqual(run["coverage"], "partial")

    def test_state_directory_is_not_scanned_and_default_repo_write_refused(self):
        self.state.mkdir()
        (self.state / "payload").write_bytes(b"x" * scanner.MIN_SIZE)
        run = scanner.scan(state_dir=self.state, scan_roots=[self.base])
        self.assertNotIn(str(self.state / "payload"), json.loads((self.state / "duplicates-state.json").read_text())["files"])
        repo = self.base / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        with mock.patch.object(Path, "cwd", return_value=repo):
            with self.assertRaisesRegex(RuntimeError, "external --state-dir"):
                scanner.scan(scan_roots=[self.root])
        with self.assertRaisesRegex(ValueError, "repository"):
            scanner.scan(state_dir=repo / "state", scan_roots=[self.root])
        self.assertIn(run["coverage"], ("bounded_cycle", "partial"))

    def test_state_directory_and_record_safety(self):
        real_state = self.base / "real-state"
        link_state = self.base / "linked-state"
        real_state.mkdir()
        link_state.symlink_to(real_state, target_is_directory=True)
        with self.assertRaises((OSError, ValueError)):
            scanner.scan(state_dir=link_state, scan_roots=[self.root])
        linked_parent = self.base / "linked-parent"
        linked_parent.symlink_to(real_state, target_is_directory=True)
        with self.assertRaises((OSError, ValueError)):
            scanner.scan(state_dir=linked_parent / "nested", scan_roots=[self.root])

        self.state.mkdir()
        (self.state / "duplicates-state.json").symlink_to(self.base / "not-a-state")
        with self.assertRaises(ValueError):
            scanner.scan(state_dir=self.state, scan_roots=[self.root])

    def test_group_world_writable_and_foreign_owner_state_dir_rejected(self):
        self.state.mkdir()
        self.state.chmod(0o777)
        with self.assertRaises(ValueError):
            scanner.scan(state_dir=self.state, scan_roots=[self.root])
        self.state.chmod(0o700)
        with mock.patch.object(scanner.os, "getuid", return_value=os.getuid() + 1):
            with self.assertRaises(ValueError):
                scanner.scan(state_dir=self.state, scan_roots=[self.root])

    def test_corrupt_state_fails_closed(self):
        self.state.mkdir()
        state_path = self.state / "duplicates-state.json"
        state_path.write_text("{broken", encoding="utf-8")
        state_path.chmod(0o600)
        with self.assertRaises(json.JSONDecodeError):
            scanner.scan(state_dir=self.state, scan_roots=[self.root])
        self.assertEqual(state_path.read_text(encoding="utf-8"), "{broken")

    def test_cloud_state_record_is_rejected_before_open(self):
        self.state.mkdir()
        state_path = self.state / "duplicates-state.json"
        state_path.write_text("{}", encoding="utf-8")
        state_path.chmod(0o600)
        with mock.patch.object(scanner, "cloud_placeholder", return_value=True), \
             mock.patch.object(scanner.os, "open", side_effect=AssertionError("cloud record opened")):
            with self.assertRaises(ValueError):
                scanner.read_state(state_path)

    def test_temp_collision_fails_closed_and_records_are_private(self):
        self.state.mkdir()
        token = "collision"
        target = self.base / "keep"
        target.write_text("preserve", encoding="utf-8")
        (self.state / (".duplicates-state.json." + token + ".tmp")).symlink_to(target)
        with mock.patch.object(scanner.uuid, "uuid4", return_value=SimpleNamespace(hex=token)):
            with self.assertRaises(FileExistsError):
                scanner.scan(state_dir=self.state, scan_roots=[self.root])
        self.assertEqual(target.read_text(encoding="utf-8"), "preserve")
        (self.state / (".duplicates-state.json." + token + ".tmp")).unlink()
        scanner.scan(state_dir=self.state, scan_roots=[self.root])
        self.assertEqual(stat.S_IMODE((self.state / "duplicates-state.json").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.state / "duplicates-report.json").stat().st_mode), 0o600)

    def test_report_symlink_fails_closed(self):
        self.state.mkdir()
        target = self.base / "report-target"
        target.write_text("preserve", encoding="utf-8")
        (self.state / "duplicates-report.json").symlink_to(target)
        with self.assertRaises(ValueError):
            scanner.scan(state_dir=self.state, scan_roots=[self.root])
        self.assertEqual(target.read_text(encoding="utf-8"), "preserve")

    def test_non_macos_cli_rejects_before_scan(self):
        with mock.patch.object(scanner.sys, "platform", "linux"), \
             mock.patch.object(scanner.sys, "argv", [str(SCRIPT)]), \
             mock.patch.object(scanner, "scan") as scan:
            with self.assertRaises(SystemExit):
                scanner.main()
        scan.assert_not_called()

    def test_cache_unknown_files_never_opened_or_checked_with_lsof(self):
        cache = self.base / "Library" / "Caches"
        cache.mkdir(parents=True)
        (cache / "arbitrary.log").write_bytes(b"x" * scanner.MIN_SIZE)
        real_open = os.open

        def guarded_open(path, *args, **kwargs):
            if str(path).startswith(str(cache)):
                raise AssertionError("cache data must not open")
            return real_open(path, *args, **kwargs)

        with mock.patch("subprocess.run", side_effect=AssertionError("lsof must not run")), \
             mock.patch.object(scanner.os, "open", side_effect=guarded_open):
            run = scanner.scan(state_dir=self.state, scan_roots=[cache])
        self.assertEqual(run["eligible_files_recorded"], 0)
        self.assertEqual(run["hash_bytes_read"], 0)

    def test_cache_cached_hash_is_not_reused_after_lsof_failure(self):
        home = self.base
        logs = home / "Library" / "Logs"
        path = logs / "WorkBuddy" / "renderer.log"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"x" * scanner.MIN_SIZE)
        old = path.stat().st_mtime - 15 * 86400
        os.utime(path, (old, old))
        self.state.mkdir()
        (self.state / "duplicates-state.json").write_text(json.dumps({
            "files": {str(path): {"stat": scanner.stamp(path.lstat()), "sha256": "cached"}},
            "seen_duplicates": [], "runs": []
        }), encoding="utf-8")
        def portable_source_check(candidate, candidate_home, expected=None):
            st = candidate.lstat()
            if expected is not None:
                self.assertEqual(scanner.safe_cleanup.signature(st), expected)
            return st, "test known diagnostic log"

        with mock.patch.object(Path, "home", return_value=home), \
             mock.patch.object(scanner.safe_cleanup, "check_source", side_effect=portable_source_check), \
             mock.patch.object(scanner.safe_cleanup, "check_unused_text", side_effect=subprocess.TimeoutExpired("lsof", 5)) as lsof:
            run = scanner.scan(state_dir=self.state, scan_roots=[logs])
        state = json.loads((self.state / "duplicates-state.json").read_text())
        self.assertNotIn(str(path), state["files"])
        self.assertGreaterEqual(lsof.call_count, 1)
        self.assertEqual(run["hash_bytes_read"], 0)

    def test_run_reports_only_attempted_and_visited_roots_and_scope(self):
        second_root = self.base / "Downloads"
        second_root.mkdir()
        (self.root / "a").write_bytes(b"a" * scanner.MIN_SIZE)
        (self.root / "c").write_bytes(b"c" * scanner.MIN_SIZE)
        (second_root / "b").write_bytes(b"b" * scanner.MIN_SIZE)
        run = scanner.scan(state_dir=self.state, scan_roots=[self.root, second_root], max_entries=1)
        self.assertEqual(run["roots_attempted"], [str(self.root)])
        self.assertEqual(run["roots"], [str(self.root)])
        self.assertEqual(run["scope"], "bounded_batch")
        self.assertFalse(run["whole_scan_complete"])

    def test_read_failures_report_partial_coverage(self):
        self.put("file", b"x" * scanner.MIN_SIZE)

        def denied_walk(root, **kwargs):
            kwargs["onerror"](PermissionError("denied", str(root / "private")))
            return iter(())

        with mock.patch.object(os, "walk", side_effect=denied_walk):
            run = self.scan()
        self.assertEqual(run["coverage"], "partial")
        self.assertEqual(run["errors"][0]["error"], "PermissionError")


if __name__ == "__main__":
    unittest.main()
