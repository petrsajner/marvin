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
  const phases: Record<string, [string, string]> = {
    preparing: ["Preparing model server", "Připravuji server modelu"],
    downloading: ["Downloading model", "Stahuji model"],
    verifying: ["Checking downloaded files", "Kontroluji stažené soubory"],
    loading: ["Loading model", "Načítám model"],
    restoring: ["Restoring the previous model", "Obnovuji předchozí model"],
    stopping: ["Stopping model and freeing GPU memory", "Zastavuji model a uvolňuji paměť grafické karty"],
  };
  const failed = state.status === "failed";
  return <div className={"model-progress " + (busy ? "running" : failed ? "failed" : "")} role="status">
    {busy ? <LoaderCircle className="spin" /> : failed ? <AlertCircle /> : <Check />}
    <div><strong>{busy ? (phases[state.phase] || phases.preparing)[cs ? 1 : 0] : failed ? (cs ? "Spuštění modelu selhalo" : "Model failed to start") : runtime.status === "running" ? (cs ? "Model je připravený" : "Model is ready") : (cs ? "Model je zastavený" : "Model is stopped")}</strong>
    {busy && <small>{Math.max(0, Math.floor(now / 1000 - (state.started_at || now / 1000)))} s · VRAM {runtime.vram || "—"}</small>}
    {busy && state.phase === "downloading" && state.total_bytes > 0 && <small>
      {Math.min(100, Math.floor(100 * state.downloaded_bytes / state.total_bytes))}% · {(
        state.downloaded_bytes / 1e9).toFixed(1)} / {(state.total_bytes / 1e9).toFixed(1)} GB
    </small>}
    {state.error && <small className="error">{state.error}</small>}</div>
  </div>;
}
