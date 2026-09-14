import { translate } from "../i18n";
import { useEffect, useState } from "react";
import { LoaderCircle, Check, AlertCircle } from "lucide-react";

export function ModelStatus({ runtime, cs }: { runtime: any; cs: boolean }) {
  const [now, setNow] = useState(Date.now());
  const state = runtime.switch || {};
  const busy = ["starting", "stopping"].includes(state.status);
  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [busy]);
  const phases: Record<string, string> = {
    preparing: "Preparing model server",
    releasing: "Freeing memory for the new configuration",
    downloading: "Downloading model",
    verifying: "Checking downloaded files",
    loading: "Loading model",
    restoring: "Restoring the previous model",
    stopping: "Stopping model and freeing GPU memory",
  };
  const failed = state.status === "failed";
  const restored = failed && state.restored_model && runtime.status === "running";
  return <div className={"model-progress " + (busy ? "running" : failed && !restored ? "failed" : "")} role="status">
    {busy ? <LoaderCircle className="spin" /> : failed && !restored ? <AlertCircle /> : <Check />}
    <div><strong>{busy ? translate(phases[state.phase] || phases.preparing, cs ? "cs" : "en") : failed ? (state.restored_model ? (translate("Previous working configuration restored", cs ? "cs" : "en")) : (translate("Model failed to start", cs ? "cs" : "en"))) : runtime.status === "running" ? (translate("Model is ready", cs ? "cs" : "en")) : (translate("Model is stopped", cs ? "cs" : "en"))}</strong>
    {busy && <small>{Math.max(0, Math.floor(now / 1000 - (state.started_at || now / 1000)))} s · VRAM {runtime.vram || "—"}</small>}
    {busy && state.phase === "downloading" && state.total_bytes > 0 && <small>
      {Math.min(100, Math.floor(100 * state.downloaded_bytes / state.total_bytes))}% · {(
        state.downloaded_bytes / 1e9).toFixed(1)} / {(state.total_bytes / 1e9).toFixed(1)} GB
    </small>}
    {state.error && <small className={restored ? "amber" : "error"}>{state.error}</small>}</div>
  </div>;
}
