"""Tests for single-agent local harness upgrades (P0/P1/P2).

Covers dynamic setup-driven system prompts, consolidated tools with legacy aliases,
thinking-continuity preservation, non-destructive observation masking, resilient
apply_patch, runaway thinking guard, leaked tool-call recovery, memory replace/remove,
incremental CodeIndex, multi-language RepoIndex, shell failure extraction, expanded
read-only command safety, and prompt KV-cache hit telemetry.
"""
from __future__ import annotations

import copy
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness.agent import Agent, Status, build_registry
from harness.app_operations import session_detail
from harness.application import ApplicationService
from harness.code_index import CodeIndex
from harness.config import Config, load_config
from harness.hardware import Hardware
from harness.llm import AssistantResult, ReasoningLoopGuard
from harness.memory import MemoryStore
from harness.prompts import build_system_prompt
from harness.repo_index import RepoIndex
from harness.safety import Risk, SafetyPolicy
from harness.session import Session
from harness.tools.base import AgentContext
from harness.tools.fs import ApplyPatchTool, ReadFileTool, validate_syntax_pre_write
from harness.tools.shell import _extract_failure_lines, is_read_only_command


def _make_cfg(root: Path) -> Config:
    data = copy.deepcopy(load_config().data)
    data["paths"] = {
        "runtime_dir": "runtime",
        "sessions_dir": "sessions",
        "models_dir": "models",
    }
    return Config(data, root=root)


