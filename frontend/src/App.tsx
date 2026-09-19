import { translate } from "./i18n";
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
  Mic,
  Paperclip,
  ArrowUp,
  Square,
  Play,
  RotateCw,
  CircleDashed,
  Lightbulb,
  Wrench,
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
  GitCompare,
} from "lucide-react";
import {
  api,
  imageFile,
  visibleMessage,
  FileItem,
  Message,
  Chat,
  Job,
} from "./api";

import { Attachment, ChatMessage } from "./components/Messages";
import { DialogView, SETTINGS_SECTIONS } from "./components/Dialogs";
import { ResizeHandle } from "./components/ResizeHandle";
import { ActivityFeedback } from "./components/ActivityFeedback";

type Dialog = { type: string; file?: FileItem; section?: string; data?: any };
const COPYRIGHT = "© Petr Sajner 2026";
// Documents a preview can render, as opposed to code or binaries.
const READABLE = /\.(md|markdown|txt|rst|docx|pdf|html?|csv|xlsx)$/i;
// Measured against what the server actually tokenised, not assumed. Keep this in
// step with Session.CHARS_PER_TOKEN, or the two context figures disagree again.
const CHARS_PER_TOKEN = 3.2;
const phases: Record<string, string> = {
  preparing: "Preparing request",
  reading_context: "Reading context",
  generating: "Generating",
  loading_model: "Loading model",
  thinking: "Thinking",
  answering: "Writing answer",
  preparing_tool: "Preparing action",
  executing: "Running action",
  idle: "Ready",
};

