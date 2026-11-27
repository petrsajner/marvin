"""Semantic browser tools backed by an isolated headless Edge session."""
from __future__ import annotations

import json
from pathlib import Path

from harness.safety import Risk
from harness.tools.base import AgentContext, Tool


def _browser(ctx: AgentContext):
    if ctx.browser is None:
        raise RuntimeError("browser session manager unavailable")
    return ctx.browser


class BrowserOpenTool(Tool):
    name = "browser_open"
    description = ("Open a URL in the isolated headless Edge session. Use browser_snapshot after "
                   "navigation to inspect page text and obtain fresh element refs.")
    parameters = {"url": {"type": "string"}}
    required = ["url"]

    def run(self, ctx: AgentContext, url: str) -> str:
        return json.dumps(_browser(ctx).open(url), ensure_ascii=False, indent=2)


class BrowserSnapshotTool(Tool):
    name = "browser_snapshot"
    parallel_safe = False
    description = ("Return current URL/title, visible page text, and interactive elements with "
                   "stable refs such as e1. Call again after page-changing actions.")
    parameters = {
        "max_text_chars": {"type": "integer", "description": "Visible text limit (default 12000)"},
        "max_elements": {"type": "integer", "description": "Interactive element limit (default 160)"},
    }

    def run(self, ctx: AgentContext, max_text_chars: int = 12_000,
            max_elements: int = 160) -> str:
        return json.dumps(
            _browser(ctx).snapshot(max_text_chars, max_elements),
            ensure_ascii=False, indent=2)


class BrowserClickTool(Tool):
    name = "browser_click"
    description = "Click one element ref returned by the latest browser_snapshot."
    parameters = {"ref": {"type": "string"}}
    required = ["ref"]
    risk = Risk.WRITE

    def run(self, ctx: AgentContext, ref: str) -> str:
        return json.dumps(_browser(ctx).click(ref), ensure_ascii=False, indent=2)


class BrowserFillTool(Tool):
    name = "browser_fill"
    description = "Replace the value of an input/textarea ref returned by browser_snapshot."
    parameters = {"ref": {"type": "string"}, "text": {"type": "string"}}
    required = ["ref", "text"]
    risk = Risk.WRITE

    def run(self, ctx: AgentContext, ref: str, text: str) -> str:
        return json.dumps(_browser(ctx).fill(ref, text), ensure_ascii=False, indent=2)


class BrowserHoverTool(Tool):
    name = "browser_hover"
    description = "Hover one element ref to reveal hover states, menus, or tooltips."
    parameters = {"ref": {"type": "string"}}
    required = ["ref"]

    def run(self, ctx: AgentContext, ref: str) -> str:
        return json.dumps(_browser(ctx).hover(ref), ensure_ascii=False, indent=2)


class BrowserSelectTool(Tool):
    name = "browser_select"
    description = "Select a native dropdown option by value or visible label."
    parameters = {"ref": {"type": "string"}, "value": {"type": "string"}}
    required = ["ref", "value"]
    risk = Risk.WRITE

    def run(self, ctx: AgentContext, ref: str, value: str) -> str:
        return json.dumps(_browser(ctx).select(ref, value), ensure_ascii=False, indent=2)


class BrowserScrollTool(Tool):
    name = "browser_scroll"
    description = "Scroll the page or one scrollable element vertically by a pixel delta."
    parameters = {"delta_y": {"type": "integer"},
                  "ref": {"type": "string", "description": "Optional scrollable element ref"}}
    required = ["delta_y"]

    def run(self, ctx: AgentContext, delta_y: int, ref: str | None = None) -> str:
        return json.dumps(_browser(ctx).scroll(delta_y, ref), ensure_ascii=False, indent=2)


class BrowserUploadTool(Tool):
    name = "browser_upload"
    description = "Set a local file on an <input type=file> ref. Relative paths use the project."
    parameters = {"ref": {"type": "string"}, "path": {"type": "string"}}
    required = ["ref", "path"]
    risk = Risk.WRITE

    def run(self, ctx: AgentContext, ref: str, path: str) -> str:
        target = ctx.resolve(path)
        return json.dumps(_browser(ctx).upload(ref, str(target)), ensure_ascii=False, indent=2)


class BrowserDownloadTool(Tool):
    name = "browser_download"
    description = "Click a ref that starts a download and save it in the active chat browser folder."
    parameters = {"ref": {"type": "string"}}
    required = ["ref"]
    risk = Risk.WRITE

    def run(self, ctx: AgentContext, ref: str) -> str:
        return json.dumps(_browser(ctx).download(ref), ensure_ascii=False, indent=2)


class BrowserViewportTool(Tool):
    name = "browser_viewport"
    description = "Set the isolated browser viewport for desktop, tablet, or mobile layout checks."
    parameters = {"width": {"type": "integer"}, "height": {"type": "integer"}}
    required = ["width", "height"]

    def run(self, ctx: AgentContext, width: int, height: int) -> str:
        return json.dumps(_browser(ctx).viewport(width, height), ensure_ascii=False, indent=2)


