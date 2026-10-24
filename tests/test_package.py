import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        for name in ("SKILL.md", "agents", "references", "scripts", "tests", "lib",
                     "package.json", "cordis.patch.yml", "README.md", "CHANGELOG.md", "LICENSE"):
            target = self.repo / name
            if (ROOT / name).is_dir():
                shutil.copytree(ROOT / name, target, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copyfile(ROOT / name, target)
        (self.repo / "package.json").write_text(json.dumps({"version": "2.0.1"}))
        (self.repo / ".gitignore").write_text("dist/\n")
        self.git("init", "-q")
        self.commit()

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)

    def commit(self):
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-qm", "fixture")

    def package(self):
        return subprocess.run(["bash", "scripts/package.sh"], cwd=self.repo,
                              env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                              capture_output=True, text=True)

    def test_zip_contains_skill_resources_but_no_local_or_unlisted_records(self):
        for name in ("work/daily-cleanup/plan-private.json", ".env", "scripts/receipt-private.jsonl"):
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("private fixture only")
        self.commit()
        result = self.package()
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(self.repo / "dist/system-cleanup-v2.0.1.zip") as archive:
            names = archive.namelist()
            self.assertIn("system-cleanup/SKILL.md", names)
            self.assertIn("system-cleanup/scripts/safe_cleanup.py", names)
            self.assertFalse(any("private" in name or name.endswith(".env") or "/.git/" in name for name in names))
            self.assertIsNone(archive.testzip())

    def test_uncommitted_tracked_changes_are_rejected(self):
        (self.repo / "SKILL.md").write_text("uncommitted fixture")
        result = self.package()
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.repo / "dist").exists())
