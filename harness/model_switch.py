"""Asynchronous local-model startup and switching.

Requests replace the pending target while keeping model and KV controls interactive. Switching during loading cancels the previous load, releases its memory and starts the new target. The requested KV profile is applied when the server starts."""
from __future__ import annotations

import copy
import inspect
import threading
import time
from dataclasses import dataclass, replace
from typing import Callable

from harness import servermgmt
from harness.config import Config
from harness.i18n import t


@dataclass(frozen=True)
class ModelSwitchSnapshot:
    status: str = "idle"  # idle | starting | ready | failed
    target: str | None = None
    error: str = ""
    started_at: float = 0
    phase: str = "idle"
    command: str = ""
    downloaded_bytes: int = 0
    total_bytes: int = 0
    restored_model: str | None = None

    @property
    def busy(self) -> bool:
        return self.status in ("starting", "stopping")


def _running_model_ok(cfg: Config, model_key: str) -> bool:
    return servermgmt.health(cfg) and servermgmt.running_model(cfg) == model_key


class ModelSwitchController:
    """One background worker handles model startup and switching.

    Each iteration takes the latest request, stops the old server when necessary, starts the requested model and KV profile, and publishes its state. A newer request cancels obsolete work before the next target is loaded."""

    def __init__(self, cfg: Config, *,
                 ensure_fn: Callable[[Config, str], bool] = servermgmt.ensure,
                 stop_fn: Callable[..., bool] = servermgmt.stop,
                 running_fn: Callable[[Config, str], bool] = _running_model_ok):
        self.cfg = cfg
        self._ensure = ensure_fn
        self._stop = stop_fn
        self._running = running_fn
        self._lock = threading.Lock()
        self._state = ModelSwitchSnapshot()
        self._thread: threading.Thread | None = None
        # (model_key, kv_profile, restart, on_success, incoming_config, on_failure)
        self._desired: tuple | None = None
        self._gen = 0  # Incremented on every request/cancellation to invalidate stale publications.
        self._last_ready: tuple[Config, str] | None = None
        self._controlled_ensure = "cancelled" in inspect.signature(ensure_fn).parameters
        self._phase_ensure = "on_phase" in inspect.signature(ensure_fn).parameters
        self._progress_ensure = "on_download_progress" in inspect.signature(ensure_fn).parameters

    def snapshot(self) -> ModelSwitchSnapshot:
        with self._lock:
            return self._state

    def remember_configuration(self, cfg: Config, key: str) -> None:
        """Seed rollback from a previously successful, still installed model."""
        with self._lock:
            self._last_ready = (Config(copy.deepcopy(cfg.data), cfg.root), key)

    def request(self, model_key: str, *, restart: bool = False,
                kv_profile: str | None = None,
                on_success: Callable[[str], None] | None = None,
                config: Config | None = None,
                on_failure: Callable[[str | None], None] | None = None) -> bool:
        """Accept the request and interrupt an obsolete load to release GPU memory."""
        with self._lock:
            interrupted = self._state.busy
            self._desired = (model_key, kv_profile, restart, on_success, config, on_failure)
            self._gen += 1
            self._state = ModelSwitchSnapshot("starting", model_key, started_at=time.time(),
                                              phase="preparing", command="restart" if restart else "start")
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run, daemon=True, name="model-switch")
                self._thread.start()
        if interrupted and not self._controlled_ensure:
            # Stop the running/loading server outside the lock so ensure can return promptly
            # The interrupted ensure call returns and the loop selects the latest target.
            try:
                self._stop(self.cfg, quiet=True)
            except Exception:
                pass
        return True

    def cancel(self) -> None:
        """Discard the pending target, stop the server and return to idle."""
        with self._lock:
            self._desired = None
            self._gen += 1
            gen = self._gen
            self._state = ModelSwitchSnapshot("stopping", self._state.target, started_at=time.time(),
                                              phase="stopping", command="stop")
        try:
            self._stop(self.cfg, quiet=True)
        except Exception:
            pass
        self._publish(gen, ModelSwitchSnapshot())

    def reset(self) -> None:
        """Discard a pending request without changing the running server."""
        with self._lock:
            self._desired = None

    def wait(self, timeout: float | None = None) -> bool:
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout)
            return not thread.is_alive()
        return True

    # ------------------------------------------------------------------
    def _cancelled(self, gen):
        with self._lock:
            return self._gen != gen

    def _ensure_controlled(self, cfg, key, gen):
        kwargs = {}
        if self._controlled_ensure:
            kwargs["cancelled"] = lambda: self._cancelled(gen)
        if self._phase_ensure:
            kwargs["on_phase"] = lambda phase: self._publish(gen, ModelSwitchSnapshot("starting", key, phase=phase))
        if self._progress_ensure:
            kwargs["on_download_progress"] = lambda done, total: self._publish(gen,
                ModelSwitchSnapshot("starting", key, phase="downloading", downloaded_bytes=done, total_bytes=total))
        return self._ensure(cfg, key, **kwargs)

    def _run(self) -> None:
        while True:
            with self._lock:
                if self._desired is None:
                    self._thread = None
                    return
                target, kv_profile, restart, on_success, incoming, on_failure = self._desired
                self._desired = None
                gen = self._gen
            run_cfg = Config(copy.deepcopy(incoming.data), incoming.root) if incoming else self.cfg
            try:
                profile_changed = kv_profile and kv_profile != self.cfg.kv_cache_mode(target)
                from harness.gpu import effective_vram_gb
                before = {k: v for k, v in self.cfg.data.get("hardware", {}).items() if k != "vram_gb"}
                after = {k: v for k, v in run_cfg.data.get("hardware", {}).items() if k != "vram_gb"}
                hardware_changed = before != after or effective_vram_gb(run_cfg) != effective_vram_gb(self.cfg)
                if not restart and not profile_changed and not hardware_changed and self._running(self.cfg, target):
                    if self._cancelled(gen):
                        continue
                    run_cfg.data["default_model"] = target
                    for field in ("_active_placement", "_recovery_placement", "_recovered_contexts"):
                        if field in self.cfg.data:
                            run_cfg.data[field] = copy.deepcopy(self.cfg.data[field])
                    self.cfg = run_cfg
                    self._last_ready = (Config(copy.deepcopy(self.cfg.data), self.cfg.root), target)
                    if on_success is not None:
                        on_success(target)
                    # Reuse an already running matching model without restarting it.
                    self._publish(gen, ModelSwitchSnapshot("ready", target))
                    continue
                self._publish(gen, ModelSwitchSnapshot("starting", target, phase="releasing"))
                if self._stop(self.cfg, quiet=True) is False:
                    raise RuntimeError("The previous model could not release its memory")
                if kv_profile:
                    run_cfg.set_kv_cache_mode(target, kv_profile)
                run_cfg.data["default_model"] = target
                if self._cancelled(gen):
                    continue
                self._publish(gen, ModelSwitchSnapshot("starting", target, phase="loading"))
                if not self._ensure_controlled(run_cfg, target, gen):
                    raise RuntimeError("llama-server could not be prepared")
                if self._cancelled(gen):
                    continue
                self.cfg = run_cfg
                self._last_ready = (Config(copy.deepcopy(run_cfg.data), run_cfg.root), target)
                callback_error = ""
                if on_success is not None:
                    try:
                        on_success(target)
                    except Exception as exc:
                        callback_error = t("Failed to save UI state: {error}", error=exc)
                self._publish(gen, ModelSwitchSnapshot("ready", target, callback_error))
            except Exception as exc:
                if self._cancelled(gen):
                    continue
                restored = None
                restore_error = ""
                if self._last_ready:
                    previous_cfg, previous_key = self._last_ready
                    try:
                        self._publish(gen, ModelSwitchSnapshot("starting", target, phase="restoring"))
                        restored_ok = self._running(previous_cfg, previous_key)
                        if not restored_ok:
                            if self._stop(run_cfg, quiet=True) is False:
                                raise RuntimeError("The stopped model has not released its memory")
                            restored_ok = self._ensure_controlled(previous_cfg, previous_key, gen)
                        if restored_ok and not self._cancelled(gen):
                            if incoming is None:
                                # The compatibility UI holds the original Config object.
                                run_cfg.data.clear()
                                run_cfg.data.update(copy.deepcopy(previous_cfg.data))
                                self.cfg = run_cfg
                            else:
                                self.cfg = previous_cfg
                            restored = previous_key
                    except Exception as restore_exc:
                        restore_error = f"; restore: {restore_exc}"
                self._publish(gen, ModelSwitchSnapshot(
                    "failed", target, f"{type(exc).__name__}: {exc}{restore_error}", restored_model=restored))
                if on_failure is not None and not self._cancelled(gen):
                    try:
                        on_failure(restored)
                    except Exception as callback_exc:
                        self._publish(gen, ModelSwitchSnapshot("failed", target,
                            f"{type(exc).__name__}: {exc}{restore_error}; UI state: {callback_exc}"))

    def _publish(self, gen: int, state: ModelSwitchSnapshot) -> None:
        """Publish only if no newer request has superseded this generation."""
        with self._lock:
            if self._gen == gen:
                self._state = replace(state, started_at=state.started_at or self._state.started_at,
                                      command=state.command or self._state.command)
