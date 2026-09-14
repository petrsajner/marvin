"""Persistent research ledger and staged synthesis without filtering out sources."""
from __future__ import annotations

import json
import hashlib
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable


class ResearchLedger:
    def __init__(self, session):
        self.session = session
        self.path = session.dir / "research.json"
        self.data = self._load()
        self.run_id: str | None = None

    def begin(self, question: str) -> str:
        self.run_id = f"research-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self.data.setdefault("runs", []).append({
            "id": self.run_id,
            "question": question,
            "created": time.time(),
            "queries": [],
            "plan": None,
            "candidates": [],
            "sources": [],
            "status": "collecting",
            "synthesis": None,
        })
        self._save()
        return self.run_id

    def set_plan(self, plan: dict) -> None:
        run = self.current()
        if run is None:
            return
        run["plan"] = plan
        self._save()

    def current(self) -> dict | None:
        if self.run_id:
            return next((run for run in self.data.get("runs", [])
                         if run.get("id") == self.run_id), None)
        runs = self.data.get("runs", [])
        return runs[-1] if runs else None

    def record_query(self, query: str, results: list[tuple[str, str, str]]) -> None:
        run = self.current()
        if run is None:
            self.begin(query)
            run = self.current()
        run["queries"].append({"query": query, "timestamp": time.time()})
        known = {item.get("url") for item in run["candidates"]}
        for title, url, snippet in results:
            if not url or url in known:
                continue
            run["candidates"].append({
                "title": title,
                "url": url,
                "snippet": snippet,
                "found_by_query": query,
            })
            known.add(url)
        self._save()

    def record_source(self, url: str, title: str, content: str,
                      content_type: str = "text/html", requested_url: str | None = None,
                      max_chars: int = 200_000) -> str:
        run = self.current()
        if run is None:
            self.begin(url)
            run = self.current()
        existing = next((source for source in run["sources"] if source.get("url") == url), None)
        source_id = existing.get("id") if existing else f"S{len(run['sources']) + 1}"
        record = {
            "id": source_id,
            "title": title or url,
            "url": url,
            "requested_url": requested_url or url,
            "content_type": content_type,
            "content": content[:max_chars],
            "content_truncated": len(content) > max_chars,
            "original_char_count": len(content),
            "fetched_at": time.time(),
        }
        if existing:
            existing.update(record)
        else:
            run["sources"].append(record)
        self._save()
        return source_id

    def status(self) -> dict:
        run = self.current()
        if run is None:
            return {"active": False, "queries": 0, "candidates": 0, "sources": 0,
                    "status": "idle"}
        return {
            "active": True,
            "run_id": run["id"],
            "question": run["question"],
            "queries": len(run["queries"]),
            "candidates": len(run["candidates"]),
            "sources": len(run["sources"]),
            "status": run["status"],
        }

    def complete(self, synthesis: str) -> None:
        run = self.current()
        if run is None:
            return
        run["status"] = "complete"
        run["completed_at"] = time.time()
        run["synthesis"] = synthesis
        self._save()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"runs": []}
        except (OSError, ValueError):
            return {"runs": []}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)


class GenerationStopped(RuntimeError):
    def __init__(self, text: str = ""):
        super().__init__("Generation stopped by the user")
        self.text = text


def _ask(llm, prompt: str, should_stop: Callable[[], bool] | None = None,
         on_text: Callable[[str], None] | None = None,
         on_reasoning: Callable[[str], None] | None = None) -> str:
    result = llm.stream(
        [
            {"role": "system", "content": (
                "You are a loss-aware research synthesizer. Preserve all information relevant "
                "to the question, including contradictions, negative findings, uncertainty, and "
                "minority claims. Never filter or rank sources by perceived credibility."
            )},
            {"role": "user", "content": prompt},
        ],
        sampling=llm.cfg.sampling(False),
        thinking=False,
        on_text=on_text,
        on_reasoning=on_reasoning,
        should_stop=should_stop,
    )
    text = (result.content or "").strip()
    if result.stopped:
        raise GenerationStopped(text)
    if not text:
        raise RuntimeError("The model returned an empty response")
    return text


def _fallback_plan(question: str) -> dict:
    return {
        "subquestions": [question],
        "search_angles": [
            "direct evidence and explanations",
            "conflicting, negative, and minority findings",
            "limitations, uncertainty, and missing information",
        ],
        "source_types_to_include": ["all relevant web and project sources"],
        "known_constraints": [
            "The automatic planner returned no usable structured response; fallback plan applied."
        ],
    }