export function App() {
  const [leftWidth, setLeftWidth] = useState<number>();
  const [rightWidth, setRightWidth] = useState<number>();
  const [chatLimit, setChatLimit] = useState(20);
  const runtimeGeneration = useRef(0);
  const [app, setApp] = useState<any>(null),
    [sid, setSid] = useState(""),
    [chat, setChat] = useState<Chat | null>(null),
    [detail, setDetail] = useState<any>(null),
    [runtime, setRuntime] = useState<any>({}),
    [tab, setTab] = useState("results"),
    [panel, setPanel] = useState(true),
    [nav, setNav] = useState(false);
  const [dialog, setDialog] = useState<Dialog | null>(null),
    [text, setText] = useState(""),
    [attachments, setAttachments] = useState<FileItem[]>([]),
    [uploading, setUploading] = useState(0);
  const [toast, setToast] = useState(""),
    [search, setSearch] = useState(""),
    [searchResults, setSearchResults] = useState<any[] | null>(null),
    [findings, setFindings] = useState<any[] | null>(null),
    [sending, setSending] = useState(false),
    [delivery, setDelivery] = useState("steer"),
    [connected, setConnected] = useState(true),
    [newMessages, setNewMessages] = useState(false);
  const sidRef = useRef(""),
    scrollRef = useRef<HTMLDivElement>(null),
    fileRef = useRef<HTMLInputElement>(null),
    textRef = useRef<HTMLTextAreaElement>(null),
    draftReady = useRef(false),
    stick = useRef(true),
    pendingRequest = useRef<{
      id: string;
      text: string;
      files: string[];
    } | null>(null),
    liveRate = useRef<{ run: string; chars: number; at: number; rate: number } | null>(null),
    loadGeneration = useRef(0);
  const [now, setNow] = useState(Date.now());
  const [listening, setListening] = useState(false),
    [transcribing, setTranscribing] = useState(false),
    [listenFrom, setListenFrom] = useState(0);
  const project = (app?.projects || []).find(
    (p: any) => p.path === chat?.meta.workspace,
  );
  const projectId = project?.id;
  const [projectChecks, setProjectChecks] = useState<any>(null);
  // Keyed on the project id, not the project object: the identity of `app`
  // changes on every state refresh and would recreate this callback constantly.
  const refreshProjectChecks = useCallback(() => {
    if (!projectId) {
      setProjectChecks(null);
      return Promise.resolve();
    }
    return api(`/api/projects/${projectId}/checks`)
      .then(setProjectChecks)
      .catch(() => {});
  }, [projectId]);
  // Checks poll on their own interval and depend on the running flag rather than
  // the status object. A fresh object on every poll would retrigger the effect,
  // which polls immediately on entry, and turn this into a tight request loop.
  const checksRunning = !!projectChecks?.running;
  useEffect(() => {
    if (!projectId) {
      setProjectChecks(null);
      return;
    }
    if (!panel || tab !== "progress") return;
    refreshProjectChecks();
    if (!checksRunning) return;
    const timer = setInterval(refreshProjectChecks, 2000);
    return () => clearInterval(timer);
  }, [projectId, panel, tab, checksRunning, refreshProjectChecks]);
  useEffect(() => {
    if (app?.active?.session_id !== sid) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [app?.active?.session_id, sid]);
  // The clock above only runs during a task; dictation needs its own.
  useEffect(() => {
    if (!listening) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [listening]);
  const cs = app?.preferences?.language === "cs";
  const modeNames = ["Discussion", "Research", "Writing", "Development", "Computer"];
  useEffect(() => setChatLimit(20), [chat?.meta.workspace, search]);
  // While a chat is loading after a switch, keep the sidebar on the target
  // project's list instead of flashing the no-project conversations.
  const pendingSession = (app?.sessions || []).find((s: any) => s.id === sid);
  const listedChats = searchResults || (app?.sessions || []).filter(
    (s: any) =>
      (s.workspace || null) ===
      (chat?.meta.workspace ?? pendingSession?.workspace ?? null),
  );
  useEffect(() => {
    if (app?.preferences?.send_mode) setDelivery(app.preferences.send_mode);
  }, [app?.preferences?.send_mode]);
  const tr = useCallback((en: string) => translate(en, cs ? "cs" : "en"), [cs]);
  const error = useCallback(
    (e: unknown) => setToast(e instanceof Error ? e.message : String(e)),
    [],
  );
  const refresh = useCallback(async () => {
    const next = await api(
      "/api/state" + (sidRef.current ? "?session_id=" + sidRef.current : ""),
    );
    setApp(next);
    if (!sidRef.current) setSid(next.session_id);
    return next;
  }, []);
  // Dictation puts the text in the box and stops there. Nothing is ever sent
  // without the owner pressing send.
  const dictate = useCallback(async () => {
    if (transcribing) return;
    if (!listening) {
      try {
        await api("/api/voice/start", "POST");
        setListenFrom(Date.now());
        setNow(Date.now());
        setListening(true);
      } catch (e) {
        error(e);
      }
      return;
    }
    setListening(false);
    setTranscribing(true);
    try {
      const heard = await api<{ text: string; heard: boolean }>(
        "/api/voice/stop",
        "POST",
      );
      if (heard.heard) {
        setText((current) =>
          current && !/\s$/.test(current)
            ? current + " " + heard.text
            : current + heard.text,
        );
        textRef.current?.focus();
      } else {
        setToast(tr("Nothing was heard."));
      }
    } catch (e) {
      error(e);
    } finally {
      setTranscribing(false);
    }
  }, [listening, transcribing, error, tr]);
  const refreshDetail = useCallback(async () => {
    const current = sidRef.current;
    if (current) {
      const value = await api("/api/sessions/" + current + "/detail");
      if (sidRef.current === current) setDetail(value);
    }
  }, []);
  const reloadChat = useCallback(async () => {
    const current = sidRef.current;
    if (!current) return;
    const value = await api<Chat>("/api/sessions/" + current);
    if (sidRef.current === current)
      setChat((old) =>
        old ? { ...value, messages: reconcileMessages(old, value) } : value,
      );
  }, []);
  useEffect(() => {
    refresh().catch(error);
  }, [refresh, error]);
  useEffect(() => {
    if (!sid) return;
    sidRef.current = sid;
    draftReady.current = false;
    loadGeneration.current++;
    const generation = loadGeneration.current;
    setChat(null);
    setDetail(null);
    setText("");
    setAttachments([]);
    stick.current = true;
    setNewMessages(false);
    api<Chat>("/api/sessions/" + sid)
      .then((value) => {
        if (generation !== loadGeneration.current) return;
        setChat(value);
        let draft = value.draft;
        try {
          const local = JSON.parse(
            localStorage.getItem("marvin.draft." + sid) || "null",
          );
          if (local) draft = local;
        } catch {}
        setText(draft.text || "");
        setAttachments(draft.attachments || []);
        setPanel(value.meta.work_mode !== "discussion");
        draftReady.current = true;
      })
      .catch(error);
    api("/api/sessions/" + sid + "/detail")
      .then((value) => {
        if (generation === loadGeneration.current) setDetail(value);
      })
      .catch(error);
    api("/api/sessions/" + sid + "/select", "POST").catch(error);
  }, [sid, error]);
  useEffect(() => {
    if (!app) return;
    document.title = "Marvin v" + app.version;
    document.documentElement.lang = translate("en", cs ? "cs" : "en");
    document.documentElement.dataset.theme = app.preferences.theme || "dark";
    document.documentElement.dataset.density =
      app.preferences.density || "comfortable";
  }, [app, cs]);
  useEffect(() => {
    if (!app) return;
    const source = new EventSource("/api/events?after=" + app.sequence);
    let timer: ReturnType<typeof setTimeout> | undefined;
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.onmessage = (event) => {
      const row = JSON.parse(event.data),
        p = row.payload;
      const current = row.session_id === sidRef.current;
      if (row.kind === "live" && current) {
        // Rolling generation-rate estimate from accumulated characters between
        // live updates; reset when a new run starts.
        const chars = (p.text?.length || 0) + (p.reasoning?.length || 0);
        const at = Date.now();
        const prev = liveRate.current;
        if (!prev || prev.run !== p.run_id) {
          liveRate.current = { run: p.run_id, chars, at, rate: 0 };
        } else if (at > prev.at + 150) {
          const inst = chars > prev.chars ? (chars - prev.chars) / CHARS_PER_TOKEN / ((at - prev.at) / 1000) : 0;
          prev.rate = inst > 0 ? (prev.rate ? prev.rate * 0.7 + inst * 0.3 : inst) : prev.rate * 0.85;
          prev.chars = chars;
          prev.at = at;
        }
        p.tok_rate = liveRate.current?.rate || 0;
        setChat((old) => (old ? { ...old, live: p } : old));
      }
      if (row.kind === "message" && current)
        setChat((old) =>
          old ? { ...old, messages: mergeMessages(old.messages, [p]) } : old,
        );
      if (row.kind === "navigate" && current) setSid(p.session_id);
      if (
        [
          "submission",
          "run_status",
          "session_changed",
          "queue_changed",
          "settings_changed",
          "tool_completed",
        ].includes(row.kind)
      ) {
        clearTimeout(timer);
        timer = setTimeout(() => {
          refresh().catch(error);
          if (current) {
            reloadChat().catch(error);
          }
          if (current || row.kind === "settings_changed") {
            refreshDetail().catch(error);
          }
        }, 180);
      }
      if (row.kind === "run_status" && p.status === "failed")
        setToast(p.error || p.text || "Task failed");
    };
    return () => {
      source.close();
      clearTimeout(timer);
    };
  }, [!!app, refresh, reloadChat, refreshDetail, error]);
  useEffect(() => {
    if (!app) return;
    let pending = false;
    const poll = () => {
      if (pending) return;
      pending = true;
      const generation = runtimeGeneration.current;
      return (
      api("/api/runtime")
        .then((value) => {
          if (generation !== runtimeGeneration.current) return;
          setRuntime(value);
          if (panel && tab === "progress") refreshDetail().catch(error);
        })
        .catch(() => {})
        .finally(() => { pending = false; })
      );
    };
    poll();
    const timer = setInterval(poll, 2000);
    window.addEventListener("marvin-runtime-refresh", poll);
    return () => { clearInterval(timer); window.removeEventListener("marvin-runtime-refresh", poll); };
  }, [!!app, panel, tab, refreshDetail, error]);
  useEffect(() => {
    if (!draftReady.current || !sid) return;
    localStorage.setItem(
      "marvin.draft." + sid,
      JSON.stringify({ text, attachments }),
    );
    const timer = setTimeout(
      () =>
        api("/api/sessions/" + sid + "/actions/draft", "POST", {
          text,
          attachments,
        }).catch(error),
      350,
    );
    return () => clearTimeout(timer);
  }, [text, attachments, sid, error]);
  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    if (stick.current)
      requestAnimationFrame(() => {
        scroller.scrollTop = scroller.scrollHeight;
      });
    else setNewMessages(true);
  }, [chat?.messages, chat?.live]);
  // One search over chats, project files, memory and decisions. Each of these was
  // reachable from a different place, so remembering a sentence but not where it
  // was written meant guessing which place to look in.
  useEffect(() => {
    const timer = setTimeout(() => {
      if (!search.trim()) {
        setSearchResults(null);
        setFindings(null);
        return;
      }
      api(
        "/api/find?query=" +
          encodeURIComponent(search.trim()) +
          (sid ? "&session_id=" + encodeURIComponent(sid) : ""),
      )
        .then((answer: any) => {
          const groups = answer.groups || [];
          const chats = groups.find((g: any) => g.kind === "chat");
          setSearchResults(
            (chats?.items || []).map((item: any) => ({
              id: item.open.session_id,
              title: item.title,
              snippet: item.snippet,
            })),
          );
          setFindings(groups.filter((g: any) => g.kind !== "chat"));
        })
        .catch(error);
    }, 250);
    return () => clearTimeout(timer);
  }, [search, sid, error]);
  // Ctrl+K anywhere. The palette is the keyboard route to the same places the
  // interface already has, for someone who would rather type than hunt.
  useEffect(() => {
    const open = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        setDialog((current: any) =>
          current?.type === "palette" ? null : { type: "palette" },
        );
      }
    };
    document.addEventListener("keydown", open);
    return () => document.removeEventListener("keydown", open);
  }, []);
  const act = useCallback(
    async (action: string, payload: any = {}) => {
      const result = await api(
        "/api/sessions/" + sidRef.current + "/actions/" + action,
        "POST",
        payload,
      );
      if (result.session_id) {
        sidRef.current = result.session_id;
        setSid(result.session_id);
      }
      if (action === "delete") return result;
      await refresh();
      await reloadChat();
      await refreshDetail();
      return result;
    },
    [refresh, reloadChat, refreshDetail],
  );
  const settings = async (value: any) => {
    await api("/api/settings", "PATCH", value);
    window.dispatchEvent(new Event("marvin-runtime-refresh"));
    await refresh();
  };
  const runtimeCommand = async (command: string) => {
    ++runtimeGeneration.current;
    setRuntime((old: any) => ({ ...old, switch: {
      status: command === "stop" ? "stopping" : "starting", command,
      phase: command === "stop" ? "stopping" : "preparing", started_at: Date.now() / 1000,
      target: app.preferences.model,
    } }));
    try {
      const result = await api("/api/runtime/" + command, "POST");
      setRuntime((old: any) => ({ ...old, switch: result.switch }));
    } catch (e) {
      setRuntime((old: any) => ({ ...old, switch: { status: "failed", error: String(e) } }));
      throw e;
    } finally { window.dispatchEvent(new Event("marvin-runtime-refresh")); }
  };
  const addFiles = async (files: File[]) => {
    const current = sidRef.current;
    setUploading((n) => n + files.length);
    try {
      const results = await Promise.all(
        files.map(async (file) => {
          const form = new FormData();
          form.append("file", file);
          return api<FileItem>(
            "/api/sessions/" + current + "/attachments",
            "POST",
            form,
          );
        }),
      );
      if (sidRef.current === current)
        setAttachments((items) => [...items, ...results]);
      else {
        const draft = await api<Chat>("/api/sessions/" + current);
        await api("/api/sessions/" + current + "/actions/draft", "POST", {
          ...draft.draft,
          attachments: [...(draft.draft.attachments || []), ...results],
        });
      }
    } catch (e) {
      error(e);
    } finally {
      setUploading((n) => n - files.length);
    }
  };
  // Every surface that reports a failure offers the same help, composed once.
  const helpWith = useCallback(
    (detail: string) =>
      setText(
        tr("The previous task failed with this error:") +
          "\n\n" +
          (detail || "").slice(0, 4000) +
          "\n\n" +
          tr(
            "Work out what caused it and what I should do next. Explain it in plain language, and say what you would change before you change anything.",
          ),
      ),
    [tr],
  );
  const submit = async () => {
    if (sending || uploading || (!text.trim() && !attachments.length)) return;
    const current = sidRef.current;
    setSending(true);
    const files = attachments.map((f) => f.id);
    try {
      pendingRequest.current = JSON.parse(
        localStorage.getItem("marvin.send." + current) || "null",
      );
    } catch {}
    const draft = { text, files };
    if (
      !pendingRequest.current ||
      pendingRequest.current.text !== text ||
      pendingRequest.current.files.join() !== files.join()
    )
      pendingRequest.current = { id: crypto.randomUUID(), ...draft };
    localStorage.setItem(
      "marvin.send." + current,
      JSON.stringify(pendingRequest.current),
    );
    try {
      const result = await api("/api/sessions/" + current + "/submit", "POST", {
        text,
        attachments: files,
        request_id: pendingRequest.current.id,
        delivery,
      });
      if (sidRef.current === current) {
        setText("");
        setAttachments([]);
      }
      await api("/api/sessions/" + current + "/actions/draft", "POST", {
        text: "",
        attachments: [],
      });
      pendingRequest.current = null;
      localStorage.removeItem("marvin.send." + current);
      localStorage.removeItem("marvin.draft." + current);
      await refresh();
      await reloadChat();
      if (result.status === "steering")
        setToast(tr("Clarification received"));
    } catch (e) {
      error(e);
    } finally {
      setSending(false);
    }
  };
  const pick = async (folder = true) => {
    const value = await api("/api/pick", "POST", { folder });
    return value.path as string | null;
  };
  const selectProject = async (id: string) => {
    const value = await api("/api/projects/select", "POST", { id: id || null });
    sidRef.current = value.session_id;
    setSid(value.session_id);
    setNav(false);
    await refresh();
  };
  // Documents worth watching render as text; a binary would show nothing useful.
  const watchDocument = async (path: string) => {
    try {
      const file = await api(
        "/api/sessions/" + sid + "/register-file", "POST", { path },
      );
      setDialog({ type: "preview", file });
    } catch (e) {
      error(e);
    }
  };
  const newChat = async () => {
    const project = app?.projects?.find(
      (p: any) => p.path === chat?.meta.workspace,
    );
    const value = await api("/api/sessions", "POST", {
      project_id: project?.id,
      mode: chat?.meta.work_mode || "discussion",
    });
    sidRef.current = value.session_id;
    setSid(value.session_id);
    setNav(false);
    await refresh();
  };
  const openExport = async (format: string, research = false) => {
    const file = await act("export", { format, research });
    setDialog({ type: "preview", file });
  };
  const retryAnswer = useCallback(
    () => act("retry").catch(error),
    [act, error],
  );
  const openSource = useCallback(
    (id: string) => setDialog({ type: "sources", data: id }),
    [],
  );
  const closeDialog = useCallback(() => setDialog(null), []);
  const openFile = useCallback(
    (file: FileItem) => setDialog({ type: "preview", file }),
    [],
  );
  const active = app?.active?.session_id === sid,
    mode = chat?.meta.work_mode || "discussion";
  const queued: Job[] = (app?.queue || []).filter(
    (j: Job) =>
      j.session_id === sid && ["queued", "steering"].includes(j.status),
  );
  const interrupted = (chat?.jobs || [])
    .filter((j) =>
      ["interrupted", "stopped", "failed", "waiting_confirmation"].includes(
        j.status,
      ),
    )
    .at(-1);
  const live = chat?.live;
  const savedLive = chat?.messages.some(
    (m) =>
      m.role === "assistant" &&
      m.run_id === live?.run_id &&
      m.step_id === live?.step,
  );
  const contextUsed =
    Object.values(detail?.context?.breakdown || {}).reduce<number>(
      (a, v) => a + Number(v),
      0,
    ) ||
    detail?.context?.estimated_tokens ||
    0;
  if (!app)
    return (
      <div className="startup">
        <Bot size={32} />
        <h1>Marvin</h1>
        <p>{toast || "Loading workspace…"}</p>
        <small className="copyright">{COPYRIGHT}</small>
      </div>
    );
  return (
    <div
      className="app"
      onDragOver={(e) => {
        if ([...e.dataTransfer.types].includes("Files")) {
          e.preventDefault();
          e.dataTransfer.dropEffect = "copy";
        }
      }}
      onDrop={(e) => {
        if (e.dataTransfer.files.length) {
          e.preventDefault();
          addFiles([...e.dataTransfer.files]);
        }
      }}
    >
      <header className="topbar">
        <button
          className="icon mobile-nav"
          aria-label={tr("Projects and chats")}
          onClick={() => setNav(!nav)}
        >
          <PanelLeft />
        </button>
        <div className="brand">
          <Bot />
          Marvin <small>v{app.version}</small>
        </div>
        <span className="spacer" />
        <button
          className={"runtime-button " + (["starting", "stopping"].includes(runtime.switch?.status) ? "model-busy" : "")}
          onClick={() => setDialog({ type: "settings", section: "model" })}
        >
          {["starting", "stopping"].includes(runtime.switch?.status) ? <LoaderCircle className="spin" /> : <span
            className={
              "dot " + (runtime.status === "running" ? "ready" : "waiting")
            }
          />}
          <span>
            {
              app.models.find(
                (m: any) => m.id === (runtime.switch?.status === "starting" ? runtime.switch.target : runtime.model || app.preferences.model),
              )?.name
            }
          </span>
          {runtime.profile?.speculative && <span className="amber">MTP</span>}
          <span className="muted">
            {runtime.switch?.status === "starting"
              ? tr("Loading")
              : runtime.switch?.status === "stopping" ? tr("Stopping")
              : runtime.switch?.status === "failed" ? tr("Start failed")
              : runtime.status === "running"
                ? tr("Ready")
                : tr("Stopped")}
          </span>
          <ChevronDown />
        </button>
        <button
          className="icon"
          title={tr("Settings")}
          aria-label={tr("Settings")}
          onClick={() => setDialog({ type: "settings", section: "model" })}
        >
          <Settings2 />
        </button>
      </header>
      <div className="workspace" style={{
        "--sidebar-width": leftWidth ? `${leftWidth}px` : undefined,
        "--detail-width": rightWidth ? `${rightWidth}px` : undefined,
      } as React.CSSProperties}>
        <div className={"sidebar-region " + (nav ? "open" : "")}>
        <aside className={"sidebar " + (nav ? "open" : "")}>
          <button className="positive" onClick={() => newChat().catch(error)}>
            <Plus />
            {tr("New chat")}
          </button>
          <label className="search">
            <Search />
            <input
              aria-label={tr("Search everything")}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={tr("Search everything")}
            />
          </label>
          <label className="section-label">{tr("PROJECT")}</label>
          <div className="row">
            <select
              aria-label={tr("Project")}
              value={project?.id || ""}
              onChange={(e) => selectProject(e.target.value).catch(error)}
            >
              <option value="">{tr("No project")}</option>
              {app.projects.map((p: any) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <button
              className="icon"
              aria-label={tr("Project actions")}
              onClick={() => setDialog({ type: "project" })}
            >
              <Ellipsis />
            </button>
          </div>
          <label className="section-label">
            {searchResults
              ? tr("SEARCH RESULTS")
              : tr("CONVERSATIONS")}
          </label>
          <nav
            className="chat-list"
            aria-label={tr("Conversations")}
          >
            {listedChats.slice(0, chatLimit).map((s: any) => (
              <button
                key={s.id}
                className={sid === s.id ? "selected" : ""}
                onClick={() => {
                  setSid(s.id);
                  setNav(false);
                }}
              >
                <MessageSquare />
                <span>
                  {s.title || tr("New conversation")}
                  {app.active?.session_id === s.id && (
                    <small className="green">{tr("Working")}</small>
                  )}
                  {searchResults && <small>{s.snippet}</small>}
                </span>
              </button>
            ))}
            {listedChats.length > chatLimit && <button className="older-chats" onClick={() => setChatLimit((n) => n + 20)}>
              <ChevronDown />{tr("Show older")} ({listedChats.length - chatLimit})
            </button>}
            {chatLimit > 20 && <button className="older-chats" onClick={() => setChatLimit(20)}>
              {tr("Show recent only")}
            </button>}
          </nav>
          {(findings || []).map((group: any) => (
            <div key={group.kind}>
              <label className="section-label">
                {tr(
                  group.kind === "file"
                    ? "IN PROJECT FILES"
                    : group.kind === "memory"
                      ? "IN MEMORY"
                      : "IN PROJECT DECISIONS",
                )}
              </label>
              <nav className="chat-list">
                {group.items.map((item: any, index: number) => (
                  <button
                    key={group.kind + index}
                    onClick={() => {
                      setNav(false);
                      if (item.open.what === "file")
                        setDialog({
                          type: "preview",
                          file: {
                            id: item.open.path,
                            name: item.title,
                            path: item.open.path,
                            url: "",
                          },
                        });
                      else if (item.open.what === "memory")
                        setDialog({
                          type: "settings",
                          section: "memory",
                          data: { scope: item.snippet },
                        });
                      else setDialog({ type: "decisions" });
                    }}
                  >
                    {item.open.what === "file" ? (
                      <FileText />
                    ) : item.open.what === "memory" ? (
                      <Brain />
                    ) : (
                      <BookmarkCheck />
                    )}
                    <span>
                      {item.title}
                      <small>{item.snippet}</small>
                    </span>
                  </button>
                ))}
              </nav>
            </div>
          ))}
          <button
            className="nav-button"
            onClick={() => setDialog({ type: "library" })}
          >
            <FolderOpen />
            {tr("Project documents")}
          </button>
          <button
            className="nav-button"
            onClick={() => setDialog({ type: "decisions" })}
          >
            <BookmarkCheck />
            {tr("Project decisions")}
          </button>
          <div className="sidebar-bottom">
            <button
              className="nav-button"
              onClick={() => setDialog({ type: "settings", section: "memory" })}
            >
              <Brain />
              {tr("Memory and skills")}
            </button>
            <button
              className="nav-button"
              onClick={() => setDialog({ type: "settings", section: "data" })}
            >
              <HardDrive />
              {tr("Data and backups")}
            </button>
          </div>
        </aside>
        <ResizeHandle side="left" label={tr("Navigation width")} value={leftWidth}
          onChange={setLeftWidth} onReset={() => setLeftWidth(undefined)} />
        </div>
        <main className="main">
          <div className="chat-heading">
            <input
              key={chat?.id || sid}
              aria-label={tr("Chat title")}
              defaultValue={chat?.meta.title || ""}
              placeholder={tr("New conversation")}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  act("rename", { title: e.currentTarget.value }).catch(error);
                  e.currentTarget.blur();
                }
              }}
            />
            <select
              aria-label={tr("Work mode")}
              value={mode}
              onChange={(e) =>
                act("mode", { mode: e.target.value }).catch(error)
              }
            >
              {app.modes.map((m: any, i: number) => (
                <option key={m.id} value={m.id}>
                  {cs
                    ? ["Discussion","Research","Writing","Development","Computer"].map((label) => translate(label, "cs"))[i]
                    : m.label}
                </option>
              ))}
            </select>
            <button
              className="icon"
              aria-label={tr("Toggle details")}
              onClick={() => setPanel(!panel)}
            >
              <PanelRight />
            </button>
            <button
              className="icon"
              aria-label={tr("Chat actions")}
              onClick={() => setDialog({ type: "chat" })}
            >
              <Ellipsis />
            </button>
          </div>
          <div className={"chat-workspace " + (panel ? "with-detail" : "")}>
            <div className="chat-column">
              <div
                className="messages"
                ref={scrollRef}
                onScroll={() => {
                  const s = scrollRef.current;
                  if (s) {
                    stick.current =
                      s.scrollHeight - s.scrollTop - s.clientHeight < 80;
                    if (stick.current) setNewMessages(false);
                  }
                }}
              >
                {chat?.before !== null && chat?.before !== undefined && (
                  <button
                    className="older"
                    onClick={async () => {
                      const value = await api<Chat>(
                        "/api/sessions/" + sid + "?before=" + chat.before,
                      );
                      setChat((old) =>
                        old
                          ? {
                              ...old,
                              messages: mergeMessages(
                                value.messages,
                                old.messages,
                              ),
                              before: value.before,
                            }
                          : old,
                      );
                    }}
                  >
                    {tr("Earlier messages")}
                  </button>
                )}
                {chat?.messages.filter(visibleMessage).map((m) => (
                  <ChatMessage
                    key={m.id}
                    message={m}
                    cs={cs}
                    openFile={openFile}
                    openSource={openSource}
                    retry={retryAnswer}
                    helpWith={helpWith}
                  />
                ))}
                {chat && !chat.messages.some(visibleMessage) && (
                  <div className="empty-chat">
                    <Bot size={34} />
                    <h2>
                      {tr("What shall we work on?")}
                    </h2>
                  </div>
                )}
                {active && !savedLive && (live?.text || live?.reasoning) && (
                  <article className="message assistant live">
                    <div className="message-label">
                      <Bot />
                      Marvin
                    </div>
                    {live.reasoning && (
                      <details open={false}>
                        <summary>{tr("Thinking")}</summary>
                        <Markdown remarkPlugins={[remarkGfm]}>
                          {live.reasoning}
                        </Markdown>
                      </details>
                    )}
                    {live.text && (
                      <Markdown remarkPlugins={[remarkGfm]}>
                        {live.text}
                      </Markdown>
                    )}
                  </article>
                )}
                {queued.length > 0 && app.queue_paused && (
                  <button
                    className="positive"
                    onClick={() =>
                      api("/api/queue/resume", "POST")
                        .then(refresh)
                        .catch(error)
                    }
                  >
                    <Play />
                    {tr("Resume queued messages")}
                  </button>
                )}
                {queued.map((job) => (
                  <div className="queued" key={job.id}>
                    <div className="row">
                      <ListChecks />
                      <strong>
                        {job.status === "steering"
                          ? tr("Clarification received")
                          : tr("After current task")}
                      </strong>
                      <span className="spacer" />
                      <button
                        className="icon"
                        aria-label={tr("Edit queued message")}
                        onClick={() =>
                          setDialog({ type: "queue-edit", data: job })
                        }
                      >
                        <FileText />
                      </button>
                      <button
                        className="icon"
                        aria-label={tr("Cancel queued message")}
                        onClick={() =>
                          api("/api/queue/" + job.id, "PATCH", { cancel: true })
                            .then(refresh)
                            .catch(error)
                        }
                      >
                        <X />
                      </button>
                    </div>
                    <p>{job.payload.text}</p>
                  </div>
                ))}
              </div>
              {newMessages && (
                <button
                  className="new-messages"
                  onClick={() => {
                    stick.current = true;
                    const s = scrollRef.current;
                    if (s) s.scrollTop = s.scrollHeight;
                    setNewMessages(false);
                  }}
                >
                  {tr("New messages")}
                  <ChevronDown />
                </button>
              )}
              <div className="composer-area">
                {interrupted && !active && (
                  <div className="attention">
                    <div>
                      <strong>
                        {interrupted.status === "waiting_confirmation"
                          ? tr("Waiting for confirmation")
                          : tr("Task can be continued")}
                      </strong>
                      {interrupted.payload.error && (
                        <p>{interrupted.payload.error}</p>
                      )}
                    </div>
                    <button
                      className="positive"
                      onClick={() =>
                        act("resume", {
                          approve:
                            interrupted.status === "waiting_confirmation"
                              ? true
                              : undefined,
                        }).catch(error)
                      }
                    >
                      <Play />
                      {interrupted.status === "waiting_confirmation"
                        ? tr("Allow")
                        : tr("Continue")}
                    </button>
                    {interrupted.status === "waiting_confirmation" && (
                      <button
                        className="danger"
                        onClick={() =>
                          act("resume", { approve: false }).catch(error)
                        }
                      >
                        {tr("Deny")}
                      </button>
                    )}
                  </div>
                )}
                {active && (
                  <div className="activity" role="status">
                    <LoaderCircle className="spin" />
                    <span>
                      {live?.phase === "preparing" && /^\/(compress|handoff)/.test(app.active?.text || "")
                        ? tr("Summarizing conversation")
                        : tr(phases[live?.phase] || phases.preparing)}
                      {live?.tool && " · " + live.tool}
                      {live?.phase === "reading_context" &&
                        live.prompt_progress &&
                        prefillSummary(live.prompt_progress, tr)}
                      {live?.tool_chars > 0 &&
                        " · " + Math.round(live.tool_chars / 1024) + " KB"}
                      {(live?.phase_started || live?.started) &&
                        " · " +
                          Math.max(0, Math.round(now / 1000 - (live.phase_started || live.started))) +
                          " s"}
                      {" · ~" +
                        formatTokens(
                          Math.round(
                            ((live?.text?.length || 0) +
                              (live?.reasoning?.length || 0) +
                              (live?.tool_chars || 0)) /
                              CHARS_PER_TOKEN,
                          ),
                        ) +
                        " tok"}
                      {live?.tok_rate >= 1 &&
                        ["thinking", "generating", "answering"].includes(live?.phase) &&
                        " · ~" + Math.round(live.tok_rate) + " tok/s"}
                    </span>
                    <button
                      onClick={() => {
                        setTab("progress");
                        setPanel(true);
                      }}
                    >
                      {tr("Progress")}
                      <ChevronRight />
                    </button>
                  </div>
                )}
                {app.active && !active && (
                  <div className="activity muted">
                    <span>
                      {tr("Another chat is working; this message will be queued.")}
                    </span>
                  </div>
                )}
                <div
                  className="composer"
                  onPaste={(e) => {
                    const files = [...e.clipboardData.items]
                      .filter(
                        (i) => i.kind === "file" && i.type.startsWith("image/"),
                      )
                      .map((i) => i.getAsFile())
                      .filter((x): x is File => !!x);
                    if (files.length) {
                      e.preventDefault();
                      addFiles(files);
                    }
                  }}
                >
                  <div className="attachment-list">
                    {attachments.map((file) => (
                      <Attachment
                        key={file.id}
                        file={file}
                        open={() => openFile(file)}
                        remove={() =>
                          setAttachments((items) =>
                            items.filter((i) => i.id !== file.id),
                          )
                        }
                        cs={cs}
                      />
                    ))}
                    {uploading > 0 && (
                      <span className="uploading">
                        <LoaderCircle className="spin" />
                        {tr("Adding attachments")} (
                        {uploading})
                      </span>
                    )}
                  </div>
                  <textarea
                    ref={textRef}
                    aria-label={tr("Message")}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    onKeyDown={(e) => {
                      if (
                        e.key === "Enter" &&
                        !e.shiftKey &&
                        !e.nativeEvent.isComposing
                      ) {
                        e.preventDefault();
                        submit();
                      }
                    }}
                    placeholder={
                      active
                        ? tr("Add a clarification…")
                        : tr("Type a message…")
                    }
                  />
                  {text.startsWith("/") && !text.includes("\n") && (
                    <div className="slash-menu">
                      {Object.entries(app.commands as Record<string, string>)
                        .filter(([key]) => key.startsWith(text.split(" ")[0]))
                        .map(([key, value]) => (
                          <button
                            key={key}
                            onClick={() => {
                              setText(key + " ");
                              textRef.current?.focus();
                            }}
                          >
                            <code>{key}</code>
                            <span>{tr(value)}</span>
                          </button>
                        ))}
                    </div>
                  )}
                  <div className="composer-toolbar">
                    {app.voice?.enabled && (
                      <button
                        className={listening ? "danger" : "attach"}
                        disabled={transcribing || (!listening && !app.voice?.ready)}
                        title={
                          app.voice?.ready
                            ? ""
                            : (app.voice?.missing || []).join(", ") ||
                              app.voice?.capture_error ||
                              ""
                        }
                        onClick={() => void dictate()}
                      >
                        {transcribing ? (
                          <LoaderCircle className="spin" />
                        ) : listening ? (
                          <Square />
                        ) : (
                          <Mic />
                        )}
                        {transcribing
                          ? tr("Transcribing")
                          : listening
                            ? tr("Stop dictation") +
                              " · " +
                              Math.max(
                                0,
                                Math.round((now - listenFrom) / 1000),
                              ) +
                              " s"
                            : tr("Dictate")}
                      </button>
                    )}
                    <button
                      className="attach"
                      onClick={() => fileRef.current?.click()}
                    >
                      <Paperclip />
                      {tr("Attach")}
                    </button>
                    <input
                      ref={fileRef}
                      type="file"
                      multiple
                      hidden
                      onChange={(e) => {
                        if (e.target.files) addFiles([...e.target.files]);
                        e.target.value = "";
                      }}
                    />
                    <button
                      className="attach"
                      onClick={() => setDialog({ type: "capabilities" })}
                    >
                      <Lightbulb />
                      {tr("What can I ask for?")}
                    </button>
                    <select
                      aria-label={tr("Thinking")}
                      value={app.preferences.thinking}
                      onChange={(e) =>
                        settings({ thinking: e.target.value }).catch(error)
                      }
                    >
                      {["xhigh", "medium", "low", "off"].map((e) => (
                        <option key={e} value={e}>
                          {tr("Thinking")}: {e}
                        </option>
                      ))}
                    </select>
                    <span className="spacer" />
                    {active && (
                      <select
                        aria-label={tr("Message delivery")}
                        value={delivery}
                        onChange={(e) => setDelivery(e.target.value)}
                      >
                        <option value="steer">
                          {tr("Clarify now")}
                        </option>
                        <option value="queue">
                          {tr("After completion")}
                        </option>
                      </select>
                    )}
                    {active && (
                      <button
                        className="icon danger stop"
                        aria-label={tr("Stop task")}
                        title={tr("Stop task")}
                        onClick={() => act("stop").catch(error)}
                      >
                        <Square />
                      </button>
                    )}
                    <button
                      className="icon positive send"
                      disabled={sending || uploading > 0}
                      aria-label={tr("Send")}
                      title={tr("Send")}
                      onClick={submit}
                    >
                      {sending ? (
                        <LoaderCircle className="spin" />
                      ) : (
                        <ArrowUp />
                      )}
                    </button>
                  </div>
                </div>
                <div className="composer-footer">
                  <span>
                    {connected
                      ? tr("Saved locally")
                      : tr("Reconnecting…")}
                  </span>
                  <button
                    onClick={() => {
                      setTab("context");
                      setPanel(true);
                    }}
                  >
                    {tr("Context")}: ~{formatTokens(contextUsed)} /{" "}
                    {formatTokens(detail?.context?.limit || 0)}
                    <ChevronRight />
                  </button>
                </div>
              </div>
            </div>
            {panel && (
              <aside className="detail">
                <ResizeHandle side="right" label={tr("Detail width")} value={rightWidth}
                  onChange={setRightWidth} onReset={() => setRightWidth(undefined)} />
                <nav className="detail-tabs">
                  {[
                    ["results", "Results"],
                    ["progress", "Progress"],
                    ["context", "Context"],
                  ].map(([id, en]) => (
                    <button
                      key={id}
                      className={tab === id ? "selected" : ""}
                      onClick={() => setTab(id)}
                    >
                      {tr(en)}
                    </button>
                  ))}
                </nav>
                <div className="detail-body">
                  {tab === "results" ? (
                    <>
                      <section>
                        <h3>{tr("This conversation")}</h3>
                        {!detail?.results?.length && (
                          <p className="muted">
                            {tr("Created files will appear here.")}
                          </p>
                        )}
                        {detail?.results?.map((f: FileItem) => (
                          <div className="file-row" key={f.id}>
                            <FileText />
                            <button onClick={() => openFile(f)}>
                              <strong>{f.name}</strong>
                              <small>
                                {f.kind === "changed"
                                  ? tr("Changed file")
                                  : tr("Result")}
                              </small>
                            </button>
                            {f.kind === "changed" && (
                              <button
                                className="icon"
                                aria-label={tr("Show changes")}
                                title={tr("Show changes")}
                                onClick={() =>
                                  setDialog({
                                    type: "diff",
                                    data: { path: f.path },
                                  })
                                }
                              >
                                <GitCompare />
                              </button>
                            )}
                            <button
                              className="icon"
                              aria-label={tr("Open folder")}
                              onClick={() =>
                                api("/api/files/" + f.id + "/open", "POST", {
                                  folder: true,
                                }).catch(error)
                              }
                            >
                              <FolderOpen />
                            </button>
                          </div>
                        ))}
                      </section>
                      {detail?.research && (
                        <section>
                          <h3>{tr("Research")}</h3>
                          <p>
                            {detail.research.sources.length}{" "}
                            {tr("loaded sources")}
                          </p>
                          <button
                            onClick={() => setDialog({ type: "sources" })}
                          >
                            <Globe />
                            {tr("All sources")}
                          </button>
                          <div className="row">
                            <button
                              onClick={() =>
                                openExport("pdf", true).catch(error)
                              }
                            >
                              PDF
                            </button>
                            <button
                              onClick={() =>
                                openExport("docx", true).catch(error)
                              }
                            >
                              DOCX
                            </button>
                            <button
                              onClick={() =>
                                act("export_sources")
                                  .then((f) =>
                                    setDialog({ type: "preview", file: f }),
                                  )
                                  .catch(error)
                              }
                            >
                              <Download />
                              {tr("Sources")}
                            </button>
                          </div>
                        </section>
                      )}
                      <section>
                        <h3>{tr("Validation")}</h3>
                        {detail?.plan?.validations?.length ? (
                          detail.plan.validations.map((v: any, i: number) => (
                            <div className="check-row" key={i}>
                              {v.status === "passed" ? (
                                <CheckCheck className="green" />
                              ) : (
                                <AlertCircle className="amber" />
                              )}
                              <span>
                                {v.label}
                                <small>{v.status}</small>
                              </span>
                            </div>
                          ))
                        ) : (
                          <p className="muted">
                            {tr("No completed checks recorded.")}
                          </p>
                        )}
                      </section>
                      <section>
                        <button
                          className="wide"
                          onClick={() => setDialog({ type: "export" })}
                        >
                          <Download />
                          {tr("Export conversation")}
                        </button>
                        <button
                          className="wide"
                          onClick={() => setDialog({ type: "checkpoints" })}
                        >
                          <History />
                          {tr("Restore points")}
                        </button>
                      </section>
                    </>
                  ) : tab === "progress" ? (
                    <>
                      <section>
                        <h3>
                          {detail?.plan?.goal ||
                            tr("Current task")}
                        </h3>
                        {detail?.plan?.steps?.map((s: any) => (
                          <div className="check-row" key={s.id}>
                            {s.status === "completed" ? (
                              <Check className="green" />
                            ) : s.status === "in_progress" ? (
                              <LoaderCircle className="spin" />
                            ) : (
                              <span className="small-circle" />
                            )}
                            <span>
                              {s.text}
                              <small>{s.note}</small>
                            </span>
                          </div>
                        ))}
                      </section>
                      <section>
                        <h3>{tr("Activity history")}</h3>
                        {detail?.notices?.map((n: any) =>
                          n.kind === "steer_deferred" ? (
                            <p className="muted" key={n.seq}>
                              {tr(
                                "Your message is waiting for the context to finish loading. Interrupting now would discard it and reload it from the start.",
                              )}
                            </p>
                          ) : n.kind === "failure" ? (
                            <div className="file-row" key={n.seq}>
                              <AlertCircle className="amber" />
                              <div>
                                <strong>{tr("The task did not finish")}</strong>
                                <small>{n.text}</small>
                                {n.hint && <small>{tr(n.hint)}</small>}
                              </div>
                              <button onClick={() => helpWith(n.text)}>
                                {tr("Work out what to do")}
                              </button>
                            </div>
                          ) : (
                            <p key={n.seq}>{n.text}</p>
                          ),
                        )}
                      </section>
                      <section>
                        <h3>{tr("Processes")}</h3>
                        {detail?.processes?.map((p: any) => (
                          <div className="process" key={p.process_id}>
                            <strong>{p.command}</strong>
                            <p>
                              {p.status} · {Math.round(p.elapsed_seconds)} s
                            </p>
                            <button
                              onClick={() =>
                                setDialog({
                                  type: "process-output",
                                  data: { id: p.process_id },
                                })
                              }
                            >
                              <FileText />
                              {tr("Output")}
                            </button>
                            {p.status === "running" && (
                              <button
                                className="danger"
                                title={tr("This stops the background command only, not the task")}
                                onClick={() =>
                                  act("stop_process", {
                                    id: p.process_id,
                                  }).catch(error)
                                }
                              >
                                <Square />
                                {tr("Stop this command")}
                              </button>
                            )}
                          </div>
                        ))}
                      </section>
                      <section>
                        <h3>Browser</h3>
                        <p>
                          {detail?.browser?.running
                            ? detail.browser.url
                            : tr("Closed")}
                        </p>
                        {detail?.browser?.running && (
                          <button
                            onClick={() => act("close_browser").catch(error)}
                          >
                            <X />
                            {tr("Close browser")}
                          </button>
                        )}
                      </section>
                      <section>
                        <h3>{tr("Files changed")}</h3>
                        {detail?.changes?.files
                          ?.filter((f: any) => f.changed)
                          .map((f: any) => (
                            <div className="row" key={f.path}>
                              <button
                                className="file-diff-link"
                                title={tr("Show changes")}
                                onClick={() =>
                                  setDialog({
                                    type: "diff",
                                    data: { path: f.path },
                                  })
                                }
                              >
                                <GitCompare />
                                {f.path}
                              </button>
                              {READABLE.test(f.path) && (
                                <button
                                  className="icon"
                                  title={tr("Watch this document")}
                                  aria-label={tr("Watch this document")}
                                  onClick={() => watchDocument(f.path)}
                                >
                                  <BookOpen />
                                </button>
                              )}
                            </div>
                          ))}
                        <button
                          className="wide"
                          onClick={() => act("revert").catch(error)}
                        >
                          <History />
                          {tr("Revert task changes")}
                        </button>
                      </section>
                      {project && (
                        <section>
                          <h3>{tr("Project status")}</h3>
                          {projectChecks?.available === false ? (
                            <p className="muted">
                              {tr(
                                "No checks detected — add .qwen/project.yaml to define them.",
                              )}
                            </p>
                          ) : (
                            (projectChecks?.checks || []).map((c: any) => (
                              <div
                                className="check-row"
                                key={c.id}
                                title={c.summary || c.command}
                              >
                                {c.state === "running" ? (
                                  <LoaderCircle className="spin" />
                                ) : c.state === "pass" ? (
                                  <CheckCheck className="green" />
                                ) : c.state === "never" || c.state === "queued" ? (
                                  <CircleDashed />
                                ) : (
                                  <AlertCircle className="amber" />
                                )}
                                <span>
                                  {tr(c.label)}
                                  <small>
                                    {c.state === "never"
                                      ? tr("not run yet")
                                      : c.state === "queued"
                                        ? tr("queued…")
                                        : c.state === "running"
                                          ? tr("running…")
                                          : `${tr(c.state)} · ${new Date(
                                              c.time * 1000,
                                            ).toLocaleTimeString()}`}
                                  </small>
                                  {c.hint && <small>{tr(c.hint)}</small>}
                                </span>
                                {c.hint && (
                                  <button
                                    className="icon"
                                    aria-label={tr("Work out what to do")}
                                    title={tr("Work out what to do")}
                                    onClick={() =>
                                      helpWith(c.summary || c.command)
                                    }
                                  >
                                    <Wrench />
                                  </button>
                                )}
                              </div>
                            ))
                          )}
                          <button
                            className="wide"
                            disabled={projectChecks?.running}
                            onClick={() =>
                              api(
                                `/api/projects/${project.id}/checks/run`,
                                "POST",
                              )
                                .then(refreshProjectChecks)
                                .catch(error)
                            }
                          >
                            <Play />
                            {tr("Run project checks")}
                          </button>
                          <button
                            className="wide"
                            onClick={() =>
                              api(`/api/projects/${project.id}/checks/fix`, "POST")
                                .then((value) => {
                                  sidRef.current = value.session_id;
                                  setSid(value.session_id);
                                })
                                .catch(error)
                            }
                          >
                            <Wrench />
                            {tr("Fix failures with agent")}
                          </button>
                        </section>
                      )}
                    </>
                  ) : (
                    <>
                      <section>
                        <h3>{tr("Context usage")}</h3>
                        <div className="meter">
                          <div
                            style={{
                              width:
                                Math.min(
                                  100,
                                  (100 * contextUsed) /
                                    (detail?.context?.limit || 1),
                                ) + "%",
                            }}
                          />
                        </div>
                        <p>
                          ~{formatTokens(contextUsed)} /{" "}
                          {formatTokens(detail?.context?.limit || 0)}
                        </p>
                        <p className="muted">
                          {tr("Estimate; measured usage below is from the last completed request.")}
                        </p>
                        {detail?.context?.usage?.prompt_tokens !==
                          undefined && (
                          <p>
                            {tr("Measured input")}:{" "}
                            {detail.context.usage.prompt_tokens}
                            <br />
                            {tr("Generated")}:{" "}
                            {detail.context.usage.completion_tokens}
                          </p>
                        )}
                      </section>
                      <section>
                        <h3>{tr("Active memories")}</h3>
                        {detail?.context?.snapshot && (
                          <button
                            onClick={() =>
                              setDialog({
                                type: "context-snapshot",
                                data: detail.context.snapshot,
                              })
                            }
                          >
                            <History />
                            {tr("Context used by this run")}
                          </button>
                        )}
                        {["global", "mode", "project"].map((scope, i) => (
                          <div className="check-row" key={scope}>
                            {detail?.memory?.[scope]?.path ? (
                              <Check className="green" />
                            ) : (
                              <X />
                            )}
                            <span>
                              {cs
                                ? ["Global", "Mode", "Project"].map((label) => translate(label, "cs"))[i]
                                : ["Global", "Work mode", "Project"][i]}
                            </span>
                          </div>
                        ))}
                        <button
                          onClick={() =>
                            setDialog({ type: "settings", section: "memory" })
                          }
                        >
                          <Brain />
                          {tr("Open memories")}
                        </button>
                      </section>
                      <section>
                        <h3>{tr("Pinned files")}</h3>
                        {detail?.context?.pinned_files?.map((p: string) => (
                          <div className="file-row" key={p}>
                            <Pin />
                            <span>{p.split(/[\\/]/).at(-1)}</span>
                            <button
                              className="icon"
                              onClick={() =>
                                act("unpin", { path: p }).catch(error)
                              }
                              aria-label={tr("Unpin")}
                            >
                              <X />
                            </button>
                          </div>
                        ))}
                        <div className="row">
                          <button
                            onClick={() =>
                              pick(false)
                                .then((p) => p && act("pin", { path: p }))
                                .catch(error)
                            }
                          >
                            <Plus />
                            {tr("Pin file")}
                          </button>
                          <button
                            onClick={() => act("clear_pins").catch(error)}
                          >
                            {tr("Unpin all")}
                          </button>
                        </div>
                      </section>
                      <section>
                        <h3>{tr("Loaded skills")}</h3>
                        {detail?.context?.active_skills?.map((s: string) => (
                          <p key={s}>{s}</p>
                        ))}
                        <button
                          className="wide"
                          onClick={() => act("compress").catch(error)}
                        >
                          <Archive />
                          {tr("Compress")}
                        </button>
                        <button
                          className="wide"
                          onClick={() => act("handoff").catch(error)}
                        >
                          <MessageSquare />
                          {tr("Hand off to new chat")}
                        </button>
                      </section>
                    </>
                  )}
                </div>
                <footer className="detail-footer">
                  <small className="copyright">{COPYRIGHT}</small>
                </footer>
              </aside>
            )}
          </div>
        </main>
      </div>
      {toast && (
        <div className="toast" role="status">
          <span>{toast}</span>
          <button
            className="icon"
            aria-label={tr("Dismiss")}
            onClick={() => setToast("")}
          >
            <X />
          </button>
        </div>
      )}
      {/* The palette's actions are built here, where the callbacks live: it is a
          second way into the interface, not a second implementation of it. */}
      {dialog && (
        <DialogView
          actions={[
            { id: "new-chat", label: tr("New chat"), run: () => newChat() },
            {
              id: "capabilities",
              label: tr("What can I ask for?"),
              run: async () => setDialog({ type: "capabilities" }),
            },
            ...(app.modes || []).map((m: any, index: number) => ({
              id: "mode-" + m.id,
              label: tr("Switch mode") + ": " +
                (cs ? translate(modeNames[index], "cs") : m.label),
              run: () => act("mode", { mode: m.id }),
            })),
            {
              id: "decisions",
              label: tr("Project decisions"),
              run: async () => setDialog({ type: "decisions" }),
            },
            {
              id: "context",
              label: tr("Context"),
              run: async () => {
                setTab("context");
                setPanel(true);
              },
            },
            {
              id: "progress",
              label: tr("Task progress"),
              run: async () => {
                setTab("progress");
                setPanel(true);
              },
            },
            {
              id: "changes",
              label: tr("Changes"),
              run: async () => {
                setTab("changes");
                setPanel(true);
              },
            },
            {
              id: "compress",
              label: tr("Compress"),
              run: () => act("compress"),
            },
            ...(app.voice?.enabled && app.voice?.ready
              ? [{ id: "dictate", label: tr("Dictate"), run: () => dictate() }]
              : []),
            ...SETTINGS_SECTIONS.map(([section, label]) => ({
              id: "settings-" + section,
              label: tr("Settings") + ": " + tr(label),
              run: async () => setDialog({ type: "settings", section }),
            })),
          ]}
          dialog={dialog}
          close={closeDialog}
          setDialog={setDialog}
          app={app}
          chat={chat}
          detail={detail}
          sid={sid}
          tr={tr}
          cs={cs}
          act={act}
          settings={settings}
          error={error}
          refresh={refresh}
          setSid={setSid}
          pick={pick}
          runtime={runtime}
          runtimeCommand={runtimeCommand}
          setText={setText}
          openPanel={(name: string) => {
            setTab(name);
            setPanel(true);
          }}
        />
      )}
      <ActivityFeedback cs={cs} />
    </div>
  );
}