class DynamicSystemPromptTests(unittest.TestCase):
    def test_prompt_uses_live_model_gpu_and_language_without_hardcoded_values(self):
        import harness.prompts as prompts_mod
        tmp = Path(tempfile.mkdtemp(prefix="marvin-prompt-"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        cfg = _make_cfg(tmp)
        cfg.data["default_model"] = "q4"
        cfg.data["language"] = "en"
        fake_hw = Hardware(
            cpu_name="TestCPU", physical_cores=8, logical_cpus=16,
            performance_cpus=(), physical_cpus=(),
            ram_total=32 * 1024**3, ram_available=16 * 1024**3,
            gpu_name="NVIDIA GeForce RTX 4070 Ti", gpu_uuid="u", driver="580.0",
            vram_total=16 * 1024**3, vram_available=14 * 1024**3, compute_cap="8.9",
        )
        old_cache = prompts_mod._HARDWARE_ENV_CACHE
        prompts_mod._HARDWARE_ENV_CACHE = None
        try:
            with patch("harness.hardware.detect_hardware", return_value=fake_hw):
                prompt_en = build_system_prompt("agent", cfg, tmp, "development")
                cfg.data["language"] = "cs"
                prompt_cs = build_system_prompt("agent", cfg, tmp, "development")
        finally:
            prompts_mod._HARDWARE_ENV_CACHE = old_cache

        self.assertIn("RTX 4070 Ti (16 GB VRAM)", prompt_en)
        self.assertIn("32 GB RAM", prompt_en)
        self.assertIn("Q4", prompt_en)
        self.assertIn("interface is set to English", prompt_en)
        self.assertNotIn("RTX 5090", prompt_en)
        self.assertIn("interface is set to Czech", prompt_cs)


class ToolConsolidationTests(unittest.TestCase):
    def test_consolidated_schemas_shrink_catalog_and_preserve_legacy_aliases(self):
        tmp = Path(tempfile.mkdtemp(prefix="marvin-tools-"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        cfg = _make_cfg(tmp)
        cfg.data["_semantic_search"] = False
        reg_off = build_registry("agent", "development", cfg)
        self.assertNotIn("semantic_search", reg_off.names())
        self.assertIsNotNone(reg_off.get("semantic_search"))

        cfg.data["_semantic_search"] = True
        reg_on = build_registry("agent", "development", cfg)
        self.assertIn("semantic_search", reg_on.names())

        # Consolidated tools present; legacy names callable via aliases.
        for name in ("browser_inspect", "browser_interact", "task_plan", "memory", "manage_context", "project_info"):
            self.assertIn(name, reg_off.names())
        for alias in ("browser_open", "browser_click", "set_task_plan", "save_memory", "pin_context_file", "repo_overview"):
            self.assertNotIn(alias, reg_off.names())
            self.assertIsNotNone(reg_off.get(alias))

        # Browser interact risk classification: read-only actions are SAFE, mutating actions are WRITE.
        interact = reg_off.get("browser_interact")
        self.assertEqual(interact.risk_for({"action": "hover"}), Risk.SAFE)
        self.assertEqual(interact.risk_for({"action": "scroll"}), Risk.SAFE)
        self.assertEqual(interact.risk_for({"action": "click"}), Risk.WRITE)
        self.assertEqual(interact.risk_for({"action": "fill"}), Risk.WRITE)


class ObservationMaskingTests(unittest.TestCase):
    def test_observation_masking_preserves_originals_and_avoids_lossy_summarization(self):
        tmp = Path(tempfile.mkdtemp(prefix="marvin-mask-"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        cfg = _make_cfg(tmp)
        session = Session(cfg, system_prompt="SYS", workspace=str(tmp))
        session.add("user", "Inspect the large project files")

        # Add 16 bulky tool results + 1 protected memory result (TOOL_OUTPUTS_KEPT=8 -> 8 masked).
        for i in range(16):
            cid = f"c{i}"
            session.add("assistant", "", tool_calls=[{
                "id": cid, "type": "function",
                "function": {"name": "read_file", "arguments": f'{{"path":"file_{i}.py"}}'},
            }])
            session.add("tool", f"E:/proj/file_{i}.py (lines 1-200 of 200)\n" + ("x = 1\n" * 900),
                        tool_call_id=cid, name="read_file")
        # Also add an older memory tool result that must NEVER be masked.
        session.messages.insert(2, {
            "role": "tool", "name": "memory", "tool_call_id": "cmem",
            "id": "mem-1", "content": "CRITICAL MEMORY " + ("fact\n" * 600),
        })

        count, saving = session.prunable_tool_outputs(keep_recent=8, min_chars=2400)
        self.assertEqual(count, 8)
        self.assertGreater(saving, 5000)

        agent = Agent(cfg, None, session, build_registry("agent", "development", cfg), SafetyPolicy("auto"))
        before_tokens = agent.estimate_context_tokens()
        notes = []
        agent.emit = lambda kind, payload: notes.append(str(payload))
        with patch.object(agent, "_ctx_limit", return_value=int(before_tokens / 0.90)), \
                patch("harness.context.summarize_messages") as summarize:
            agent._maybe_compress()
        summarize.assert_not_called()
        self.assertTrue(any("Masked" in n for n in notes), notes)

        # Verify originals survive intact in memory and after reload, while model view is compact.
        api_msgs = session.to_api_messages(include_pins=False)
        self.assertFalse(any(Session.MASKED_CONTENT_KEY in m for m in api_msgs))
        masked_api = [m for m in api_msgs if m.get("role") == "tool" and "Older read_file output omitted" in str(m.get("content"))]
        self.assertEqual(len(masked_api), 8)
        # Memory tool was NOT masked.
        mem_api = [m for m in api_msgs if m.get("tool_call_id") == "cmem"][0]
        self.assertIn("CRITICAL MEMORY", mem_api["content"])
        # Full original content survives in session.messages and after reload.
        reloaded = Session.load(cfg, session.id)
        self.assertEqual(reloaded.to_api_messages(include_pins=False), api_msgs)
        orig_first_tool = next(m for m in reloaded.messages if m.get("tool_call_id") == "c0")
        self.assertIn("x = 1\n", orig_first_tool["content"])
        self.assertEqual(reloaded.context_breakdown()["masked_tool_outputs"], 8)


class ResilientEditAndReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="marvin-edit-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.cfg = _make_cfg(self.tmp)
        self.session = Session(self.cfg, workspace=str(self.tmp))
        self.ctx = AgentContext(self.cfg, self.session, workspace=self.tmp, project_workspace=self.tmp)

    def test_apply_patch_whitespace_and_indent_fallback_diff_and_hint(self):
        target = self.tmp / "sample.py"
        target.write_bytes(b"def greet():\r\n    value = 1   \r\n    return value\r\n")
        # Read first so hash is tracked.
        ReadFileTool().run(self.ctx, "sample.py")

        # Level 2: trailing whitespace / LF difference matches uniquely.
        res = ApplyPatchTool().run(self.ctx, "sample.py", [
            {"old": "    value = 1\n    return value", "new": "    value = 2\n    return value"},
        ])
        self.assertTrue(res.startswith("OK: patched"), res)
        self.assertIn("whitespace-normalized", res)
        self.assertIn("-    value = 1", res)
        self.assertIn("+    value = 2", res)

        # Level 3: indentation-shifted multi-line match preserves target indent.
        res2 = ApplyPatchTool().run(self.ctx, "sample.py", [
            {"old": "value = 2\nreturn value", "new": "value = 3\nreturn value + 1"},
        ])
        self.assertTrue(res2.startswith("OK: patched"), res2)
        self.assertIn("indent-normalized", res2)
        self.assertIn("    value = 3", target.read_text(encoding="utf-8"))

        # Failure provides closest-match lines with line numbers.
        err = ApplyPatchTool().run(self.ctx, "sample.py", [
            {"old": "    value = 999\n    return value + 1", "new": "    value = 0"},
        ])
        self.assertIn("Closest match in file", err)
        self.assertIn("value = 3", err)

        # External modification after read triggers stale-file protection.
        target.write_text("def greet():\n    value = 42\n    return value\n", encoding="utf-8")
        stale = ApplyPatchTool().run(self.ctx, "sample.py", [{"old": "value = 42", "new": "value = 43"}])
        self.assertIn("changed on disk since you last read it", stale)

    def test_read_file_default_cap_and_toml_xml_validation(self):
        big = self.tmp / "big.txt"
        big.write_text("\n".join(f"line {i}" for i in range(1, 601)), encoding="utf-8")
        out = ReadFileTool().run(self.ctx, "big.txt")
        self.assertIn("lines 1-400 of 600", out)
        self.assertIn("200 more lines omitted", out)
        tail = ReadFileTool().run(self.ctx, "big.txt", start_line=590, end_line=600)
        self.assertIn("line 600", tail)

        self.assertIsNotNone(validate_syntax_pre_write("pyproject.toml", "[bad\nx = "))
        self.assertIsNone(validate_syntax_pre_write("pyproject.toml", '[project]\nname = "ok"\n'))
        self.assertIsNotNone(validate_syntax_pre_write("config.xml", "<root><unclosed></root>"))
        self.assertIsNone(validate_syntax_pre_write("config.xml", "<root><ok/></root>"))


class RecoveryGuardsAndMemoryTests(unittest.TestCase):
    def test_leaked_tool_call_and_reasoning_loop_recover_cleanly(self):
        tmp = Path(tempfile.mkdtemp(prefix="marvin-guard-"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        cfg = _make_cfg(tmp)

        # ReasoningLoopGuard detects verbatim repetition after threshold, ignores normal prose.
        guard = ReasoningLoopGuard(min_chars=400, window=100, repeats=4)
        self.assertFalse(guard.feed("Distinct reasoning sentence number " + " ".join(str(i) for i in range(150))))
        repeated = "Wait let me double check the exact same assumption again without changing anything. "
        triggered = False
        for _ in range(10):
            if guard.feed(repeated):
                triggered = True
                break
        self.assertTrue(triggered)

        # Leaked <tool_call> in plain text triggers silent retry rather than leaking XML to user.
        replies = [
            AssistantResult(content="<tool_call>read_file\n<arg_key>path</arg_key>"),
            AssistantResult(content="All clean now."),
        ]

        class StubLLM:
            def stream(self, messages, **kwargs):
                return replies.pop(0)

        session = Session(cfg, system_prompt="SYS", workspace=str(tmp))
        agent = Agent(cfg, StubLLM(), session, build_registry("agent", "development", cfg), SafetyPolicy("auto"))
        agent.new_task("Inspect")
        r1 = agent.step()
        self.assertIs(r1.status, Status.CONTINUE)
        r2 = agent.step()
        self.assertIs(r2.status, Status.FINAL)
        self.assertEqual(r2.text, "All clean now.")

    def test_memory_dedup_replace_and_remove(self):
        tmp = Path(tempfile.mkdtemp(prefix="marvin-mem-"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        cfg = _make_cfg(tmp)
        store = MemoryStore(cfg, tmp, "development")
        self.assertIn("OK:", store.append("Use Pytest for backend tests", "project"))
        self.assertIn("Already in", store.append("use pytest for backend tests", "project"))
        self.assertIn("OK: updated", store.replace("Pytest", "Use unittest for backend tests", "project"))
        self.assertIn("Use unittest for backend tests", store.read("project"))
        self.assertNotIn("Pytest", store.read("project"))
        self.assertIn("OK: removed", store.remove("unittest", "project"))
        self.assertNotIn("unittest", store.read("project"))


class IndexesShellAndTelemetryTests(unittest.TestCase):
    def test_incremental_code_index_and_multilang_repo_index(self):
        tmp = Path(tempfile.mkdtemp(prefix="marvin-idx-"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        (tmp / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
        (tmp / "b.ts").write_text("export function renderWidget() { return null; }\n", encoding="utf-8")

        idx = CodeIndex(tmp)
        self.assertEqual(len(idx.find_symbol("alpha")), 1)
        self.assertEqual(len(idx.find_symbol("renderWidget")), 1)
        with patch.object(idx, "_python_symbols", wraps=idx._python_symbols) as spy_py:
            (tmp / "b.ts").write_text("export function renderWidgetV2() { return null; }\n", encoding="utf-8")
            idx.invalidate(tmp / "b.ts")
            self.assertEqual(len(idx.find_symbol("renderWidgetV2")), 1)
            spy_py.assert_not_called()

        summary = RepoIndex(tmp).summary()
        self.assertIn("alpha", summary)
        self.assertIn("renderWidgetV2", summary)

    def test_shell_read_only_rules_and_failure_line_extraction(self):
        self.assertTrue(is_read_only_command("rg pattern src"))
        self.assertTrue(is_read_only_command("git branch"))
        self.assertTrue(is_read_only_command("git branch -a"))
        self.assertTrue(is_read_only_command("git remote -v"))
        self.assertTrue(is_read_only_command("git tag --list"))
        self.assertTrue(is_read_only_command("Get-ChildItem src"))
        self.assertFalse(is_read_only_command("git branch -D feature"))
        self.assertFalse(is_read_only_command("git branch new-branch"))
        self.assertFalse(is_read_only_command("git remote add origin https://example.com"))
        self.assertFalse(is_read_only_command("git tag v1.0.0"))

        noisy = "\n".join(f"ok line {i}" for i in range(500)) + "\nAssertionError: expected 42 got 0\n" + "\n".join(f"tail {i}" for i in range(500))
        hits = _extract_failure_lines(noisy, "")
        self.assertTrue(any("AssertionError: expected 42 got 0" in h for h in hits))

    def test_session_detail_reports_prompt_cache_hit_rate(self):
        tmp = Path(tempfile.mkdtemp(prefix="marvin-cache-"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        cfg = _make_cfg(tmp)
        service = ApplicationService(cfg, manage_model=False)
        self.addCleanup(service.close)
        session = service.new_session(work_mode="development")
        session.meta["last_usage"] = {
            "prompt_tokens": 20000,
            "completion_tokens": 200,
            "timings": {"cache_n": 19000, "prompt_n": 1000},
        }
        detail = session_detail(service, session)
        self.assertEqual(detail["context"]["cache_hit"], {"cached": 19000, "total": 20000, "percent": 95.0})


if __name__ == "__main__":
    unittest.main()
