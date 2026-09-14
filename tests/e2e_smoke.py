"""End-to-end smoke test requiring downloaded weights and a GPU.

Exercise chat, file creation through tools and image reading. Run with tests/e2e_smoke.py [--model q4]."""
from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.agent import Agent, Status, build_registry
from harness.config import load_config
from harness.llm import LLMClient
from harness.prompts import system_prompt
from harness.safety import SafetyPolicy
from harness.session import Session
from harness import servermgmt

PASS, FAIL = 0, 0


def check(cond: bool, label: str, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {label}")
    else:
        FAIL += 1
        print(f"  ✗ FAIL: {label} {extra}")


def make_test_image(path: Path) -> None:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (400, 200), "white")
    d = ImageDraw.Draw(img)
    d.text((30, 60), "QWEN 3.8 TEST 42", fill="black")
    d.rectangle([20, 20, 380, 180], outline="red", width=3)
    img.save(path)


def run_agent_task(cfg, llm, task: str, images=None, mode: str = "agent", max_steps: int = 12):
    session = Session(cfg, system_prompt=system_prompt(mode))
    safety = SafetyPolicy("auto", max_steps=max_steps, semi_max_steps=max_steps)
    agent = Agent(cfg, llm, session, build_registry(mode), safety, mode=mode)
    agent.new_task(task, images=images)
    final_text = ""
    steps = 0
    while steps < max_steps:
        r = agent.step(approve=True)  # Test fixtures use automatic action approval.
        steps += 1
        if r.status is Status.FINAL:
            final_text = r.text
            break
        if r.status in (Status.ERROR, Status.ABORTED):
            final_text = f"[{r.status.value}] {r.text}"
            break
    return final_text, session


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="q4")
    ap.add_argument("--skip-server-start", action="store_true")
    args = ap.parse_args()
    cfg = load_config()

    print("=== E2E SMOKE TEST ===")
    if not args.skip_server_start:
        print(f"[server] starting model {args.model} ...")
        if servermgmt.start(cfg, args.model) != 0:
            print("CANNOT START SERVER")
            return 2
    elif not servermgmt.health(cfg):
        print("The server is not running!")
        return 2

    llm = LLMClient(cfg)

    # 1) Basic chat and latency.
    print("\n[1] Chat")
    t0 = time.time()
    session = Session(cfg, system_prompt=system_prompt("chat"))
    safety = SafetyPolicy("auto", max_steps=5)
    agent = Agent(cfg, llm, session, build_registry("chat"), safety, mode="chat")
    agent.new_task("In one sentence, explain the main difference between RAM and disk storage.")
    r = agent.step(approve=True)
    dt = time.time() - t0
    ok = r.status is Status.FINAL and len(r.text) > 20
    check(ok, f"chat response ({dt:.1f}s)", f"status={r.status} text={r.text[:100]!r}")
    if r.text:
        print(f"      → {r.text[:150]}")

    # 2) File creation through agent tool calling.
    print("\n[2] Agent + tool calling (write_file)")
    tmp = Path(tempfile.mkdtemp())
    old_ws = cfg.agent.get("workspace")
    cfg.agent["workspace"] = str(tmp)
    try:
        text, session = run_agent_task(
            cfg, llm,
            f"Create file 'e2e_test.txt' containing exactly this single line: HELLO-QWEN-E2E "
            f"and then respond 'DONE'.")
        f = tmp / "e2e_test.txt"
        check(f.exists() and "HELLO-QWEN-E2E" in f.read_text(encoding="utf-8"),
              "File created with the expected content",
              f"(exists={f.exists()}, text={text[:150]!r})")
        tool_calls_used = [m for m in session.messages if m.get("tool_calls")]
        check(bool(tool_calls_used), "The model actually called tools")
    finally:
        cfg.agent["workspace"] = old_ws

    # 3) vision
    print("\n[3] Vision: reading an image")
    img_path = tmp / "vision_test.png"
    make_test_image(img_path)
    text, _ = run_agent_task(
        cfg, llm,
        "What number is written in the attached image? Reply with the number only.",
        images=[img_path], mode="chat")
    check("42" in text, f"model read '42' from the image", f"text={text[:200]!r}")

    print(f"\n=== RESULT: {PASS} ✓ / {FAIL} ✗ ===")
    print(servermgmt.vram_str())
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