class BrowserPressTool(Tool):
    name = "browser_press"
    description = "Press a browser key/combo such as Enter, Escape, Control+L, or Control+Enter."
    parameters = {"key": {"type": "string"}}
    required = ["key"]
    risk = Risk.WRITE

    def run(self, ctx: AgentContext, key: str) -> str:
        return json.dumps(_browser(ctx).press(key), ensure_ascii=False, indent=2)


class BrowserWaitTool(Tool):
    name = "browser_wait"
    description = "Wait briefly for UI/network changes, then return the current page status."
    parameters = {"milliseconds": {"type": "integer"}}
    required = ["milliseconds"]

    def run(self, ctx: AgentContext, milliseconds: int) -> str:
        return json.dumps(_browser(ctx).wait(milliseconds), ensure_ascii=False, indent=2)


class BrowserScreenshotTool(Tool):
    name = "browser_screenshot"
    description = ("Capture the current page and attach it to the next model request for native "
                   "vision analysis. Use after implementing or changing visible UI.")
    parameters = {"full_page": {"type": "boolean", "description": "Capture full page"}}

    def run(self, ctx: AgentContext, full_page: bool = False) -> str:
        result = _browser(ctx).screenshot(full_page)
        path = Path(result["path"])
        ctx.pending_images.append(path)
        return json.dumps(result, ensure_ascii=False, indent=2)


class BrowserConsoleTool(Tool):
    name = "browser_console"
    description = "Read browser console messages incrementally. Reuse the returned cursor."
    parameters = {"cursor": {"type": "integer"}, "max_entries": {"type": "integer"}}

    def run(self, ctx: AgentContext, cursor: int = 0, max_entries: int = 100) -> str:
        return json.dumps(
            _browser(ctx).console(cursor, max_entries), ensure_ascii=False, indent=2)


class BrowserNetworkTool(Tool):
    name = "browser_network"
    description = "Read HTTP responses and failed requests incrementally. Reuse the cursor."
    parameters = {"cursor": {"type": "integer"}, "max_entries": {"type": "integer"}}

    def run(self, ctx: AgentContext, cursor: int = 0, max_entries: int = 100) -> str:
        return json.dumps(
            _browser(ctx).network(cursor, max_entries), ensure_ascii=False, indent=2)


class BrowserCloseTool(Tool):
    name = "browser_close"
    description = "Close the isolated browser session and release its processes."
    parameters = {}

    def run(self, ctx: AgentContext) -> str:
        return json.dumps(_browser(ctx).close(), ensure_ascii=False, indent=2)


class BrowserInspectTool(Tool):
    name = "browser_inspect"
    parallel_safe = False
    description = (
        "Open or inspect a page in the isolated headless Edge browser. "
        "Actions: 'open' (requires url), 'snapshot' (visible text + interactive element refs e1..), "
        "'screenshot' (attaches image for native vision), 'console', 'network', 'close'."
    )
    parameters = {
        "action": {
            "type": "string",
            "enum": ["open", "snapshot", "screenshot", "console", "network", "close"],
            "description": "Inspection action to perform",
        },
        "url": {"type": "string", "description": "URL or local file URL (for action='open')"},
        "max_text_chars": {"type": "integer", "description": "Visible text limit for snapshot (default 12000)"},
        "max_elements": {"type": "integer", "description": "Interactive element limit for snapshot (default 160)"},
        "full_page": {"type": "boolean", "description": "Full-page capture (for action='screenshot')"},
        "cursor": {"type": "integer", "description": "Incremental cursor (for console/network)"},
        "max_entries": {"type": "integer", "description": "Maximum entries (for console/network, default 100)"},
    }
    required = ["action"]
    risk = Risk.SAFE

    def run(self, ctx: AgentContext, action: str, url: str | None = None,
            max_text_chars: int = 12_000, max_elements: int = 160,
            full_page: bool = False, cursor: int = 0, max_entries: int = 100) -> str:
        act = str(action or "").strip().lower()
        if act == "open":
            if not url:
                return "ERROR: browser_inspect(action='open') requires 'url'"
            return BrowserOpenTool().run(ctx, url=url)
        if act == "snapshot":
            return BrowserSnapshotTool().run(ctx, max_text_chars=max_text_chars, max_elements=max_elements)
        if act == "screenshot":
            return BrowserScreenshotTool().run(ctx, full_page=full_page)
        if act == "console":
            return BrowserConsoleTool().run(ctx, cursor=cursor, max_entries=max_entries)
        if act == "network":
            return BrowserNetworkTool().run(ctx, cursor=cursor, max_entries=max_entries)
        if act == "close":
            return BrowserCloseTool().run(ctx)
        return f"ERROR: Unknown browser_inspect action: {action!r}"


