"""Exercise real budget switching and recovery on isolated local application data."""
from pathlib import Path
import argparse
import json
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import psutil
from fastapi.testclient import TestClient
from harness import servermgmt
from harness.application import ApplicationService
from harness.config import load_config
from harness.llm import LLMClient
from harness.web_api import create_app
from tests.check_runtime_upgrade import make_config, save, stop_owned


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if any((p.info["name"] or "").lower() == "llama-server.exe" for p in psutil.process_iter(["name"])):
        raise RuntimeError("Another model server is running")
    if output.exists():
        raise RuntimeError("Use a new output directory")
    original = load_config()
    cfg = make_config(original, output, original.path("paths.llama_dir"), "q5", "q8_0", 8087)
    cfg.data["hardware"]["vram_gb"] = "auto"
    injection = {"enabled": False, "count": 0}

    class FaultOnce(LLMClient):
        def stream(self, *args, **kwargs):
            if injection["enabled"] and not injection["count"]:
                injection["count"] += 1
                stop_owned(self.cfg)
                save(self.cfg.path("paths.runtime_dir") / "model-failure.json", {
                    "model": self.cfg.model_key(), "time": time.time(), "code": "vram_pressure",
                    "error": "Injected memory pressure for the recovery qualification"})
                raise RuntimeError("Injected model disconnection")
            return super().stream(*args, **kwargs)

    service = ApplicationService(cfg, llm_factory=FaultOnce)
    report = {"scope": "Actual model restarts and GPU budget profiles; memory pressure is injected without exhausting RAM", "transitions": []}
    def ready(key):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            snapshot = service.models.snapshot()
            if snapshot.status == "failed":
                raise RuntimeError(snapshot.error)
            if snapshot.status == "ready" and servermgmt.health(cfg):
                assert servermgmt.running_model(cfg) == key
                return
            time.sleep(.15)
        raise TimeoutError("Model did not become ready")

    def complete(rid):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            job = service.store.job(rid)
            if job and job["status"] in ("complete", "failed", "stopped") and service.active is None:
                assert job["status"] == "complete", job
                return job
            time.sleep(.1)
        raise TimeoutError("Task did not finish")

    try:
        with TestClient(create_app(cfg, service=service)) as client:
            ready("q5")
            sid = client.post("/api/sessions", json={"work_mode": "discussion"}).json()["session_id"]
            for index, (budget, model, profile) in enumerate(((24, "q5", "q8_0_96k"), (16, "q3", "q8_0_64k"), ("auto", "q5", "q8_0"))):
                started = time.monotonic()
                client.patch("/api/settings", json={"vram_gb": budget}).raise_for_status()
                ready(model)
                assert service.models.cfg.kv_cache_mode(model) == profile
                rid = f"switch-{index}"
                marker = f"MEMORY-CHECK-{index}"
                client.post(f"/api/sessions/{sid}/submit", json={"text": f"Reply with exactly {marker}.", "request_id": rid}).raise_for_status()
                complete(rid)
                assert marker in service.session(sid).messages[-1].get("content", "")
                report["transitions"].append({"budget": budget, "model": model, "profile": profile, "seconds": time.monotonic() - started})
                save(output / "results.json", report)
                print("PASS", budget, model, profile, flush=True)
            before = servermgmt.pid_file(cfg).read_text()
            client.patch("/api/settings", json={"vram_gb": 32}).raise_for_status()
            ready("q5")
            assert servermgmt.pid_file(cfg).read_text() == before
            report["equivalent_budget_reused_server"] = True
            injection["enabled"] = True
            client.post(f"/api/sessions/{sid}/submit", json={"text": "Reply with exactly MEMORY-RECOVERED.", "request_id": "recovery"}).raise_for_status()
            complete("recovery")
            assert injection["count"] == 1
            assert service.models.cfg.kv_cache_mode("q5") == "q8_0_128k"
            assert "MEMORY-RECOVERED" in service.session(sid).messages[-1].get("content", "")
            assert len([m for m in service.session(sid).messages if m.get("role") == "user" and m.get("content") == "Reply with exactly MEMORY-RECOVERED."]) == 1
            report["injected_pressure_recovered"] = True
            report["recovered_profile"] = service.models.cfg.kv_cache_mode("q5")
            report["ok"] = True
            print("PASS pressure recovery", flush=True)
    except Exception as exc:
        report.update(ok=False, error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        stop_owned(cfg)
        service.close()
        save(output / "results.json", report)


if __name__ == "__main__":
    main()
