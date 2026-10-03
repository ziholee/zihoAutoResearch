"""Public CLI contract checks using temporary projects, never ML commands."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal


REPO = Path(__file__).resolve().parents[1]


class CliHarness(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "target"
        self.project.mkdir()

    def cli(self, *arguments, expected=0, cwd=None):
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            (str(REPO), str(REPO / "src"), env.get("PYTHONPATH", ""))
        )
        result = subprocess.run(
            [sys.executable, "-m", "zar", *arguments],
            cwd=cwd or self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        try:
            output = json.loads(result.stdout, parse_float=Decimal)
        except ValueError:
            self.fail(f"Expected one JSON envelope, got {result.stdout!r}; stderr={result.stderr!r}")
        self.assertEqual(set(output), {"ok", "data", "diagnostics"})
        self.assertIs(output["ok"], expected == 0)
        self.assertIsInstance(output["diagnostics"], list)
        for diagnostic in output["diagnostics"]:
            self.assertEqual(set(diagnostic), {"severity", "code", "path", "message"})
        return output

    def invoke(self, *arguments, expected=0):
        return self.cli(*arguments, "--project", str(self.project), "--json", expected=expected)

    @property
    def stored(self):
        return self.project / ".autoresearch" / "project.json"

    def init(self):
        self.invoke("init")
        return json.loads(self.stored.read_text())

    def write_input(self, document):
        path = self.root / "input.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def ready(self, document):
        document.update(
            objective="Verify the local record tool",
            comparison={"id": "comparison-1", "dataset_ref": "fixture-v1",
                        "split_ref": "split-v1", "metric": "rmse",
                        "direction": "minimize", "evaluation_ref": "evaluation-v1",
                        "min_delta": 0.01},
            environment={"os": "linux", "runtime": "python", "device": "cpu"},
            commands=[{"name": "train", "argv": ["never-execute-this"], "cwd": "."}],
            budget={"max_experiments": 3, "max_run_seconds": 60},
            editable_paths=["train.py"],
            next_action="Inspect preprocessing",
        )
        return document


class CliTests(CliHarness):
    def test_init_preserves_user_files_and_is_idempotent(self):
        for name in ("program.md", "AGENTS.md", "train.py"):
            (self.project / name).write_text(f"original {name}")
        document = self.init()
        self.assertRegex(document["id"], r"^project-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
        self.assertEqual(document["revision"], 1)
        store = self.stored.parent
        for name in ("reviews", "experiments", "submissions", "reports"):
            self.assertTrue((store / name).is_dir())
        self.assertTrue((store / "program.md").is_file())
        before = {p.relative_to(store): p.read_bytes() for p in store.rglob("*") if p.is_file()}
        self.invoke("init")
        after = {p.relative_to(store): p.read_bytes() for p in store.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        for name in ("program.md", "AGENTS.md", "train.py"):
            self.assertEqual((self.project / name).read_text(), f"original {name}")

    def test_partial_initialization_does_not_overwrite(self):
        store = self.stored.parent
        store.mkdir()
        marker = store / "program.md"
        marker.write_text("unfinished user content")
        self.invoke("init", expected=3)
        self.assertEqual(marker.read_text(), "unfinished user content")
        self.assertFalse(self.stored.exists())

    def test_incomplete_status_succeeds_and_check_fails(self):
        self.init()
        status = self.invoke("status")
        self.assertFalse(status["data"]["ready"])
        self.assertIn("objective", json.dumps(status["data"]))
        result = self.invoke("check", expected=3)
        self.assertTrue(result["diagnostics"])

    def test_ready_project_round_trip_does_not_execute_commands(self):
        document = self.ready(self.init())
        self.invoke("project", "set", "--file", str(self.write_input(document)))
        saved = json.loads(self.stored.read_text())
        self.assertEqual(saved["revision"], 2)
        self.assertEqual(saved["created_at"], document["created_at"])
        self.assertEqual(saved["commands"], document["commands"])
        self.invoke("check")
        status = self.invoke("status")
        self.assertTrue(status["data"]["ready"])
        self.assertEqual(status["data"]["missing"], [])
        self.assertIn("Inspect preprocessing", json.dumps(status["data"]))

    def test_user_can_select_each_environment(self):
        document = self.ready(self.init())
        for selected in ("windows", "linux", "macos", "other"):
            with self.subTest(selected=selected):
                document["environment"]["os"] = selected
                self.invoke("project", "set", "--file", str(self.write_input(document)))
                document = json.loads(self.stored.read_text())
                self.assertEqual(document["environment"]["os"], selected)

    def test_invalid_utf8_input_is_reported_without_changing_project(self):
        self.init()
        before = self.stored.read_bytes()
        source = self.root / "encoding.json"
        source.write_bytes(b'{"name": "\xff"}')
        self.invoke("project", "set", "--file", str(source), expected=2)
        self.assertEqual(self.stored.read_bytes(), before)

    def test_stale_revision_preserves_canonical_file(self):
        document = self.init()
        source = self.write_input(document)
        self.invoke("project", "set", "--file", str(source))
        before = self.stored.read_bytes()
        self.invoke("project", "set", "--file", str(source), expected=3)
        self.assertEqual(self.stored.read_bytes(), before)

    def test_immutable_id_and_creation_time(self):
        document = self.init()
        before = self.stored.read_bytes()
        for key, value in (("id", "other-project"), ("created_at", "2000-01-01T00:00:00Z")):
            with self.subTest(key=key):
                changed = {**document, key: value}
                self.invoke("project", "set", "--file", str(self.write_input(changed)), expected=3)
                self.assertEqual(self.stored.read_bytes(), before)

    def test_invalid_json_and_fields_preserve_file(self):
        document = self.init()
        before = self.stored.read_bytes()
        variants = [
            "{", '{"schema_version":1,"schema_version":1}',
            json.dumps({**document, "extra": True}),
            json.dumps({**document, "schema_version": 2}),
            json.dumps({**document, "revision": True}),
            json.dumps({key: value for key, value in document.items() if key != "name"}),
            json.dumps({**document, "budget": {"max_experiments": float("nan"), "max_run_seconds": 1}}),
        ]
        for value in variants:
            with self.subTest(value=value[:100]):
                source = self.root / "invalid.json"
                source.write_text(value)
                self.invoke("project", "set", "--file", str(source), expected=2)
                self.assertEqual(self.stored.read_bytes(), before)

    def test_exact_decimal_survives_storage(self):
        document = self.ready(self.init())
        source = self.write_input(document)
        exact = "0.123456789012345678901234567890123456789"
        source.write_text(source.read_text().replace('"min_delta": 0.01', '"min_delta": ' + exact))
        self.invoke("project", "set", "--file", str(source))
        saved = json.loads(self.stored.read_text(), parse_float=Decimal)
        self.assertEqual(saved["comparison"]["min_delta"], Decimal(exact))

    def test_lock_is_not_removed_on_conflict(self):
        document = self.init()
        lock = self.stored.parent / ".lock"
        lock.write_text("held elsewhere")
        before = self.stored.read_bytes()
        self.invoke("project", "set", "--file", str(self.write_input(document)), expected=4)
        self.assertEqual(lock.read_text(), "held elsewhere")
        self.assertEqual(self.stored.read_bytes(), before)

    def test_unknown_selected_experiment_is_rejected(self):
        document = self.ready(self.init())
        document["selected_experiment_id"] = "missing-experiment"
        before = self.stored.read_bytes()
        self.invoke("project", "set", "--file", str(self.write_input(document)), expected=3)
        self.assertEqual(self.stored.read_bytes(), before)

    def test_global_flags_before_and_between_subcommands(self):
        self.cli("--json", "--project", str(self.project), "init")
        document = self.init()
        source = self.write_input(document)
        self.cli("project", "--json", "--project", str(self.project), "set", "--file", str(source))

    def test_json_argument_errors_are_enveloped(self):
        self.cli("--json", "nonexistent-command", expected=2)
        self.cli("project", "set", "--json", expected=2)

    def test_json_help_is_enveloped(self):
        result = self.cli("--json", "--help")
        self.assertIn("commands", result["data"])

    def test_linked_metadata_is_rejected_without_writing(self):
        self.init()
        external = self.root / "external.json"
        external.write_bytes(self.stored.read_bytes())
        self.stored.unlink()
        self.stored.symlink_to(external)
        before = external.read_bytes()
        self.invoke("status", expected=3)
        self.assertEqual(external.read_bytes(), before)

    def test_default_project_does_not_search_ancestors(self):
        self.init()
        child = self.project / "child"
        child.mkdir()
        self.cli("status", "--json", cwd=child, expected=4)


if __name__ == "__main__":
    unittest.main()