def plan_research(llm, question: str, project_catalog: str = "",
                  should_stop: Callable[[], bool] | None = None) -> dict:
    prompt = f"""Create a research plan for the user's question:
{question}

Available project documents:
{project_catalog or 'none'}

Return JSON only with this schema:
{{
  "subquestions": ["..."],
  "search_angles": ["..."],
  "source_types_to_include": ["..."],
  "known_constraints": ["..."]
}}

Cover the question broadly. Do not rank, filter, or exclude possible sources by perceived
credibility, origin, popularity, or official status. Include angles that could reveal conflicting,
negative, uncertain, or minority information.
"""
    try:
        raw = _ask(llm, prompt, should_stop=should_stop)
    except RuntimeError as exc:
        if "empty response" not in str(exc):
            raise
        return _fallback_plan(question)
    try:
        plan = json.loads(raw)
    except ValueError:
        start, end = raw.find("{"), raw.rfind("}")
        try:
            plan = json.loads(raw[start:end + 1]) if 0 <= start < end else None
        except ValueError:
            plan = None
    if not isinstance(plan, dict):
        plan = {"subquestions": [question], "search_angles": [],
                "source_types_to_include": [], "known_constraints": [],
                "raw_plan": raw}
    for key in ("subquestions", "search_angles", "source_types_to_include", "known_constraints"):
        if not isinstance(plan.get(key), list):
            plan[key] = []
    return plan


def synthesize_research(llm, run: dict,
                        should_stop: Callable[[], bool] | None = None,
                        on_text: Callable[[str], None] | None = None,
                        on_reasoning: Callable[[str], None] | None = None,
                        save_progress: Callable[[], None] | None = None) -> str:
    question = run.get("question", "")
    cache = run.setdefault("evidence_notes", {})

    def extract(prompt):
        key = hashlib.sha256(prompt.encode()).hexdigest()
        if key not in cache:
            cache[key] = _ask(llm, prompt, should_stop=should_stop)
            run["synthesis_progress"] = {"phase": "evidence", "completed_parts": len(cache)}
            if save_progress:
                save_progress()
        return cache[key]

    evidence: list[str] = []
    for source in run.get("sources", []):
        content = source.get("content", "")
        source_id = source["id"]
        header = f"[{source_id}] {source.get('title')}\nURL: {source.get('url')}"
        if len(content) <= 16_000:
            evidence.append(f"{header}\n{content}")
            continue
        chunks = [content[index:index + 16_000] for index in range(0, len(content), 16_000)]
        notes: list[str] = []
        for index, chunk in enumerate(chunks, 1):
            notes.append(extract(
                f"Research question: {question}\n\nSource {source_id}, chunk {index}/{len(chunks)}:\n"
                f"{chunk}\n\nExtract every detail relevant to the question. Preserve conflicting, "
                "negative, uncertain, or unusual claims. Do not judge source credibility."
            ))
        evidence.append(f"{header}\n" + "\n".join(notes))

    candidate_lines = [
        f"- {item.get('title') or "(untitled)"} — {item.get('url')}"
        for item in run.get("candidates", [])
    ]
    if not evidence:
        raise RuntimeError("No sources were loaded for synthesis")

    combined = "\n\n".join(evidence)
    if len(combined) > 60_000:
        bundles = [combined[index:index + 50_000] for index in range(0, len(combined), 50_000)]
        partials = [
            extract(
                f"Research question: {question}\n\nEvidence bundle {index + 1}/{len(bundles)}:\n"
                f"{bundle}\n\nCreate a loss-aware evidence synthesis. Preserve every source ID, "
                "all relevant claims, contradictions, uncertainty, and negative findings."
            )
            for index, bundle in enumerate(bundles)
        ]
        combined = "\n\n".join(partials)

    source_ids = [source["id"] for source in run.get("sources", [])]
    final_prompt = f"""Original user question:
{question}

Processed evidence:
{combined}

All candidate sources found (including sources not fetched):
{chr(10).join(candidate_lines) or "- none"}

Create a clear final synthesis in the language of the question. Adapt its length and structure to the question;
the following topics are guidance, not a requirement for a long section each:
1. Direct answer
2. Key findings
3. Detailed synthesis by topic
4. Contradictions and alternative views
5. Uncertainty and missing evidence
6. Practical conclusion
7. Sources used
8. Other sources found but not fetched

Rules:
- Do not silently omit relevant information.
- Do not assess or filter sources by credibility or origin.
- Separate source claims from your own inferences.
- Reference each claim using [{'], ['.join(source_ids)}] for its source.
- For key claims, also identify a specific passage or page when available.
- Include every processed source ID and URL in the final source list.
"""
    synthesis = _ask(llm, final_prompt, should_stop=should_stop,
                     on_text=on_text, on_reasoning=on_reasoning)
    missing = [source_id for source_id in source_ids if f"[{source_id}]" not in synthesis]
    if missing:
        synthesis = _ask(llm, (
            f"Original question: {question}\n\nPrevious synthesis:\n{synthesis}\n\n"
            f"Missing sources in the coverage check: {', '.join(missing)}\n\n"
            "Revise the synthesis while preserving its existing content and explicitly including every "
            "missing source ID in the text or source list. Do not filter sources by trustworthiness."
        ), should_stop=should_stop, on_text=on_text, on_reasoning=on_reasoning)
    run["synthesis_progress"] = {"phase": "complete", "completed_parts": len(cache)}
    run["citation_coverage"] = {source_id: f"[{source_id}]" in synthesis for source_id in source_ids}
    if save_progress:
        save_progress()
    return synthesis
