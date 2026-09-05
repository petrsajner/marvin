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
    <span>{item.label[cs ? 1 : 0]}{item.outcome ? (item.outcome === "failed" ? (cs ? ": selhalo" : ": failed") : (cs ? ": potvrzeno" : ": confirmed")) : ""}</span>
    {!item.outcome && <small>{Math.max(0, Math.floor((now - item.started) / 1000))} s{pending.length > 1 ? ` · +${pending.length - 1}` : ""}</small>}
  </div>;
}
