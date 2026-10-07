"""GPU integration of Qwen3.8-Flash-Next (Strata) in the real application worker.

Needs the weights, Strata's program and its packs on this PC: the installed
Marvin's models folder for the llama models and Strata's data folder, and a
Strata program folder (scripts/strata_eval.py install, until Marvin prepares it
itself). Runs on its own port with its own runtime folder, so the installed
Marvin's state is untouched; stop Marvin's model first.

    python tests/e2e_flash_next.py switch     # Q5 -> Flash-Next -> Q5 in one chat
    python tests/e2e_flash_next.py coding     # an agent edits code and runs the project check
    python tests/e2e_flash_next.py pressure   # 48 GB of RAM, memory taken mid-task: 256k -> 128k
    python tests/e2e_flash_next.py clean      # no engine, no prepared files: Marvin prepares them
    python tests/e2e_flash_next.py all
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import psutil  # noqa: E402

from harness import servermgmt  # noqa: E402
from harness.application import ApplicationService  # noqa: E402
from harness.config import Config, load_config  # noqa: E402

LOCAL = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
KEY = "flash_next_strata"
PORT = 8087
GIB = 1024**3


def make_config(args, directory: Path) -> Config:
    (directory / "config.yaml").write_text("", encoding="utf-8")
    cfg = load_config(directory / "config.yaml", root=directory)
    cfg.data["paths"].update(models_dir=str(args.models_dir), llama_dir=str(args.llama_dir),
                             strata_dir=str(args.strata_dir), strata_data_dir=str(args.strata_data_dir))
    cfg.data["server"]["port"] = PORT
    cfg.data["skills"]["directory"] = str(ROOT / "skills")
    cfg.data["agent"].update(workspace=None, autonomy="auto")
    cfg.data["thinking"] = False
    cfg.data["work_mode"] = "discussion"
    return cfg


def run(service: ApplicationService, session, text: str, request_id: str, *, attachments=(), timeout=900) -> dict:
    """Submit one message and wait; the answer, the tools it used and the model that served it."""
    start = len(session.messages)
    started = time.monotonic()
    service.submit(session.id, text, attachments=list(attachments), request_id=request_id)
    deadline = started + timeout
    while time.monotonic() < deadline:
        job = service.store.job(request_id)
        if job["status"] in ("complete", "failed", "stopped") and service.active is None:
            break
        time.sleep(0.3)
    else:
        service.stop(session.id)
        raise AssertionError(f"{request_id} did not finish within {timeout} s")
    new = session.messages[start:]
    answer = next((str(m.get("content", "")) for m in reversed(new) if m.get("role") == "assistant"), "")
    return {"status": job["status"], "error": job["payload"].get("error"), "answer": answer,
            "tools": [m.get("name") for m in new if m.get("role") == "tool"],
            "model": servermgmt.running_model(service.cfg), "seconds": round(time.monotonic() - started, 1)}


def require(condition, what, evidence):
    if not condition:
        raise AssertionError(f"{what}: {json.dumps(evidence, ensure_ascii=False)[:2000]}")


def service_for(cfg: Config, model: str, thinking="off") -> ApplicationService:
    service = ApplicationService(cfg)
    service.preferences.update(model=model, thinking=thinking, autonomy="auto")
    return service


def clean(args, directory: Path) -> dict:
    """A PC with no engine and no prepared files: Marvin prepares everything when Flash-Next is chosen.

    The weights are hard-linked from the given data folder to save their 84 GB
    download; Marvin still verifies them. The engine, the pack and the draft
    layer (about 5 GB from Hugging Face) are made from nothing."""
    from harness import strata_backend, strata_runtime
    source = args.strata_data_dir
    args = copy.copy(args)
    args.strata_dir = directory / "runtime" / "strata"
    args.strata_data_dir = directory / "runtime" / "models" / "strata"
    for relative in ("models/IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf",
                     "models/IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00002-of-00002.gguf",
                     "models/mmproj-Qwen3.8-Flash-Next-BF16.gguf"):
        target = args.strata_data_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        os.link(source / relative, target)
    result = switch(args, directory, fresh=True)
    (directory / "check").mkdir()
    cfg = make_config(args, directory / "check")
    result["prepared"] = {"engine": strata_runtime.installed_record(cfg),
                          "missing_after": strata_backend.model_problems(cfg, KEY),
                          "draft_layer": sorted(p.name for p in (args.strata_data_dir / "mtp" / "rt").iterdir())}
    require(not result["prepared"]["missing_after"] and result["prepared"]["engine"].get("version"),
            "everything was prepared", result["prepared"])
    return result


def switch(args, directory: Path, fresh=False) -> dict:
    """The owner's requirement: switch the model and carry on in the same chat."""
    from PIL import Image
    cfg = make_config(args, directory)
    project = directory / "project"
    project.mkdir()
    service = service_for(cfg, "q5")
    steps = {}
    try:
        session = service.new_session(str(project), "discussion")
        steps["q5"] = r = run(service, session,
            "Remember this code word for later: AMBER-4417. Use write_file to create notes.txt in the current "
            "project containing exactly Q5_WAS_HERE, then use read_file to check it. Reply with the code word.",
            "switch-q5")
        require(r["status"] == "complete" and r["model"] == "q5" and "AMBER-4417" in r["answer"]
                and (project / "notes.txt").read_text().strip() == "Q5_WAS_HERE"
                and {"write_file", "read_file"} <= set(r["tools"]), "Q5 turn", r)

        service.preferences["model"] = KEY
        service.save_preferences()
        steps["flash_recall"] = r = run(service, session,
            "Use read_file to read notes.txt and tell me its exact content, and the code word I gave you earlier.",
            "switch-flash-recall", timeout=5400 if fresh else 900)
        require(r["status"] == "complete" and r["model"] == KEY and "Q5_WAS_HERE" in r["answer"]
                and "AMBER-4417" in r["answer"] and "read_file" in r["tools"], "Flash-Next continues the chat", r)

        image = session.dir / "solid-green.png"
        Image.new("RGB", (320, 240), (0, 190, 0)).save(image)
        record = service.store.register_file(image, session.id, "attachment")
        steps["flash_vision"] = r = run(service, session,
            "Look at the attached image. Which single color fills it? Reply with one English color word.",
            "switch-flash-vision", attachments=[record["id"]])
        require(r["status"] == "complete" and "green" in r["answer"].lower(), "Flash-Next reads the image", r)

        steps["flash_note"] = r = run(service, session,
            "Remember a second code word: TEAL-2290. Reply only with OK.", "switch-flash-note")
        require(r["status"] == "complete", "Flash-Next turn", r)

        service.preferences["model"] = "q5"
        service.save_preferences()
        steps["q5_again"] = r = run(service, session,
            "List both code words I gave you in this conversation.", "switch-q5-again")
        require(r["status"] == "complete" and r["model"] == "q5" and "AMBER-4417" in r["answer"]
                and "TEAL-2290" in r["answer"], "Q5 continues after Flash-Next", r)
        return steps
    finally:
        service.close()
        servermgmt.stop(cfg, quiet=True)


