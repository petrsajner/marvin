import { translate } from "../i18n";
import { memo, useState, type ReactNode } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Bot,
  X,
  Copy,
  RotateCw,
  FileText,
  Check,
  AlertCircle,
  GitCompare,
  History,
} from "lucide-react";
import { ChangeRow, FileItem, Message, imageFile } from "../api";

// A fenced block with its language named and one click to copy: the code a
// task produces is a result, not decoration.
const CodeBlock = ({
  children,
  cs,
}: {
  children?: ReactNode;
  cs: boolean;
}) => {
  const [copied, setCopied] = useState(false);
  const code = children as any;
  const language =
    /language-([\w+-]+)/.exec(code?.props?.className || "")?.[1] || "";
  const text = String(code?.props?.children ?? "");
  return (
    <div className="code-block">
      <div className="code-block-bar">
        <span className="code-lang">
          {language || translate("Code", cs ? "cs" : "en")}
        </span>
        <button
          onClick={() => {
            navigator.clipboard.writeText(text);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }}
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {translate(copied ? "Copied" : "Copy code", cs ? "cs" : "en")}
        </button>
      </div>
      <pre>{children}</pre>
    </div>
  );
};

export const Attachment = memo(
  ({
    file,
    open,
    remove,
    cs,
  }: {
    file: FileItem;
    open: () => void;
    remove?: () => void;
    cs: boolean;
  }) => (
    <div className="attachment">
      <button
        className="thumbnail"
        aria-label={(translate("Enlarge ", cs ? "cs" : "en")) + file.name}
        onClick={open}
      >
        {imageFile(file) ? (
          <img src={file.url} alt={file.name} />
        ) : (
          <FileText />
        )}
      </button>
      {remove && (
        <button
          className="remove"
          aria-label={(translate("Remove ", cs ? "cs" : "en")) + file.name}
          onClick={remove}
        >
          <X />
        </button>
      )}
      <span>{file.name}</span>
    </div>
  ),
);
export const ChatMessage = memo(
  ({
    message: m,
    cs,
    openFile,
    openSource,
    retry,
    helpWith,
    onDiff,
    onRestore,
  }: {
    message: Message;
    cs: boolean;
    openFile: (f: FileItem) => void;
    openSource: (id: string) => void;
    retry: () => void;
    helpWith?: (detail: string) => void;
    onDiff: (row: ChangeRow) => void;
    onRestore: (row: ChangeRow) => void;
  }) => {
    if (m.role === "tool")
      return (
        <details className="tool-message">
          <summary>
            {m.tool_status === "error" ? (
              <AlertCircle size={13} className="amber" />
            ) : (
              <Check size={13} />
            )}{" "}
            {m.name}
          </summary>
          <pre>{m.content}</pre>
          {m.tool_status === "error" && (
            <>
              {(m as any).hint && <p>{translate((m as any).hint, cs ? "cs" : "en")}</p>}
              {helpWith && (
                <button onClick={() => helpWith(String(m.content || ""))}>
                  {translate("Work out what to do", cs ? "cs" : "en")}
                </button>
              )}
            </>
          )}
        </details>
      );
    return (
      <article className={"message " + m.role}>
        <div className="message-label">
          {m.role === "assistant" ? (
            <>
              <Bot />
              Marvin
            </>
          ) : cs ? (
            "Vy"
          ) : (
            "You"
          )}
          <time>
            {m.created
              ? new Date(m.created * 1000).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })
              : ""}
          </time>
        </div>
        <div className="message-content">
          {m.reasoning && (
            <details>
              <summary>{translate("Thinking", cs ? "cs" : "en")}</summary>
              <Markdown remarkPlugins={[remarkGfm]}>{m.reasoning}</Markdown>
            </details>
          )}
          {m.content && (
            <Markdown
              remarkPlugins={[remarkGfm]}
              components={{
                a: ({ href, children }) =>
                  href?.startsWith("#source-") ? (
                    <button
                      className="citation"
                      onClick={() => openSource(href.slice(8))}
                    >
                      {children}
                    </button>
                  ) : (
                    <a href={href} target="_blank" rel="noreferrer">
                      {children}
                    </a>
                  ),
                pre: ({ children }) => <CodeBlock cs={cs}>{children}</CodeBlock>,
              }}
            >
              {String(m.content).replace(/\[(S\d+)\]/g, "[$1](#source-$1)")}
            </Markdown>
          )}
          {!!m.changes?.length && (
            <div className="change-card">
              <strong>{translate("What I changed", cs ? "cs" : "en")}</strong>
              {m.changes.map((row) => (
                <div className="change-row" key={row.path}>
                  <span aria-hidden="true">
                    {row.change === "created"
                      ? "🆕"
                      : row.change === "deleted"
                        ? "🗑"
                        : "✏️"}
                  </span>
                  <div>
                    <strong>{row.path}</strong>
                    <small>
                      {row.note ||
                        translate(
                          row.change === "created"
                            ? "Created this file."
                            : row.change === "deleted"
                              ? "Deleted this file."
                              : "Updated this file.",
                          cs ? "cs" : "en",
                        )}
                    </small>
                  </div>
                  <button
                    className="icon"
                    aria-label={translate("Show changes", cs ? "cs" : "en")}
                    title={translate("Show changes", cs ? "cs" : "en")}
                    onClick={() => onDiff(row)}
                  >
                    <GitCompare />
                  </button>
                  <button
                    className="icon"
                    aria-label={translate("Restore", cs ? "cs" : "en")}
                    title={translate("Restore", cs ? "cs" : "en")}
                    onClick={() => onRestore(row)}
                  >
                    <History />
                  </button>
                </div>
              ))}
            </div>
          )}
          {m.files && (
            <div className="attachment-list">
              {m.files.map((f) => (
                <Attachment
                  key={f.id}
                  file={f}
                  open={() => openFile(f)}
                  cs={cs}
                />
              ))}
            </div>
          )}
        </div>
        {m.role === "assistant" && (
          <div className="message-actions">
            <button
              onClick={() => navigator.clipboard.writeText(m.content || "")}
            >
              <Copy />
              {translate("Copy", cs ? "cs" : "en")}
            </button>
            <button onClick={retry}>
              <RotateCw />
              {translate("Retry", cs ? "cs" : "en")}
            </button>
          </div>
        )}
      </article>
    );
  },
);

// Dialogs use the same real service actions as the toolbar and slash commands.
