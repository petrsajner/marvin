export type Activity = { id: number; label: [string, string]; started: number; outcome?: "accepted" | "failed" };
let sequence = 0;
let snapshot: Activity[] = [];
const listeners = new Set<() => void>();
const buttons = new Map<HTMLElement, number>();
const publish = () => listeners.forEach((listener) => listener());
export const subscribeActivity = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };
export const getActivities = () => snapshot;

function labelFor(path: string): [string, string] {
  const labels: [RegExp, string, string][] = [
    [/runtime\/start/, "Starting model", "Spouštění modelu"],
    [/runtime\/restart/, "Restarting model", "Restart modelu"],
    [/runtime\/stop/, "Stopping model", "Zastavování modelu"],
    [/attachments/, "Uploading attachments", "Nahrávání příloh"],
    [/export/, "Exporting document", "Export dokumentu"],
    [/import/, "Importing data", "Import dat"],
    [/compress/, "Preparing compression", "Příprava komprese"],
    [/handoff/, "Preparing handoff", "Příprava předání"],
    [/restore/, "Restoring files", "Obnova souborů"],
    [/checkpoint/, "Creating restore point", "Vytváření bodu obnovy"],
    [/settings/, "Saving settings", "Ukládání nastavení"],
    [/memory/, "Saving memory", "Ukládání paměti"],
    [/delete/, "Deleting", "Mazání"],
    [/rename/, "Renaming", "Přejmenování"],
    [/move/, "Moving conversation", "Přesun konverzace"],
    [/submit/, "Sending message", "Odesílání zprávy"],
    [/stop/, "Stopping task", "Zastavování úlohy"],
    [/preview|library|read_skill/, "Loading content", "Načítání obsahu"],
    [/maintenance/, "Starting maintenance", "Spouštění údržby"],
    [/backup/, "Preparing backup", "Příprava zálohy"],
    [/pick/, "Selecting a file or folder", "Výběr souboru nebo složky"],
    [/\/open/, "Opening file", "Otevírání souboru"],
    [/\/run/, "Starting program", "Spouštění programu"],
    [/projects/, "Updating project", "Aktualizace projektu"],
    [/sessions/, "Updating conversation", "Aktualizace konverzace"],
  ];
  const match = labels.find(([pattern]) => pattern.test(path));
  return match ? [match[1], match[2]] : ["Processing request", "Zpracování požadavku"];
}

export function beginActivity(path: string, method: string) {
  if (path.endsWith("/actions/draft") || (method === "GET" && !/preview|library|read_skill/.test(path))) return () => {};
  const id = ++sequence;
  const entry: Activity = { id, label: labelFor(path), started: Date.now() };
  const button = document.activeElement?.closest("button") as HTMLElement | null;
  if (button) {
    buttons.set(button, (buttons.get(button) || 0) + 1);
    button.classList.add("action-pending");
    button.setAttribute("aria-busy", "true");
  }
  snapshot = [...snapshot.filter((item) => !item.outcome), entry];
  publish();
  return (failed = false) => {
    if (button) {
      const remaining = (buttons.get(button) || 1) - 1;
      if (remaining) buttons.set(button, remaining);
      else { buttons.delete(button); button.classList.remove("action-pending"); button.removeAttribute("aria-busy"); }
    }
    snapshot = snapshot.map((item) => item.id === id ? { ...item, outcome: failed ? "failed" : "accepted" } : item);
    publish();
    window.setTimeout(() => { snapshot = snapshot.filter((item) => item.id !== id); publish(); }, 4500);
  };
}
