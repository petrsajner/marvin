import { translate } from "../i18n";
import { useEffect, useState, useSyncExternalStore } from "react";
import { Check, LoaderCircle, AlertCircle } from "lucide-react";
import { getActivities, subscribeActivity } from "../activity";

export function ActivityFeedback({ cs }: { cs: boolean }) {
  const activities = useSyncExternalStore(subscribeActivity, getActivities);
  const [now, setNow] = useState(Date.now());
  const pending = activities.filter((item) => !item.outcome);
  useEffect(() => {
    if (!pending.length) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [pending.length]);
  const item = pending[0] || activities.at(-1);
  if (!item) return null;
  return <div className={"activity-feedback " + (item.outcome || "pending")} role="status">
    {!item.outcome ? <LoaderCircle className="spin" /> : item.outcome === "failed" ? <AlertCircle /> : <Check />}
    <span>{translate(item.label, cs ? "cs" : "en")}{item.outcome ? (item.outcome === "failed" ? (translate(": failed", cs ? "cs" : "en")) : (translate(": confirmed", cs ? "cs" : "en"))) : ""}</span>
    {!item.outcome && <small>{Math.max(0, Math.floor((now - item.started) / 1000))} s{pending.length > 1 ? ` · +${pending.length - 1}` : ""}</small>}
  </div>;
}