function mergeMessages(before: Message[], after: Message[]) {
  const result = [...before],
    positions = new Map(result.map((m, i) => [m.id, i]));
  after.forEach((m) => {
    const index = positions.get(m.id);
    if (index !== undefined) result[index] = m;
    else {
      positions.set(m.id, result.length);
      result.push(m);
    }
  });
  return result;
}
function reconcileMessages(old: Chat, next: Chat) {
  if (next.before === null) return next.messages;
  const first = old.messages.findIndex((m) => m.id === next.messages[0]?.id);
  return first > 0
    ? [...old.messages.slice(0, first), ...next.messages]
    : next.messages;
}
function formatDuration(seconds: number) {
  return seconds >= 90
    ? Math.round(seconds / 60) + " min"
    : Math.max(1, Math.round(seconds)) + " s";
}

// What the wait costs, and why. Reuse is the number that matters: a prompt the
// server still holds is free to send, so a low share means something near the
// start of the conversation changed and all of it is being recomputed.
function prefillSummary(
  progress: { total?: number; cache?: number; processed?: number; time_ms?: number },
  tr: (text: string) => string,
) {
  const total = Number(progress.total || 0);
  const cache = Number(progress.cache || 0);
  const processed = Number(progress.processed || 0);
  const elapsed = Number(progress.time_ms || 0) / 1000;
  const parts: string[] = [];
  const todo = Math.max(1, total - cache);
  const done = Math.max(0, processed - cache);
  // Label it. A bare percentage after "Reading context" reads as how full the
  // context is, which is a different number entirely - this one is progress
  // through the part the server does not already hold.
  parts.push(
    tr("new") +
      " " +
      Math.max(0, Math.min(100, Math.round((100 * done) / todo))) +
      "%",
  );
  if (total > 0) {
    parts.push(
      tr("reused") +
        " " +
        formatTokens(cache) +
        "/" +
        formatTokens(total) +
        " (" +
        Math.round((100 * cache) / total) +
        "%)",
    );
  }
  const rate = elapsed > 0 ? done / elapsed : 0;
  const left = total - processed;
  if (rate > 0 && left > rate) {
    parts.push(tr("remaining") + " ~" + formatDuration(left / rate));
  }
  return " · " + parts.join(" · ");
}

function formatTokens(value: number) {
  return value >= 1000
    ? (value / 1000).toFixed(value < 10000 ? 1 : 0) + "k"
    : String(value);
}
