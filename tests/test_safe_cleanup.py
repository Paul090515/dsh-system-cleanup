import importlib.util
import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "safe_cleanup.py"
SPEC = importlib.util.spec_from_file_location("safe_cleanup", SCRIPT)
cleanup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cleanup)


class SafeCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / "home"
        self.home.mkdir()
        self.state = (self.base / "state").resolve()
        self.state.mkdir()
        self.logs = self.home / "Library" / "Logs"

    def tearDown(self):
        self.temp.cleanup()

    def old_log(self, relative="Claude/mcp.log", data=b"old diagnostic text\n"):
        path = self.logs / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        old = time.time() - cleanup.AGE_SECONDS - 60
        os.utime(path, (old, old))
        return path

    def runner(self, calls=None):
        calls = [] if calls is None else calls

        def run(argv, **kwargs):
            argv = [str(arg) for arg in argv]
            calls.append(argv)
            self.assertIn(argv[0], ("/usr/sbin/lsof", "/usr/bin/file", "/bin/mv"))
            if argv[0] == "/usr/sbin/lsof":
                self.assertEqual(argv[1:3], ["-nP", "--"])
                self.assertTrue(Path(argv[3]).is_relative_to(self.base))
                return SimpleNamespace(returncode=1, stdout=b"", stderr=b"")
            if argv[0] == "/usr/bin/file":
                self.assertEqual(argv[1:3], ["-b", "--mime-type"])
                self.assertTrue(Path(argv[3]).is_relative_to(self.base))
                return SimpleNamespace(returncode=0, stdout=b"text/plain\n", stderr=b"")
            self.assertEqual(argv[1], "-n")
            source, target = Path(argv[2]), Path(argv[3])
            self.assertTrue(source.is_relative_to(self.base))
            self.assertTrue(target.is_relative_to(self.base))
            if not os.path.lexists(target):
                os.rename(source, target)
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

        return run, calls

    def make_plan(self, path=None):
        path = self.old_log() if path is None else path
        runner, _ = self.runner()
        with mock.patch.object(cleanup.subprocess, "run", side_effect=runner):
            result = cleanup.inspect(self.home, self.state)
        self.assertEqual([row["source"] for row in result["entries"]], [str(path)])
        return Path(result["manifest"]), result["entries"][0]

    def test_old_owned_known_log_is_dry_run_with_string_ns_timestamps(self):
        path = self.old_log()
        runner, calls = self.runner()
        with mock.patch.object(cleanup.subprocess, "run", side_effect=runner):
            result = cleanup.inspect(self.home, self.state)
        self.assertEqual(result["moved_count"], 0)
        self.assertEqual(result["actual_freed_bytes"], 0)
        self.assertEqual(len(result["entries"]), 1)
        row = result["entries"][0]
        self.assertEqual(row["source"], str(path))
        self.assertTrue(row["trash_path"].startswith(str(self.home / ".Trash")))
        self.assertIsInstance(row["mtime_ns"], str)
        self.assertIsInstance(row["ctime_ns"], str)
        self.assertTrue(row["mtime_ns"].isdigit())
        self.assertTrue(row["ctime_ns"].isdigit())
        self.assertTrue(path.exists())
        self.assertFalse(any(call[0] == "/bin/mv" for call in calls))

    def test_recent_directory_hardlink_and_symlink_candidates_are_skipped(self):
        recent = self.old_log("Claude/main-window.log")
        os.utime(recent, None)
        directory = self.logs / "Claude" / "claude.ai-web.log"
        directory.mkdir()
        old = time.time() - cleanup.AGE_SECONDS - 120
        os.utime(directory, (old, old))
        linked = self.old_log("WorkBuddy/main.log")
        os.link(linked, self.base / "second-link")
        direct = self.logs / "PaulBot" / "launchd.log"
        direct.parent.mkdir(parents=True)
        direct.symlink_to(linked)
        runner, calls = self.runner()
        with mock.patch.object(cleanup.subprocess, "run", side_effect=runner):
            result = cleanup.inspect(self.home, self.state)
        self.assertEqual(result["entries"], [])
        self.assertEqual(len(calls), 0)
        self.assertTrue(linked.exists())

    def test_unknown_database_and_symlinked_ancestor_are_rejected(self):
        unknown = self.home / "Library" / "Logs" / "unknown.log"
        unknown.parent.mkdir(parents=True)
        unknown.write_text("unknown", encoding="utf-8")
        database = self.home / "Library" / "Logs" / "Claude" / "main.db"
        database.parent.mkdir(parents=True)
        database.write_bytes(b"database")
        with self.assertRaises(ValueError):
            cleanup.check_source(unknown, self.home)
        with self.assertRaises(ValueError):
            cleanup.check_source(database, self.home)

        real = self.base / "real-log-dir"
        real.mkdir()
        target = real / "mcp.log"
        target.write_bytes(b"old")
        old = time.time() - cleanup.AGE_SECONDS - 30
        os.utime(target, (old, old))
        (self.logs / "WorkBuddy").symlink_to(real, target_is_directory=True)
        with self.assertRaises(ValueError):
            cleanup.check_source(self.logs / "WorkBuddy" / "renderer.log", self.home)

    def test_occupied_or_uncertain_lsof_never_mime_sniffs_or_moves(self):
        scenarios = (
            SimpleNamespace(returncode=0, stdout=b"PID\n", stderr=b""),
            SimpleNamespace(returncode=1, stdout=b"", stderr=b"warning"),
            SimpleNamespace(returncode=2, stdout=b"", stderr=b""),
            cleanup.subprocess.CalledProcessError(2, ["lsof"]),
            cleanup.subprocess.TimeoutExpired(["lsof"], 5),
        )
        for outcome in scenarios:
            with self.subTest(outcome=type(outcome).__name__):
                self.temp.cleanup()
                self.setUp()
                try:
                    path = self.old_log()
                    manifest, _ = self.make_plan(path)
                    (self.home / ".Trash").mkdir()
                    calls = []

                    def run(argv, **kwargs):
                        argv = [str(arg) for arg in argv]
                        calls.append(argv)
                        if argv[0] == "/usr/sbin/lsof":
                            if isinstance(outcome, BaseException):
                                raise outcome
                            return outcome
                        self.fail("MIME sniff or move must not run after uncertain lsof")

                    with mock.patch.object(cleanup.subprocess, "run", side_effect=run):
                        summary = cleanup.trash_plan(manifest, self.state, self.home)
                    self.assertEqual(summary["moved_count"], 0)
                    self.assertTrue(path.exists())
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(calls[0][0], "/usr/sbin/lsof")
                finally:
                    self.tearDown()

    def test_non_plain_mime_is_skipped(self):
        path = self.old_log()
        calls = []

        def run(argv, **kwargs):
            argv = [str(arg) for arg in argv]
            calls.append(argv[0])
            if argv[0] == "/usr/sbin/lsof":
                return SimpleNamespace(returncode=1, stdout=b"", stderr=b"")
            return SimpleNamespace(returncode=0, stdout=b"application/pdf\n", stderr=b"")

        with mock.patch.object(cleanup.subprocess, "run", side_effect=run):
            result = cleanup.inspect(self.home, self.state)
        self.assertEqual(result["entries"], [])
        self.assertEqual(calls, ["/usr/sbin/lsof", "/usr/bin/file"])
        self.assertTrue(path.exists())

    def test_missing_lsof_records_error_without_mime_sniff_or_move(self):
        path = self.old_log()
        calls = []

        def run(argv, **kwargs):
            argv = [str(arg) for arg in argv]
            calls.append(argv)
            self.assertEqual(argv[0], "/usr/sbin/lsof")
            raise FileNotFoundError("lsof executable missing")

        with mock.patch.object(cleanup.subprocess, "run", side_effect=run):
            result = cleanup.inspect(self.home, self.state)
        self.assertEqual(result["entries"], [])
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["path"], str(path))
        self.assertIn("lsof executable missing", result["errors"][0]["error"])
        self.assertEqual(len(calls), 1)
        self.assertTrue(path.exists())

    def test_cloud_flagged_codex_directory_is_not_descended(self):
        codex = self.logs / "com.openai.codex"
        cloud_dir = codex / "2026" / "10" / "24"
        cloud_dir.mkdir(parents=True)
        candidate = cloud_dir / "codex-desktop-test.log"
        candidate.write_bytes(b"cloud placeholder fixture\n")
        real_lstat = Path.lstat

        def lstat(path):
            result = real_lstat(path)
            if path == codex / "2026":
                attrs = {name: getattr(result, name) for name in dir(result) if name.startswith("st_")}
                attrs["st_flags"] = 0x40000000
                return SimpleNamespace(**attrs)
            return result

        with mock.patch.object(Path, "lstat", lstat), \
             mock.patch.object(cleanup.subprocess, "run", side_effect=AssertionError("cloud path must not be read")):
            result = cleanup.inspect(self.home, self.state)
        self.assertEqual(result["entries"], [])
        self.assertEqual(result["errors"][0]["path"], str(codex / "2026"))
        self.assertTrue(candidate.exists())

    def test_cli_returns_nonzero_for_uncertain_or_rolled_back_result(self):
        args = ["safe_cleanup.py", "--state-dir", str(self.state), "trash",
                "--manifest", str(self.state / "plan-transaction.json"), "--authorized"]
        for result_status in ("uncertain", "rolled_back"):
            with self.subTest(result_status=result_status):
                output = io.StringIO()
                with mock.patch.object(sys, "argv", args), \
                     mock.patch.object(cleanup.sys, "platform", "darwin"), \
                     mock.patch.object(Path, "home", return_value=self.home), \
                     mock.patch.object(cleanup, "trash_plan", return_value={"results": [{"status": result_status}]}), \
                     redirect_stdout(output):
                    status = cleanup.main()
                self.assertEqual(status, 1)

    def test_changed_source_signature_stops_move(self):
        path = self.old_log()
        manifest, _ = self.make_plan(path)
        path.write_bytes(b"changed content with same path")
        old = time.time() - cleanup.AGE_SECONDS - 60
        os.utime(path, (old, old))
        runner, calls = self.runner()
        with mock.patch.object(cleanup.subprocess, "run", side_effect=runner):
            result = cleanup.trash_plan(manifest, self.state, self.home)
        self.assertEqual(result["moved_count"], 0)
        self.assertTrue(path.exists())
        self.assertFalse(any(call[0] == "/bin/mv" for call in calls))

    def test_source_replaced_at_move_boundary_is_not_moved(self):
        path = self.old_log()
        manifest, row = self.make_plan(path)
        (self.home / ".Trash").mkdir()
        replacement = self.base / "replacement.log"
        replacement.write_bytes(b"unapproved replacement data\n")
        old = time.time() - cleanup.AGE_SECONDS - 60
        os.utime(replacement, (old, old))

        def run(argv, **kwargs):
            argv = [str(arg) for arg in argv]
            if argv[0] == "/usr/sbin/lsof":
                return SimpleNamespace(returncode=1, stdout=b"", stderr=b"")
            if argv[0] == "/usr/bin/file":
                return SimpleNamespace(returncode=0, stdout=b"text/plain\n", stderr=b"")
            self.assertEqual(argv[0], "/bin/mv")
            source, target = Path(argv[2]), Path(argv[3])
            if source == path:
                os.replace(replacement, path)
                os.rename(path, target)
            elif not os.path.lexists(target):
                os.rename(source, target)
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

        with mock.patch.object(cleanup.subprocess, "run", side_effect=run):
            summary = cleanup.trash_plan(manifest, self.state, self.home)
        self.assertTrue(path.exists())
        self.assertEqual(path.read_bytes(), b"unapproved replacement data\n")
        self.assertFalse(Path(row["trash_path"]).exists())
        self.assertEqual(summary["moved_count"], 0)
        self.assertEqual(summary["results"][0]["status"], "rolled_back")

    def test_contested_original_path_leaves_target_and_stops_later_entries(self):
        first = self.old_log("Claude/mcp.log")
        second = self.old_log("WorkBuddy/main.log")
        (self.home / ".Trash").mkdir()
        plan_runner, _ = self.runner()
        with mock.patch.object(cleanup.subprocess, "run", side_effect=plan_runner):
            inspected = cleanup.inspect(self.home, self.state)
        manifest = Path(inspected["manifest"])
        first_row = next(row for row in inspected["entries"] if row["source"] == str(first))
        target = Path(first_row["trash_path"])
        replacement = self.base / "replacement.log"
        replacement.write_bytes(b"unapproved replacement data\n")
        os.utime(replacement, (time.time() - cleanup.AGE_SECONDS - 60,) * 2)
        contender = b"new file at the approved source path\n"
        moved_sources = []

        def run(argv, **kwargs):
            argv = [str(arg) for arg in argv]
            if argv[0] == "/usr/sbin/lsof":
                return SimpleNamespace(returncode=1, stdout=b"", stderr=b"")
            if argv[0] == "/usr/bin/file":
                return SimpleNamespace(returncode=0, stdout=b"text/plain\n", stderr=b"")
            source, destination = Path(argv[2]), Path(argv[3])
            moved_sources.append(source)
            if source == first:
                os.replace(replacement, first)
                os.rename(first, destination)
                first.write_bytes(contender)
            elif not os.path.lexists(destination):
                os.rename(source, destination)
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

        with mock.patch.object(cleanup.subprocess, "run", side_effect=run):
            summary = cleanup.trash_plan(manifest, self.state, self.home)
        self.assertEqual(first.read_bytes(), contender)
        self.assertEqual(target.read_bytes(), b"unapproved replacement data\n")
        self.assertEqual(summary["results"][0]["status"], "uncertain")
        self.assertEqual([row["status"] for row in summary["results"]], ["uncertain"])
        self.assertEqual(summary["moved_count"], 0)
        self.assertTrue(second.exists())
        self.assertEqual(moved_sources, [first])

    def test_inaccessible_symlink_and_cross_device_trash_are_skipped(self):
        for kind in ("inaccessible", "symlink", "cross-device"):
            with self.subTest(kind=kind):
                self.temp.cleanup()
                self.setUp()
                try:
                    path = self.old_log()
                    manifest, _ = self.make_plan(path)
                    trash = self.home / ".Trash"
                    trash.mkdir()
                    patches = []
                    if kind == "inaccessible":
                        real_access = os.access

                        def access(candidate, mode, *args, **kwargs):
                            if Path(candidate) == trash:
                                return False
                            return real_access(candidate, mode, *args, **kwargs)

                        patches.append(mock.patch.object(cleanup.os, "access", side_effect=access))
                    elif kind == "symlink":
                        trash.rmdir()
                        destination = self.base / "external-trash"
                        destination.mkdir()
                        trash.symlink_to(destination, target_is_directory=True)
                    else:
                        actual = trash.stat()
                        fake = SimpleNamespace(st_dev=actual.st_dev + 1, st_ino=actual.st_ino)
                        patches.append(mock.patch.object(cleanup, "check_trash", return_value=fake))
                    runner, calls = self.runner()
                    patches.append(mock.patch.object(cleanup.subprocess, "run", side_effect=runner))
                    with ExitStack() as stack:
                        for patcher in patches:
                            stack.enter_context(patcher)
                        result = cleanup.trash_plan(manifest, self.state, self.home)
                    self.assertEqual(result["moved_count"], 0)
                    self.assertTrue(path.exists())
                    self.assertFalse(any(call[0] == "/bin/mv" for call in calls))
                finally:
                    self.tearDown()

    def test_existing_destination_is_never_overwritten(self):
        path = self.old_log()
        manifest, row = self.make_plan(path)
        target = Path(row["trash_path"])
        target.parent.mkdir()
        target.write_bytes(b"preexisting")
        runner, calls = self.runner()
        with mock.patch.object(cleanup.subprocess, "run", side_effect=runner):
            result = cleanup.trash_plan(manifest, self.state, self.home)
        self.assertEqual(result["moved_count"], 0)
        self.assertEqual(target.read_bytes(), b"preexisting")
        self.assertTrue(path.exists())
        self.assertFalse(any(call[0] == "/bin/mv" for call in calls))

    def test_exact_known_old_log_moves_with_receipt_and_replay_is_rejected(self):
        path = self.old_log()
        manifest, row = self.make_plan(path)
        (self.home / ".Trash").mkdir()
        runner, calls = self.runner()
        with mock.patch.object(cleanup.subprocess, "run", side_effect=runner):
            summary = cleanup.trash_plan(manifest, self.state, self.home)
        destination = Path(row["trash_path"])
        self.assertEqual(summary["moved_count"], 1)
        self.assertEqual(summary["actual_freed_bytes"], 0)
        self.assertFalse(path.exists())
        self.assertEqual(destination.read_bytes(), b"old diagnostic text\n")
        receipt = Path(summary["receipt"])
        records = [json.loads(line) for line in receipt.read_text().splitlines()]
        self.assertIn("moved_verified", [record.get("status") for record in records])
        self.assertEqual(records[-1]["actual_freed_bytes"], 0)
        with self.assertRaises(FileExistsError):
            cleanup.trash_plan(manifest, self.state, self.home)
        self.assertEqual(sum(call[0] == "/bin/mv" for call in calls), 1)

    def test_forged_manifest_source_or_destination_is_rejected(self):
        for field, value in (("source", str(self.base / "outside.log")),
                             ("trash_path", str(self.base / "outside-trash"))):
            with self.subTest(field=field):
                path = self.old_log()
                manifest, _ = self.make_plan(path)
                plan = json.loads(manifest.read_text())
                plan["entries"][0][field] = value
                manifest.write_text(json.dumps(plan), encoding="utf-8")
                with self.assertRaises(ValueError):
                    cleanup.trash_plan(manifest, self.state, self.home)

    def test_repo_runtime_record_path_is_rejected(self):
        repo = self.base / "repository"
        (repo / ".git").mkdir(parents=True)
        with self.assertRaises(ValueError):
            cleanup.prepare_state(repo / "runtime-records", self.home)
        self.assertFalse((repo / "runtime-records").exists())


if __name__ == "__main__":
    unittest.main()
