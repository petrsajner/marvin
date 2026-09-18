import { translate } from "../i18n";
import React, { useEffect, useState, useRef, useCallback, memo } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Bot,
  Plus,
  Search,
  FolderOpen,
  MessageSquare,
  Settings2,
  PanelLeft,
  PanelRight,
  Ellipsis,
  Paperclip,
  ArrowUp,
  Square,
  Play,
  RotateCw,
  X,
  Copy,
  FileText,
  Download,
  History,
  Brain,
  HardDrive,
  ChevronDown,
  ChevronRight,
  Check,
  CheckCheck,
  LoaderCircle,
  Pin,
  Trash2,
  ExternalLink,
  GitBranch,
  BookOpen,
  Puzzle,
  BookmarkCheck,
  Monitor,
  ListChecks,
  AlertCircle,
  Globe,
  Archive,
  Upload,
  Save,
  Sparkles,
} from "lucide-react";
import {
  api,
  imageFile,
  visibleMessage,
  FileItem,
  Message,
  Chat,
  Job,
} from "../api";

import { DecisionEditor } from "./Decisions";
import { ModelStatus } from "./ModelStatus";
import { OperationProgress } from "./OperationProgress";

export function DialogView(props: any) {
  const {
    dialog,
    close,
    setDialog,
    app,
    chat,
    detail,
    sid,
    tr,
    cs,
    act,
    settings,
    error,
    refresh,
    setSid,
    pick,
    runtime,
    runtimeCommand,
  } = props;
  const [content, setContent] = useState(""),
    [name, setName] = useState(""),
    [scope, setScope] = useState("global"),
    [library, setLibrary] = useState<FileItem[]>([]),
    [backup, setBackup] = useState<any>({}),
    [maintenance, setMaintenance] = useState<any[]>([]),
    [page, setPage] = useState(1),
    [format, setFormat] = useState("pdf"),
    [diff, setDiff] = useState<any>(null),
    [diffMode, setDiffMode] = useState("split"),
    [busy, setBusy] = useState(false);
  const memoryDirty = useRef(false);
  const section = dialog.section || "model";
  const project = app.projects.find(
    (p: any) => p.path === chat?.meta.workspace,
  );
  const call = async (fn: () => Promise<any>) => {
    setBusy(true);
    try {
      return await fn();
    } catch (e) {
      error(e);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const modal = document.querySelector<HTMLElement>(".modal");
    const surfaces =
      document.querySelectorAll<HTMLElement>(".workspace,.topbar");
    surfaces.forEach((element) => (element.inert = true));
    modal?.querySelector<HTMLButtonElement>("button")?.focus();
    const escape = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
      if (e.key === "Tab" && modal) {
        const controls = Array.from(
          modal.querySelectorAll<HTMLElement>(
            "button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href]",
          ),
        ).filter((element) => element.getClientRects().length > 0);
        const first = controls[0],
          last = controls.at(-1);
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("keydown", escape);
      surfaces.forEach((element) => (element.inert = false));
      previous?.focus();
    };
  }, [close]);
  useEffect(() => {
    setName(dialog.type === "queue-edit" ? dialog.data.payload.text : "");
    if (dialog.type === "library")
      api("/api/sessions/" + sid + "/library")
        .then(setLibrary)
        .catch(error);
    if (dialog.type === "settings" && section === "data") {
      api("/api/backup").then(setBackup).catch(error);
      api("/api/maintenance").then(setMaintenance).catch(error);
    }
  }, [dialog.type, section, sid, error]);
  useEffect(() => {
    if (
      dialog.type === "settings" &&
      section === "memory" &&
      !memoryDirty.current
    )
      setContent(detail?.memory?.[scope]?.content || "");
  }, [dialog.type, section, scope, detail]);
  useEffect(() => {
    const file = dialog.file;
    if (
      dialog.type === "preview" &&
      file &&
      !imageFile(file) &&
      !file.name.toLowerCase().endsWith(".pdf")
    )
      api("/api/files/" + file.id + "/preview?start=" + page + "&count=50")
        .then((v) => setContent(v.content))
        .catch(error);
  }, [dialog.file, page, error]);
  const title =
    dialog.type === "settings"
      ? tr("Settings")
      : dialog.type === "preview"
        ? dialog.file.name
        : (
            {
              project: tr("Project"),
              chat: tr("Conversation"),
              "delete-chat": tr("Delete conversation"),
              "delete-project": tr("Delete project"),
              library: tr("Project documents"),
              sources: tr("Sources"),
              checkpoints: tr("Restore points"),
              export: tr("Export"),
              decisions: tr("Project decisions"),
              "queue-edit": tr("Queued message"),
              diff: (dialog.data?.path || "").split(/[\\/]/).pop() || tr("Changes"),
            } as any
          )[dialog.type] || dialog.type;
  const settingsSections = [
    ["model", "Model and device"],
    ["behavior", "Behavior"],
    ["memory", "Memory and skills"],
    ["data", "Data and backups"],
    ["appearance", "Appearance and language"],
    ["help", "Help and manuals"],
  ];
  const finishSelect = async (result: any) => {
    if (result?.session_id) setSid(result.session_id);
    await refresh();
    close();
  };
  useEffect(() => {
    if (dialog.type !== "diff") return;
    setDiff(null);
    const params = new URLSearchParams({ path: dialog.data.path });
    if (dialog.data.task_id) params.set("task_id", dialog.data.task_id);
    api("/api/sessions/" + sid + "/diff?" + params)
      .then(setDiff)
      .catch(error);
  }, [dialog.type, dialog.data, sid, error]);
  useEffect(() => {
    if (dialog.type !== "process-output") return;
    let cancelled = false;
    const load = () =>
      api("/api/sessions/" + sid + "/processes/" + dialog.data.id)
        .then((result) => {
          if (!cancelled) setContent(result.output || "");
        })
        .catch(error);
    load();
    const timer = setInterval(load, 2000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [dialog.type, dialog.data?.id, sid, error]);
  useEffect(() => {
    if (dialog.type !== "settings" || section !== "data") return;
    const timer = setInterval(() => {
      api("/api/maintenance").then(setMaintenance).catch(error);
      api("/api/backup").then(setBackup).catch(error);
    }, 3000);
    return () => clearInterval(timer);
  }, [dialog.type, section, error]);
  return (
    <div
      className="modal-shade"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div
        className={
          "modal " + (dialog.type === "preview" ? "preview-modal" : "")
        }
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header>
          <h2>{title}</h2>
          <span className="spacer" />
          <button
            className="icon"
            onClick={close}
            aria-label={tr("Close")}
          >
            <X />
          </button>
        </header>
        <div
          className={
            "modal-body " +
            (dialog.type === "settings" ? "settings-layout" : "")
          }
        >
          {dialog.type === "settings" && (
            <nav>
              {settingsSections.map(([id, en]) => (
                <button
                  key={id}
                  className={section === id ? "selected" : ""}
                  onClick={() => setDialog({ ...dialog, section: id })}
                >
                  {tr(en)}
                </button>
              ))}
            </nav>
          )}
          <div className="modal-content">
            {dialog.type === "settings" && section === "model" && (
              <>
                <label>
                  {tr("Model")}
                  <select
                    value={app.preferences.model}
                    onChange={(e) =>
                      call(() => settings({ model: e.target.value }))
                    }
                  >
                    {app.models.map((m: any) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                        {!m.installed
                          ? " · " + tr("not installed")
                          : ""}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  {tr("KV cache profile")}
                  <select
                    value={
                      app.models.find(
                        (m: any) => m.id === app.preferences.model,
                      )?.profile
                    }
                    onChange={(e) =>
                      call(() =>
                        settings({
                          kv_cache_modes: {
                            ...app.preferences.kv_cache_modes,
                            [app.preferences.model]: e.target.value,
                          },
                        }),
                      )
                    }
                  >
                    {app.models
                      .find((m: any) => m.id === app.preferences.model)
                      ?.profiles.map((p: any) => (
                        <option key={p.id} value={p.id} disabled={p.fits_gpu_budget === false}>
                          {cs ? p.label_cs || p.label : p.label}
                        </option>
                      ))}
                  </select>
                </label>
                {app.models
                  .find((m: any) => m.id === app.preferences.model)
                  ?.profiles.find(
                    (p: any) =>
                      p.id ===
                      app.models.find((m: any) => m.id === app.preferences.model)?.profile,
                  )?.speculative === "mtp" && (
                  <p>
                    {tr(
                      "The MTP profile generates faster using the draft model. It needs about 2.6 GB of extra VRAM; the 1.4 GB draft model is downloaded automatically on the first start.",
                    )}
                  </p>
                )}
                <p>
                  {tr("Vision")}:{" "}
                  {app.models.find((m: any) => m.id === app.preferences.model)
                    ?.vision
                    ? tr("available")
                    : tr("text-only model")}
                </p>
                <label>
                  {tr("GPU memory budget")}
                  <select
                    value={app.preferences.vram_gb || "auto"}
                    onChange={(e) =>
                      call(() =>
                        settings({
                          vram_gb:
                            e.target.value === "auto"
                              ? "auto"
                              : Number(e.target.value),
                        }),
                      )
                    }
                  >
                    {["auto", 16, 24, 32, 48, 64, 96].map((value) => (
                      <option key={value} value={value} disabled={value !== "auto" && app.memory?.vram_detected_gb && Number(value) > Math.ceil(app.memory.vram_detected_gb)}>
                        {value === "auto"
                          ? tr("Automatic detection")
                          : value + " GB"}
                      </option>
                    ))}
                  </select>
                </label>
                <p>{tr("Changing the budget restarts the model automatically when no task is running. A compatible context or smaller model is selected when needed.")}</p>
                {app.models.find((m: any) => m.id === app.preferences.model)?.uses_system_ram && <p>{tr("This profile also uses system RAM. A smaller GPU moves more weights into RAM. Windows can reclaim memory while the model starts.")}</p>}
                <div className="row">
                  <button
                    className={app.semantic_search?.enabled ? "positive" : "outline"}
                    disabled={app.semantic_search?.preparing}
                    onClick={() =>
                      call(() =>
                        settings({
                          semantic_search: !app.semantic_search?.enabled,
                        }),
                      )
                    }
                  >
                    <Sparkles />
                    {tr("Semantic search")}
                  </button>
                </div>
                {app.semantic_search?.enabled && (
                  <p>
                    {app.semantic_search.preparing
                      ? tr("Downloading the embedding model (~635 MB)…")
                      : app.semantic_search.model_ready
                        ? app.semantic_search.server
                          ? tr("Semantic search is ready.")
                          : tr("Ready; the CPU search service starts with the first search.")
                        : tr("The embedding model will be downloaded in the background (~635 MB, CPU only).")}
                  </p>
                )}
                <p>
                  VRAM: {runtime.vram || "—"} · Python {runtime.python || "—"}
                  {app.memory && <> · {tr("Free RAM")}: {app.memory.ram_available_gb} / {app.memory.ram_total_gb} GiB</>}
                </p>
                {app.active && (
                  <p className="amber">
                    {tr("New settings apply to the next request.")}
                  </p>
                )}
                <div className="row">
                  {["start", "stop", "restart"].map((command) => (
                    <button
                      key={command}
                      className={(command === "stop" ? "danger" : "outline") +
                        (["starting", "stopping"].includes(runtime.switch?.status) && runtime.switch.command === command ? " model-busy" : "")}
                      disabled={command === "stop" ? runtime.switch?.status === "stopping" : ["starting", "stopping"].includes(runtime.switch?.status)}
                      aria-busy={["starting", "stopping"].includes(runtime.switch?.status) && runtime.switch.command === command}
                      onClick={() =>
                        call(() => runtimeCommand(command))
                      }
                    >
                      {command === "start" ? (
                        <Play />
                      ) : command === "stop" ? (
                        <Square />
                      ) : (
                        <RotateCw />
                      )}
                      {tr(command === "start" ? "Start" : command === "stop" ? "Stop" : "Restart")}
                    </button>
                  ))}
                </div>
                {app.semantic_search?.enabled && (
                  <p>
                    {app.semantic_search.preparing
                      ? tr("Downloading the embedding model (~635 MB)…")
                      : app.semantic_search.model_ready
                        ? app.semantic_search.server
                          ? tr("Semantic search is ready.")
                          : tr("Ready; the CPU search service starts with the first search.")
                        : tr("The embedding model will be downloaded in the background (~635 MB, CPU only).")}
                  </p>
                )}
                <ModelStatus runtime={runtime} cs={cs} />
              </>
            )}
            {dialog.type === "settings" && section === "behavior" && (
              <>
                <label>
                  {tr("Autonomy")}
                  <select
                    value={app.preferences.autonomy}
                    onChange={(e) =>
                      call(() => settings({ autonomy: e.target.value }))
                    }
                  >
                    {["supervised", "semi", "auto"].map((value) => (
                      <option key={value}>{value}</option>
                    ))}
                  </select>
                </label>
                <label>
                  {tr("Default message delivery")}
                  <select
                    value={app.preferences.send_mode}
                    onChange={(e) =>
                      call(() => settings({ send_mode: e.target.value }))
                    }
                  >
                    <option value="steer">
                      {tr("Clarify now")}
                    </option>
                    <option value="queue">
                      {tr("After completion")}
                    </option>
                  </select>
                </label>
                <p>
                  {tr("Drafts and received messages are saved automatically.")}
                </p>
              </>
            )}
            {dialog.type === "settings" && section === "appearance" && (
              <>
                <label>
                  {tr("Theme")}
                  <select
                    value={app.preferences.theme}
                    onChange={(e) =>
                      call(() => settings({ theme: e.target.value }))
                    }
                  >
                    <option value="dark">{tr("Dark")}</option>
                    <option value="light">{tr("Light")}</option>
                    <option value="system">
                      {tr("System")}
                    </option>
                  </select>
                </label>
                <label>
                  {tr("Language")}
                  <select
                    value={app.preferences.language}
                    onChange={(e) =>
                      call(() => settings({ language: e.target.value }))
                    }
                  >
                    <option value="en">English</option>
                    <option value="cs">{translate("Czech", "cs")}</option>
                  </select>
                </label>
                <label>
                  {tr("Spacing")}
                  <select
                    value={app.preferences.density}
                    onChange={(e) =>
                      call(() => settings({ density: e.target.value }))
                    }
                  >
                    <option value="comfortable">
                      {tr("Comfortable")}
                    </option>
                    <option value="compact">
                      {tr("Compact")}
                    </option>
                  </select>
                </label>
              </>
            )}
            {dialog.type === "settings" && section === "memory" && (
              <>
                <div className="row">
                  {["global", "mode", "project"].map((s, i) => (
                    <button
                      key={s}
                      className={scope === s ? "positive" : ""}
                      onClick={() => {
                        memoryDirty.current = false;
                        setScope(s);
                      }}
                      disabled={!detail?.memory?.[s]?.path}
                    >
                      {cs
                        ? ["Global", "Mode", "Project"].map((label) => translate(label, "cs"))[i]
                        : ["Global", "Work mode", "Project"][i]}
                    </button>
                  ))}
                </div>
                <textarea
                  className="memory-editor"
                  aria-label={tr("Memory text")}
                  value={content}
                  onChange={(e) => {
                    memoryDirty.current = true;
                    setContent(e.target.value);
                  }}
                />
                <button
                  className="positive"
                  onClick={() => call(() => act("memory", { scope, content }))}
                >
                  <Save />
                  {tr("Save memory")}
                </button>
                <h3>{tr("Skills")}</h3>
                <div className="row">
                  <button
                    onClick={() =>
                      call(() => act("open_skill_folder", { scope: "user" }))
                    }
                  >
                    <FolderOpen />
                    {tr("User skills")}
                  </button>
                  <button
                    disabled={!project}
                    onClick={() =>
                      call(() => act("open_skill_folder", { scope: "project" }))
                    }
                  >
                    <FolderOpen />
                    {tr("Project skills")}
                  </button>
                </div>
                <div className="skill-list">
                  {detail?.skills?.map((s: any) => (
                    <div key={s.name}>
                      <button
                        onClick={() =>
                          call(async () => {
                            const value = await act("read_skill", {
                              name: s.name,
                            });
                            setDialog({
                              type: "skill-content",
                              data: value.content,
                            });
                          })
                        }
                      >
                        <Puzzle />
                        {s.name}
                      </button>
                      <small>
                        {s.source} · {s.description}
                      </small>
                      <button
                        onClick={() =>
                          call(() => act("skill", { argument: s.name }))
                        }
                      >
                        {tr("Use skill")}
                      </button>
                    </div>
                  ))}
                </div>
                <label>
                  {tr("New skill topic")}
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </label>
                <button
                  onClick={() =>
                    call(() => act("skill", { argument: "new " + name }))
                  }
                >
                  <Plus />
                  {tr("Design a skill")}
                </button>
              </>
            )}
            {dialog.type === "settings" && section === "data" && (
              <>
                <h3>
                  {tr("Projects and conversations")}
                </h3>
                <div className="row">
                  <button
                    disabled={!project}
                    onClick={() =>
                      call(async () => {
                        const file = await api(
                          "/api/projects/" + project.id + "/export",
                          "POST",
                          { session_id: sid },
                        );
                        setDialog({ type: "preview", file });
                      })
                    }
                  >
                    <Download />
                    {tr("Export project")}
                  </button>
                  <label className="file-picker">
                    <Upload />
                    {tr("Import project")}
                    <input
                      type="file"
                      accept=".zip"
                      onChange={(e) =>
                        call(async () => {
                          const file = e.target.files?.[0];
                          if (!file) return;
                          const form = new FormData();
                          form.append("file", file);
                          const stored = await api(
                            "/api/sessions/" + sid + "/attachments",
                            "POST",
                            form,
                          );
                          return finishSelect(
                            await api("/api/projects/import", "POST", {
                              file_id: stored.id,
                            }),
                          );
                        })
                      }
                    />
                  </label>
                  <label className="file-picker">
                    <Upload />
                    {tr("Import chat JSONL")}
                    <input
                      type="file"
                      accept=".jsonl"
                      onChange={(e) =>
                        call(async () => {
                          const file = e.target.files?.[0];
                          if (!file) return;
                          const form = new FormData();
                          form.append("file", file);
                          const stored = await api(
                            "/api/sessions/" + sid + "/attachments",
                            "POST",
                            form,
                          );
                          return finishSelect(
                            await api(
                              "/api/sessions/" + sid + "/import-chat",
                              "POST",
                              { file_id: stored.id },
                            ),
                          );
                        })
                      }
                    />
                  </label>
                </div>
                <h3>
                  {tr("Model and runtime backup")}
                </h3>
                <p>
                  {tr("Internet first, local backup when a download fails.")}
                </p>
                <p className="path">
                  {backup.path ||
                    tr("No fallback selected")}
                </p>
                <div className="row">
                  {["create", "select", "verify", "clear"].map((op, i) => (
                    <button
                      key={op}
                      onClick={() =>
                        call(async () => {
                          let path = backup.path;
                          if (op === "create" || op === "select")
                            path = await pick(true);
                          if (!path && op !== "clear") return;
                          const value = await api("/api/backup/" + op, "POST", {
                            path,
                            session_id: sid,
                          });
                          setBackup(await api("/api/backup"));
                          setMaintenance(await api("/api/maintenance"));
                          return value;
                        })
                      }
                    >
                      {[<Plus />, <FolderOpen />, <CheckCheck />, <X />][i]}
                      {cs
                        ? ["Create","Select","Verify","Clear"].map((label) => translate(label, "cs"))[i]
                        : ["Create", "Select", "Verify", "Clear"][i]}
                    </button>
                  ))}
                </div>
                {maintenance.map((p) => (
                  <OperationProgress key={p.process_id} process={p} cs={cs} />
                ))}
                <button
                  onClick={() =>
                    api("/api/maintenance").then(setMaintenance).catch(error)
                  }
                >
                  <RotateCw />
                  {tr("Refresh operations")}
                </button>
              </>
            )}
            {dialog.type === "settings" && section === "help" && (
              <>
                <h3>Marvin v{app.version}</h3>
                <p>Python 3.12 · Windows · llama.cpp</p>
                <div className="row">
                  <a className="button" href="/api/manual/en" target="_blank">
                    <BookOpen />
                    English PDF
                  </a>
                  <a className="button" href="/api/manual/cs" target="_blank">
                    <BookOpen />
                    {tr("Czech PDF")}
                  </a>
                </div>
                <h3>{tr("Commands")}</h3>
                {Object.entries(app.commands).map(([key, value]) => (
                  <p key={key}>
                    <code>{key}</code> · {tr(String(value))}
                  </p>
                ))}
              </>
            )}
            {dialog.type === "project" && (
              <>
                <label>
                  {tr("New project name")}
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </label>
                <button
                  className="positive"
                  disabled={!name.trim()}
                  onClick={() =>
                    call(async () =>
                      finishSelect(
                        await api("/api/projects", "POST", {
                          name,
                          mode: chat?.meta.work_mode || "discussion",
                        }),
                      ),
                    )
                  }
                >
                  <Plus />
                  {tr("Create project")}
                </button>
                <button
                  onClick={() =>
                    call(async () => {
                      const path = await pick(true);
                      if (path)
                        return finishSelect(
                          await api("/api/projects", "POST", { path }),
                        );
                    })
                  }
                >
                  <FolderOpen />
                  {tr("Attach existing folder")}
                </button>
                {project && (
                  <>
                    <label>
                      <input
                        type="checkbox"
                        checked={!!project.autocommit}
                        onChange={(e) =>
                          call(() =>
                            api(
                              "/api/projects/" + project.id,
                              "PATCH",
                              { autocommit: e.target.checked },
                            ),
                          )
                        }
                      />{" "}
                      {tr("Commit each finished task automatically")}
                    </label>
                    <p className="muted">
                      {tr(
                        "When enabled, every successfully finished Development or Computer task commits its own changed files in this project. Never pushes.",
                      )}
                    </p>
                    <div className="danger-zone">
                      <p className="path">{project.path}</p>
                      <button
                        className="danger"
                        onClick={() =>
                          setDialog({ type: "delete-project", data: project })
                        }
                      >
                        <Trash2 />
                        {project.managed
                          ? tr("Delete project and folder")
                          : tr("Remove project")}
                      </button>
                    </div>
                  </>
                )}
              </>
            )}
            {dialog.type === "delete-project" && (
              <>
                <p>
                  {dialog.data.managed
                    ? tr("Delete this project, its files and conversations?")
                    : tr("Remove this project and its conversations? The folder stays on disk.")}
                </p>
                <p className="path">{dialog.data.path}</p>
                <button
                  className="danger"
                  onClick={() =>
                    call(async () =>
                      finishSelect(
                        await api("/api/projects/" + dialog.data.id, "DELETE"),
                      ),
                    )
                  }
                >
                  <Trash2 />
                  {tr("Delete")}
                </button>
              </>
            )}
            {dialog.type === "chat" && (
              <>
                <label>
                  {tr("Move to project")}
                  <select
                    value={project?.id || ""}
                    onChange={(e) =>
                      call(async () => {
                        await act("move", {
                          project_id: e.target.value || null,
                        });
                        close();
                      })
                    }
                  >
                    <option value="">{tr("No project")}</option>
                    {app.projects.map((p: any) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="row">
                  <button onClick={() => call(() => act("undo"))}>
                    <History />
                    {tr("Undo last turn")}
                  </button>
                  <button
                    onClick={() =>
                      call(async () => finishSelect(await act("fork")))
                    }
                  >
                    <GitBranch />
                    {tr("Branch")}
                  </button>
                  <button onClick={() => setDialog({ type: "export" })}>
                    <Download />
                    {tr("Export")}
                  </button>
                  <button
                    className="danger"
                    onClick={() => setDialog({ type: "delete-chat" })}
                  >
                    <Trash2 />
                    {tr("Delete chat")}
                  </button>
                </div>
              </>
            )}
            {dialog.type === "delete-chat" && (
              <>
                <p>
                  {tr("Delete this conversation and its attachments?")}
                </p>
                <button
                  className="danger"
                  onClick={() =>
                    call(async () => {
                      await act("delete");
                      const next = await api("/api/state");
                      setSid(next.session_id);
                      await refresh();
                      close();
                    })
                  }
                >
                  {tr("Delete")}
                </button>
              </>
            )}
            {dialog.type === "preview" && (
              <>
                <div className="preview-toolbar">
                  {/\.(py|exe|bat|cmd|ps1)$/i.test(dialog.file.name) && (
                    <button
                      className="positive"
                      onClick={() =>
                        call(() =>
                          api("/api/files/" + dialog.file.id + "/run", "POST"),
                        )
                      }
                    >
                      <Play />
                      {tr("Run")}
                    </button>
                  )}
                  <button
                    onClick={() =>
                      api(
                        "/api/files/" + dialog.file.id + "/open",
                        "POST",
                        {},
                      ).catch(error)
                    }
                  >
                    <ExternalLink />
                    {tr("Open file")}
                  </button>
                  <button
                    onClick={() =>
                      api("/api/files/" + dialog.file.id + "/open", "POST", {
                        folder: true,
                      }).catch(error)
                    }
                  >
                    <FolderOpen />
                    {tr("Open folder")}
                  </button>
                  <a
                    className="button"
                    href={dialog.file.url + "?download=true"}
                    download
                  >
                    <Download />
                    {tr("Download")}
                  </a>
                </div>
                {/\.html?$/i.test(dialog.file.name) ? (
                  <iframe
                    className="pdf-preview"
                    title={dialog.file.name}
                    sandbox="allow-scripts allow-forms allow-downloads"
                    src={
                      "/api/preview/" +
                      dialog.file.id +
                      "/" +
                      encodeURIComponent(dialog.file.path.split(/[\\/]/).at(-1))
                    }
                  />
                ) : imageFile(dialog.file) ? (
                  <img
                    className="large-image"
                    src={dialog.file.url}
                    alt={dialog.file.name}
                  />
                ) : dialog.file.name.toLowerCase().endsWith(".pdf") ? (
                  <iframe
                    className="pdf-preview"
                    title={dialog.file.name}
                    src={dialog.file.url}
                  />
                ) : (
                  <>
                    <pre className="document-preview">{content}</pre>
                    <div className="row">
                      <button
                        disabled={page <= 1}
                        onClick={() => setPage((p) => Math.max(1, p - 50))}
                      >
                        {tr("Previous range")}
                      </button>
                      <span>
                        {page}–{page + 49}
                      </span>
                      <button onClick={() => setPage((p) => p + 50)}>
                        {tr("Next range")}
                      </button>
                    </div>
                  </>
                )}
              </>
            )}
            {dialog.type === "export" && (
              <>
                <label>
                  {tr("Format")}
                  <select
                    value={format}
                    onChange={(e) => setFormat(e.target.value)}
                  >
                    <option value="pdf">PDF</option>
                    <option value="docx">Word</option>
                    <option value="md">Markdown</option>
                    <option value="jsonl">JSONL</option>
                  </select>
                </label>
                <button
                  className="positive"
                  onClick={() =>
                    call(async () =>
                      setDialog({
                        type: "preview",
                        file: await act("export", { format }),
                      }),
                    )
                  }
                >
                  <Download />
                  {tr("Export")}
                </button>
              </>
            )}
            {dialog.type === "library" && (
              <>
                <div className="library">
                  {library.map((file) => (
                    <div className="file-row" key={file.id}>
                      <FileText />
                      <button
                        onClick={() => setDialog({ type: "preview", file })}
                      >
                        {file.name}
                      </button>
                      <button
                        className="icon"
                        title={tr("Pin")}
                        onClick={() =>
                          call(() => act("pin", { path: file.path }))
                        }
                      >
                        <Pin />
                      </button>
                    </div>
                  ))}
                </div>
                <button
                  onClick={() =>
                    call(async () => {
                      const path = await pick(false);
                      if (path) await act("pin", { path });
                    })
                  }
                >
                  <Plus />
                  {tr("Pin a file")}
                </button>
              </>
            )}
            {dialog.type === "sources" && (
              <div className="sources">
                {detail?.research?.sources
                  ?.filter((s: any) => !dialog.data || s.id === dialog.data)
                  .map((s: any) => (
                    <section key={s.id}>
                      <h3>
                        [{s.id}] {s.title}
                      </h3>
                      <a href={s.url} target="_blank" rel="noreferrer">
                        {s.url}
                      </a>
                      <p className="muted">
                        {tr("Loaded")} ·{" "}
                        {new Date(s.fetched_at * 1000).toLocaleString()}
                      </p>
                      <pre>{s.content}</pre>
                    </section>
                  ))}
                {!dialog.data &&
                  detail?.research?.candidates
                    ?.filter(
                      (c: any) =>
                        !detail.research.sources.some(
                          (s: any) => s.url === c.url,
                        ),
                    )
                    .map((c: any) => (
                      <section key={c.url}>
                        <h3>{c.title}</h3>
                        <a href={c.url} target="_blank" rel="noreferrer">
                          {c.url}
                        </a>
                        <p>{tr("Found, not loaded")}</p>
                      </section>
                    ))}
              </div>
            )}
            {dialog.type === "checkpoints" && (
              <>
                <label>
                  {tr("New restore point")}
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </label>
                <button
                  className="positive"
                  onClick={() =>
                    call(() => act("checkpoint", { argument: name }))
                  }
                >
                  <Plus />
                  {tr("Create")}
                </button>
                {detail?.checkpoints?.map((cp: any) => (
                  <div className="file-row" key={cp.id}>
                    <History />
                    <div>
                      <strong>{cp.label}</strong>
                      <small>
                        {cp.files} {tr("files")} ·{" "}
                        {new Date(cp.created * 1000).toLocaleString()}
                      </small>
                    </div>
                    <button
                      disabled={cp.restored}
                      onClick={() =>
                        call(async () => {
                          const result = await act("restore", { id: cp.id });
                          if (result.errors?.length && window.confirm(tr("Some files changed after this checkpoint. Replace them with the saved versions?"))) {
                            const forced = await act("restore", { id: cp.id, force: true });
                            if (forced.errors?.length) error(forced.errors.join("\n"));
                          } else if (result.errors?.length)
                            error(result.errors.join("\n"));
                        })
                      }
                    >
                      {cp.restored
                        ? tr("Restored")
                        : tr("Restore")}
                    </button>
                  </div>
                ))}
              </>
            )}
            {dialog.type === "queue-edit" && (
              <>
                <textarea
                  className="memory-editor"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
                <button
                  className="positive"
                  onClick={() =>
                    call(async () => {
                      await api("/api/queue/" + dialog.data.id, "PATCH", {
                        text: name,
                      });
                      await refresh();
                      close();
                    })
                  }
                >
                  <Save />
                  {tr("Save")}
                </button>
              </>
            )}
            {dialog.type === "skill-content" && (
              <Markdown remarkPlugins={[remarkGfm]}>{dialog.data}</Markdown>
            )}
            {dialog.type === "process-output" && (
              <pre className="document-preview">{content}</pre>
            )}
            {dialog.type === "diff" && (
              <>
                <div className="row">
                  <button
                    className={diffMode === "split" ? "positive" : "outline"}
                    onClick={() => setDiffMode("split")}
                  >
                    {tr("Side by side")}
                  </button>
                  <button
                    className={diffMode === "unified" ? "positive" : "outline"}
                    onClick={() => setDiffMode("unified")}
                  >
                    {tr("Unified")}
                  </button>
                  <span className="spacer" />
                  <button
                    className="danger"
                    disabled={!diff || diff.undone}
                    onClick={() =>
                      call(async () => {
                        const result = await act("restore_file", {
                          path: dialog.data.path,
                          task_id: dialog.data.task_id,
                        });
                        if (
                          result?.errors?.length &&
                          window.confirm(
                            tr(
                              "The file changed after this task. Restore the original version anyway?",
                            ),
                          )
                        ) {
                          await act("restore_file", {
                            path: dialog.data.path,
                            task_id: dialog.data.task_id,
                            force: true,
                          });
                        }
                        const params = new URLSearchParams({
                          path: dialog.data.path,
                        });
                        if (dialog.data.task_id)
                          params.set("task_id", dialog.data.task_id);
                        setDiff(
                          await api(
                            "/api/sessions/" +
                              sid +
                              "/diff?" +
                              params,
                          ),
                        );
                      })
                    }
                  >
                    <History />
                    {tr("Restore this file")}
                  </button>
                </div>
                {diff?.changed_after && (
                  <p className="amber">
                    {tr(
                      "The file was changed after this task; restoring may overwrite newer edits.",
                    )}
                  </p>
                )}
                {diff?.binary && (
                  <p>{tr("Binary file; content preview is not available.")}</p>
                )}
                {!diff && <p>{tr("Loading…")}</p>}
                {diff && !diff.binary && (
                  <div className="diff-body">
                    <table className={"diff-table " + diffMode}>
                      <tbody>
                        {(diff.lines || []).map(
                          (line: any, index: number) =>
                            line.tag === "gap" ? (
                              <tr key={index} className="diff-gap">
                                <td colSpan={diffMode === "split" ? 4 : 3}>
                                  ⋯ {line.count}
                                </td>
                              </tr>
                            ) : diffMode === "split" ? (
                              <tr key={index}>
                                <td className="diff-num">{line.a ?? ""}</td>
                                <td
                                  className={
                                    "diff-side " +
                                    (line.tag === "-" ? "diff-del" : "")
                                  }
                                >
                                  {line.tag === "+" ? "" : line.text}
                                </td>
                                <td className="diff-num">{line.b ?? ""}</td>
                                <td
                                  className={
                                    "diff-side " +
                                    (line.tag === "+" ? "diff-add" : "")
                                  }
                                >
                                  {line.tag === "-" ? "" : line.text}
                                </td>
                              </tr>
                            ) : (
                              <tr key={index}>
                                <td className="diff-num">{line.a ?? ""}</td>
                                <td className="diff-num">{line.b ?? ""}</td>
                                <td
                                  className={
                                    "diff-side " +
                                    (line.tag === "+"
                                      ? "diff-add"
                                      : line.tag === "-"
                                        ? "diff-del"
                                        : "")
                                  }
                                >
                                  {line.tag === " " ? "" : line.tag}{" "}
                                  {line.text}
                                </td>
                              </tr>
                            ),
                        )}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
            {dialog.type === "context-snapshot" && (
              <>
                <p>
                  {dialog.data.model} · {dialog.data.work_mode} ·{" "}
                  {new Date(dialog.data.created * 1000).toLocaleString()}
                </p>
                {dialog.data.memory.map((memory: any) => (
                  <section key={memory.scope}>
                    <h3>
                      {memory.scope} · {memory.sha256.slice(0, 10)}
                    </h3>
                    <Markdown remarkPlugins={[remarkGfm]}>
                      {memory.content}
                    </Markdown>
                  </section>
                ))}
              </>
            )}
            {dialog.type === "decisions" && (
              <DecisionEditor
                items={detail?.decisions || []}
                tr={tr}
                enabled={!!project}
                save={(value: any) => call(() => act("decision", value))}
                openChat={(id: string) => {
                  setSid(id);
                  close();
                }}
              />
            )}
            {busy && (
              <div className="busy">
                <LoaderCircle className="spin" />
                {tr("Working…")}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