def coding(args, directory: Path) -> dict:
    cfg = make_config(args, directory)
    project = directory / "coding"
    (project / "tests").mkdir(parents=True)
    (project / "target.py").write_text('VALUE = "before"\n', encoding="utf-8")
    (project / "tests" / "test_core.py").write_text(
        "from pathlib import Path\n"
        "text = Path('target.py').read_text(encoding='utf-8')\n"
        "assert 'VALUE = \"after\"' in text, text\n"
        "print('CODING-WORKFLOW-TEST-OK')\n", encoding="utf-8")
    service = service_for(cfg, args.coding_model, args.thinking)
    try:
        session = service.new_session(str(project), "development")
        r = run(service, session,
            "In target.py, replace exactly VALUE = \"before\" with VALUE = \"after\". Use apply_patch; do not use "
            "write_file or run_command. Then call start_project_check and poll_command until the check finishes. "
            "Finally, briefly confirm the result.", "coding-flash", timeout=1200)
        require(r["status"] == "complete" and r["model"] == args.coding_model
                and 'VALUE = "after"' in (project / "target.py").read_text(encoding="utf-8")
                and "apply_patch" in r["tools"] and "start_project_check" in r["tools"], "coding workflow", r)
        return {"coding": r}
    finally:
        service.close()
        servermgmt.stop(cfg, quiet=True)


def ballast(gib: float) -> subprocess.Popen:
    proc = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "strata_ballast.py"), "ram", "--lock-gib",
                             f"{gib:.2f}"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    line = proc.stdout.readline().strip()
    if not line.startswith("READY "):
        proc.kill()
        raise RuntimeError(f"RAM ballast of {gib:.2f} GiB failed: {line}")
    return proc


def release(proc):
    if proc is not None and proc.poll() is None:
        proc.stdin.close()
        try:
            proc.wait(30)
        except subprocess.TimeoutExpired:
            proc.kill()


