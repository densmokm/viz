"""The MCP tool surface.

Skipped when the `mcp` package is absent - the rest of the project has no
third-party dependencies and its tests should still run.
"""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401  (puts src/ on sys.path)

try:
    import mcp  # noqa: F401  (availability probe)
    HAVE_MCP = True
except ImportError:
    HAVE_MCP = False


def payload(result):
    for block in result.content:
        if getattr(block, "type", "") == "text":
            return json.loads(block.text)
    raise AssertionError("tool returned no text content")


@unittest.skipUnless(HAVE_MCP, "the mcp package is not installed")
class TestMcpServer(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        os.environ.update({
            "CIM_OPERATOR": "j.parker",
            "CIM_TODAY": "2026-09-14",
            "CIM_STATE_PATH": str(tmp / "directory.json"),
            "CIM_AUDIT_PATH": str(tmp / "audit.jsonl"),
        })
        import importlib
        import cim_agent.server as server_module
        self.mod = importlib.reload(server_module)
        self.server = self.mod.server

    def call(self, name, arguments=None):
        return asyncio.run(self.server.call_tool(name, arguments or {}, None))

    def test_every_tool_is_exposed_with_honest_annotations(self):
        tools = {t.name: t for t in asyncio.run(self.server.list_tools())}
        self.assertEqual(set(tools), {
            "cim_context", "cim_lookup_codes", "cim_find_user", "cim_plan_actions",
            "cim_plan_from_text", "cim_get_plan", "cim_apply_plan", "cim_audit_tail",
        })
        # Exactly one tool may write, and it says so.
        writers = [n for n, t in tools.items() if t.annotations.read_only_hint is False]
        self.assertEqual(writers, ["cim_apply_plan"])
        self.assertTrue(tools["cim_apply_plan"].annotations.destructive_hint)

    def test_context_reports_the_operator_and_catalogue_provenance(self):
        ctx = payload(self.call("cim_context"))
        self.assertEqual(ctx["operator_id"], "j.parker")
        self.assertEqual(ctx["scope_ods"], ["ZZG01", "ZZG02"])
        self.assertTrue(ctx["backend_is_sandbox"])
        self.assertTrue(ctx["catalogue_is_illustrative"])

    def test_plan_then_apply_round_trip(self):
        text = "Daniel Osei's smartcard is locked, UUID 555100200313."
        plan = payload(self.call("cim_plan_actions", {
            "actions": [{
                "action_type": "unlock_smartcard",
                "subject": {"uuid": "555100200313"},
                "params": {},
                "evidence": [{"start": 0, "end": len(text), "text": text}],
            }],
            "source_text": text,
            "source_ref": "INC-1",
        }))
        self.assertEqual(plan["actions"][0]["status"], "ready")
        report = payload(self.call("cim_apply_plan", {
            "plan_id": plan["plan_id"], "confirm": plan["confirmation_token"],
        }))
        self.assertEqual(report["counts"]["applied"], 1)

    def test_evidence_free_action_is_refused_with_usable_guidance(self):
        from mcp.server.mcpserver.exceptions import ToolError
        with self.assertRaises(ToolError) as caught:
            self.call("cim_plan_actions", {"actions": [{
                "action_type": "close_account",
                "subject": {"uuid": "555100200311"},
                "params": {"end_date": "2026-09-30"},
            }]})
        self.assertIn("evidence", str(caught.exception))

    def test_unknown_action_type_names_the_valid_ones(self):
        from mcp.server.mcpserver.exceptions import ToolError
        with self.assertRaises(ToolError) as caught:
            self.call("cim_plan_actions", {"actions": [{
                "action_type": "delete_everything",
                "subject": {"uuid": "555100200311"},
                "evidence": [{"start": 0, "end": 4, "text": "test"}],
            }]})
        self.assertIn("unlock_smartcard", str(caught.exception))

    def test_stale_token_is_refused_with_an_explanation(self):
        from mcp.server.mcpserver.exceptions import ToolError
        text = "unlock it"
        plan = payload(self.call("cim_plan_actions", {
            "actions": [{"action_type": "unlock_smartcard",
                         "subject": {"uuid": "555100200313"}, "params": {},
                         "evidence": [{"start": 0, "end": 9, "text": text}]}],
            "source_text": text,
        }))
        with self.assertRaises(ToolError) as caught:
            self.call("cim_apply_plan", {"plan_id": plan["plan_id"], "confirm": "stale"})
        self.assertIn("Confirmation token", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
