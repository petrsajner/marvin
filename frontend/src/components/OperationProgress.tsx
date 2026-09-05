import { useEffect, useRef, useState } from "react";
import { LoaderCircle, Check, AlertCircle } from "lucide-react";
import { api } from "../api";

export function OperationProgress({ process, cs }: { process: any; cs: boolean }) {
  const [state, setState] = useState(process);
  const [output, setOutput] = useState("");
  const [error, setError] = useState("");
  const cursor = useRef(0);
  useEffect(() => {
    let disposed = false, pending = false;
    const load = async () => {
      if (pending) return;
      pending = true;
      try {
        const result = await api(`/api/maintenance/${process.process_id}?cursor=${cursor.current}`);
        if (disposed) return;
        cursor.current = result.cursor;
        setState(result);
        setError("");
        if (result.output) setOutput((old) => (old + result.output).slice(-6000));
        if (result.status !== "running") clearInterval(timer);
      } catch (e) { if (!disposed) setError(String(e)); }
      finally { pending = false; }
    };
    const timer = window.setInterval(load, 2000);
    load();
    return () => { disposed = true; clearInterval(timer); };
  }, [process.process_id]);
  const running = state.status === "running";
  const failed = state.exit_code != null && state.exit_code !== 0;
  const title = /\sverify\s/.test(process.command || "") ? (cs ? "Ověření zálohy" : "Backup verification") : (cs ? "Vytváření zálohy" : "Creating backup");
  return <section className="operation-progress" aria-busy={running}>
    <div className="row">{running ? <LoaderCircle className="spin" /> : failed ? <AlertCircle /> : <Check />}
      <strong>{title}</strong><span>{Math.round(state.elapsed_seconds || 0)} s</span>
      {!running && <span>{failed ? (cs ? "Selhalo" : "Failed") : (cs ? "Dokončeno" : "Complete")}</span>}
    </div>
    {error && <p className="error">{error}</p>}
    {output && <pre>{output}</pre>}
  </section>;
}
