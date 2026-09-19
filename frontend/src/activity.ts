export type Activity = { id: number; label: string; started: number; outcome?: "accepted" | "failed" };
let sequence = 0;
let snapshot: Activity[] = [];
const listeners = new Set<() => void>();
const buttons = new Map<HTMLElement, number>();
const publish = () => listeners.forEach((listener) => listener());
export const subscribeActivity = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };
export const getActivities = () => snapshot;

function labelFor(path: string): string {
  const labels: [RegExp, string][] = [
    // Ahead of the generic /run/ and /projects/ patterns below.
    [/checks\/run/, "Running project checks"],
    [/checks\/fix/, "Starting check repair"],
    [/runtime\/start/, "Starting model"],
    [/runtime\/restart/, "Restarting model"],
    [/runtime\/stop/, "Stopping model"],
    [/attachments/, "Uploading attachments"],
    [/export/, "Exporting document"],
    [/import/, "Importing data"],
    [/compress/, "Preparing compression"],
    [/handoff/, "Preparing handoff"],
    [/restore/, "Restoring files"],
    [/checkpoint/, "Creating restore point"],
    [/settings/, "Saving settings"],
    [/memory/, "Saving memory"],
    [/delete/, "Deleting"],
    [/rename/, "Renaming"],
    [/move/, "Moving conversation"],
    [/submit/, "Sending message"],
    [/stop_process/, "Stopping the background process"],
    [/stop/, "Stopping task"],
    [/preview|library|read_skill/, "Loading content"],
    [/maintenance/, "Starting maintenance"],
    [/backup/, "Preparing backup"],
    [/pick/, "Selecting a file or folder"],
    [/\/open/, "Opening file"],
    [/\/run/, "Starting program"],
    [/projects/, "Updating project"],
    [/sessions/, "Updating conversation"],
  ];
  const match = labels.find(([pattern]) => pattern.test(path));
  return match ? match[1] : "Processing request";
}

export function beginActivity(path: string, method: string) {
  if (path.endsWith("/actions/draft") || path.endsWith("/select")
      || (method === "PATCH" && /^\/api\/projects\/[^/]+$/.test(path))
      || (method === "GET" && !/preview|library|read_skill/.test(path))) return () => {};
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