def pressure(args, directory: Path) -> dict:
    """A 48 GB machine with a 16 GB card, and another program takes the free RAM before a long input.

    The resident mode sizes its page-locked share from the RAM free at start, so
    the memory taken afterwards leaves the engine short while it reads the input
    (a 16 GB card gathers many experts from RAM; a 32 GB card coped). Marvin
    restarts at 128k with the same expert cache and finishes the task."""
    cfg = make_config(args, directory)
    installed = psutil.virtual_memory().total / GIB
    first = ballast(installed - 48 + 0.3)
    second = None
    service = None
    try:
        with patch("harness.gpu.installed_ram_gib", return_value=47.7):
            service = service_for(cfg, KEY)
            service.preferences["vram_gb"] = 16
            service.preferences.setdefault("kv_cache_modes", {})[KEY] = "int8_256k_r48g16"
            session = service.new_session(work_mode="discussion")
            warm = run(service, session, "Reply only with READY.", "pressure-warm")
            require(warm["status"] == "complete" and warm["model"] == KEY, "Flash-Next starts on 48 GB", warm)
            placement = json.loads((cfg.path("paths.runtime_dir") / "model-run.json").read_text(encoding="utf-8"))
            # Another program now takes what is free.
            free = psutil.virtual_memory().available / GIB
            second = ballast(max(0.5, free - 0.3))
            lines = [f"Record {i:06d}: routine inventory record, status unchanged, no special access phrase."
                     for i in range(5200)]
            for fraction, name, value in ((.1, "Cedar", "OPAL-6291"), (.5, "Birch", "MICA-8537"), (.9, "Maple", "JADE-4176")):
                lines[int(len(lines) * fraction)] = f"Special record: Project {name} has access phrase {value}."
            r = run(service, session, "\n".join(lines) + "\nList the access phrases for Cedar, Birch and Maple. "
                    "Give all three exactly.", "pressure-long", timeout=1800)
            after = json.loads((cfg.path("paths.runtime_dir") / "model-run.json").read_text(encoding="utf-8"))
            result = {"warm": warm, "long": r, "first_run": {k: placement.get(k) for k in ("context", "placement")},
                      "after": {k: after.get(k) for k in ("context", "placement")},
                      "restarts": (cfg.path("paths.runtime_dir") / "model-restarts.log").read_text(encoding="utf-8")
                      if (cfg.path("paths.runtime_dir") / "model-restarts.log").exists() else ""}
            require(r["status"] == "complete" and all(v in r["answer"] for v in ("OPAL-6291", "MICA-8537", "JADE-4176")),
                    "the long task finished", result)
            require(after["context"] == 131072, "recovered to 128k", result)
            kept = placement["placement"].get("expert_cache_slots") or placement["placement"].get("expert_cache")
            require(after["placement"].get("expert_cache") == kept, "the expert cache stayed", result)
            return result
    finally:
        if service is not None:
            service.close()
        servermgmt.stop(cfg, quiet=True)
        release(second)
        release(first)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenario", choices=("switch", "coding", "pressure", "clean", "all"))
    parser.add_argument("--models-dir", type=Path, default=LOCAL / "QwenHarness" / "runtime" / "models")
    parser.add_argument("--llama-dir", type=Path, default=LOCAL / "QwenHarness" / "runtime" / "llama")
    parser.add_argument("--strata-dir", type=Path, default=LOCAL / "QwenHarness" / "runtime" / "strata")
    parser.add_argument("--strata-data-dir", type=Path, default=LOCAL / "QwenHarness" / "runtime" / "models" / "strata")
    parser.add_argument("--coding-model", default=KEY, help="the model the coding scenario runs on (a comparison)")
    parser.add_argument("--thinking", default="off", choices=("off", "low", "medium", "xhigh"),
                        help="thinking for the coding scenario (the workspace's default is xhigh)")
    parser.add_argument("--output", type=Path, help="write the results as JSON here")
    args = parser.parse_args()
    scenarios = {"switch": switch, "coding": coding, "pressure": pressure, "clean": clean}
    chosen = list(scenarios) if args.scenario == "all" else [args.scenario]
    results, failed = {}, False
    for name in chosen:
        with tempfile.TemporaryDirectory(prefix=f"flash-e2e-{name}-") as directory:
            started = time.monotonic()
            try:
                results[name] = {"ok": True, **scenarios[name](args, Path(directory))}
            except Exception as exc:
                failed = True
                results[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            results[name]["seconds"] = round(time.monotonic() - started, 1)
            print(name, "OK" if results[name]["ok"] else "FAILED", results[name].get("error", ""), flush=True)
    text = json.dumps(results, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