class BrowserInteractTool(Tool):
    name = "browser_interact"
    parallel_safe = False
    description = (
        "Interact with the isolated browser page using refs from browser_inspect(action='snapshot'). "
        "Actions: 'click', 'fill', 'hover', 'select', 'scroll', 'press', 'wait', 'upload', 'download', 'viewport'."
    )
    parameters = {
        "action": {
            "type": "string",
            "enum": ["click", "fill", "hover", "select", "scroll", "press", "wait", "upload", "download", "viewport"],
            "description": "Interaction action to perform",
        },
        "ref": {"type": "string", "description": "Element ref from latest snapshot (e.g. 'e1')"},
        "text": {"type": "string", "description": "Text to enter (for action='fill')"},
        "value": {"type": "string", "description": "Option value or label (for action='select')"},
        "delta_y": {"type": "integer", "description": "Vertical scroll pixels (for action='scroll')"},
        "key": {"type": "string", "description": "Key or combo like 'Enter', 'Control+L' (for action='press')"},
        "milliseconds": {"type": "integer", "description": "Wait duration in ms (for action='wait')"},
        "path": {"type": "string", "description": "Local file path (for action='upload')"},
        "width": {"type": "integer", "description": "Viewport width (for action='viewport')"},
        "height": {"type": "integer", "description": "Viewport height (for action='viewport')"},
    }
    required = ["action"]
    risk = Risk.WRITE

    _SAFE_ACTIONS = frozenset({"hover", "scroll", "wait", "viewport"})

    def risk_for(self, args: dict) -> Risk:
        act = str((args or {}).get("action") or "").strip().lower()
        return Risk.SAFE if act in self._SAFE_ACTIONS else Risk.WRITE

    def run(self, ctx: AgentContext, action: str, ref: str | None = None,
            text: str | None = None, value: str | None = None,
            delta_y: int | None = None, key: str | None = None,
            milliseconds: int | None = None, path: str | None = None,
            width: int | None = None, height: int | None = None) -> str:
        act = str(action or "").strip().lower()
        if act == "click":
            if not ref:
                return "ERROR: browser_interact(action='click') requires 'ref'"
            return BrowserClickTool().run(ctx, ref=ref)
        if act == "fill":
            if not ref or text is None:
                return "ERROR: browser_interact(action='fill') requires 'ref' and 'text'"
            return BrowserFillTool().run(ctx, ref=ref, text=text)
        if act == "hover":
            if not ref:
                return "ERROR: browser_interact(action='hover') requires 'ref'"
            return BrowserHoverTool().run(ctx, ref=ref)
        if act == "select":
            if not ref or value is None:
                return "ERROR: browser_interact(action='select') requires 'ref' and 'value'"
            return BrowserSelectTool().run(ctx, ref=ref, value=value)
        if act == "scroll":
            if delta_y is None:
                return "ERROR: browser_interact(action='scroll') requires 'delta_y'"
            return BrowserScrollTool().run(ctx, delta_y=delta_y, ref=ref)
        if act == "press":
            if not key:
                return "ERROR: browser_interact(action='press') requires 'key'"
            return BrowserPressTool().run(ctx, key=key)
        if act == "wait":
            if milliseconds is None:
                return "ERROR: browser_interact(action='wait') requires 'milliseconds'"
            return BrowserWaitTool().run(ctx, milliseconds=milliseconds)
        if act == "upload":
            if not ref or not path:
                return "ERROR: browser_interact(action='upload') requires 'ref' and 'path'"
            return BrowserUploadTool().run(ctx, ref=ref, path=path)
        if act == "download":
            if not ref:
                return "ERROR: browser_interact(action='download') requires 'ref'"
            return BrowserDownloadTool().run(ctx, ref=ref)
        if act == "viewport":
            if width is None or height is None:
                return "ERROR: browser_interact(action='viewport') requires 'width' and 'height'"
            return BrowserViewportTool().run(ctx, width=width, height=height)
        return f"ERROR: Unknown browser_interact action: {action!r}"


def register_browser_tools(registry) -> None:
    registry.register(BrowserInspectTool())
    registry.register(BrowserInteractTool())
    # Keep legacy single-action tool names callable as aliases so existing
    # workflows, tests, and skills keep working without bloating model schemas.
    for legacy in (
        BrowserOpenTool(), BrowserSnapshotTool(), BrowserClickTool(), BrowserFillTool(),
        BrowserHoverTool(), BrowserSelectTool(), BrowserScrollTool(), BrowserUploadTool(),
        BrowserDownloadTool(), BrowserViewportTool(), BrowserPressTool(), BrowserWaitTool(),
        BrowserScreenshotTool(), BrowserConsoleTool(), BrowserNetworkTool(), BrowserCloseTool(),
    ):
        registry.register_alias(legacy.name, legacy)
