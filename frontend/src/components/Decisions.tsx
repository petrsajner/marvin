import { useState } from "react";
import { Save, FileText, MessageSquare } from "lucide-react";

export function DecisionEditor({ items, tr, enabled, save, openChat }: any) {
  const [draft, setDraft] = useState(""),
    [editing, setEditing] = useState<string | null>(null),
    [status, setStatus] = useState("accepted");
  return (
    <>
      <label>
        {tr("Decision")}
        <textarea
          className="memory-editor"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
      </label>
      <div className="row">
        <select
          aria-label={tr("Decision status")}
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="accepted">{tr("Accepted")}</option>
          <option value="proposed">{tr("Proposed")}</option>
          <option value="retired">{tr("Retired")}</option>
        </select>
        <button
          className="positive"
          disabled={!enabled || !draft.trim()}
          onClick={async () => {
            const result = await save({ id: editing, text: draft, status });
            if (result) {
              setDraft("");
              setEditing(null);
            }
          }}
        >
          <Save />
          {tr("Save decision")}
        </button>
      </div>
      {items.map((item: any) => (
        <section className="decision" key={item.id}>
          <p>{item.text}</p>
          <div className="row">
            <small>{item.status}</small>
            <button
              onClick={() => {
                setDraft(item.text);
                setEditing(item.id);
                setStatus(item.status);
              }}
            >
              <FileText />
              {tr("Edit")}
            </button>
            <button onClick={() => openChat(item.source_session)}>
              <MessageSquare />
              {tr("Source conversation")}
            </button>
          </div>
        </section>
      ))}
    </>
  );
}
