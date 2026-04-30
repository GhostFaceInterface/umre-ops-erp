from dotenv import load_dotenv
import os

load_dotenv()

import json
from pathlib import Path
import time
from typing import Any
from uuid import uuid4
from datetime import UTC, datetime

from mcp.server.fastmcp import FastMCP

try:
    from scripts.code_intel_common import (
        DEFAULT_MATCH_COUNT,
        active_model_name,
        estimate_codebase_tokens,
        estimate_tokens,
        get_supabase_client,
        normalize_snippet,
        read_text,
        resolve_codebase_root,
        safe_file_path,
        set_model_config,
    )
    from scripts.search import search_code as semantic_search
except ModuleNotFoundError:
    from code_intel_common import (
        DEFAULT_MATCH_COUNT,
        active_model_name,
        estimate_codebase_tokens,
        estimate_tokens,
        get_supabase_client,
        normalize_snippet,
        read_text,
        resolve_codebase_root,
        safe_file_path,
        set_model_config,
    )
    from search import search_code as semantic_search


set_model_config(os.getenv("CODE_INTEL_MODEL_NAME"), os.getenv("CODE_INTEL_MODEL_REVISION"))

mcp = FastMCP("umre_ops_code_intelligence")
SERVER_SESSION_ID = os.getenv("CODE_INTEL_MCP_SESSION_ID") or str(uuid4())
_BASELINE_CONTEXT: dict[str, int] | None = None


def _codebase_root() -> Path:
    return resolve_codebase_root(None)


def _usage_log_path() -> Path:
    configured = os.getenv("CODE_INTEL_MCP_USAGE_LOG")
    if configured:
        return Path(configured).expanduser().resolve()
    return (_codebase_root() / ".code-intel" / "mcp_usage.jsonl").resolve()


def _now_ms() -> float:
    return time.perf_counter() * 1000


def _json_size_tokens(value: Any) -> int:
    return estimate_tokens(json.dumps(value, ensure_ascii=False, default=str))


def _baseline_context() -> tuple[dict[str, int], float]:
    global _BASELINE_CONTEXT
    started = _now_ms()
    if _BASELINE_CONTEXT is None:
        _BASELINE_CONTEXT = estimate_codebase_tokens(_codebase_root())
    return _BASELINE_CONTEXT, _now_ms() - started


def _record_usage(
    *,
    tool_name: str,
    started_ms: float,
    output: Any,
    args: dict[str, Any],
    timings_ms: dict[str, float],
) -> None:
    baseline, baseline_ms = _baseline_context()
    output_tokens = _json_size_tokens(output)
    baseline_tokens = baseline.get("estimated_tokens") or 0
    saved_tokens = max(baseline_tokens - output_tokens, 0)
    savings_percent = round((saved_tokens / baseline_tokens * 100), 2) if baseline_tokens else 0.0
    timings_ms = {**timings_ms, "baseline_estimate_ms": round(baseline_ms, 2)}
    total_ms = _now_ms() - started_ms
    timings_ms["total_ms"] = round(total_ms, 2)

    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "server_session_id": SERVER_SESSION_ID,
        "project": "umre_ops",
        "model_name": active_model_name(),
        "tool_name": tool_name,
        "args": args,
        "output_estimated_tokens": output_tokens,
        "without_mcp_estimated_tokens": baseline_tokens,
        "estimated_tokens_saved": saved_tokens,
        "estimated_savings_percent": savings_percent,
        "full_codebase_files": baseline.get("files"),
        "full_codebase_characters": baseline.get("characters"),
        "timings_ms": timings_ms,
    }

    log_started = _now_ms()
    path = _usage_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    record["timings_ms"]["usage_log_write_ms"] = round(_now_ms() - log_started, 2)


def _with_usage(tool_name: str, args: dict[str, Any], work) -> Any:
    started = _now_ms()
    work_started = _now_ms()
    output = work()
    timings = {"tool_work_ms": round(_now_ms() - work_started, 2)}
    _record_usage(tool_name=tool_name, started_ms=started, output=output, args=args, timings_ms=timings)
    return output


def _read_usage_records(limit: int | None = None) -> list[dict[str, Any]]:
    path = _usage_log_path()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if limit:
        lines = lines[-limit:]
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _usage_summary(limit: int | None = None) -> dict[str, Any]:
    records = _read_usage_records(limit)
    total_output_tokens = sum(int(row.get("output_estimated_tokens") or 0) for row in records)
    total_without_mcp = sum(int(row.get("without_mcp_estimated_tokens") or 0) for row in records)
    total_saved = max(total_without_mcp - total_output_tokens, 0)
    total_ms = sum(float((row.get("timings_ms") or {}).get("total_ms") or 0) for row in records)
    by_tool: dict[str, dict[str, Any]] = {}
    for row in records:
        tool_name = row.get("tool_name") or "unknown"
        bucket = by_tool.setdefault(
            tool_name,
            {
                "calls": 0,
                "output_estimated_tokens": 0,
                "without_mcp_estimated_tokens": 0,
                "estimated_tokens_saved": 0,
                "total_ms": 0.0,
            },
        )
        bucket["calls"] += 1
        bucket["output_estimated_tokens"] += int(row.get("output_estimated_tokens") or 0)
        bucket["without_mcp_estimated_tokens"] += int(row.get("without_mcp_estimated_tokens") or 0)
        bucket["estimated_tokens_saved"] += int(row.get("estimated_tokens_saved") or 0)
        bucket["total_ms"] = round(bucket["total_ms"] + float((row.get("timings_ms") or {}).get("total_ms") or 0), 2)

    return {
        "usage_log": str(_usage_log_path()),
        "records": len(records),
        "output_estimated_tokens": total_output_tokens,
        "without_mcp_estimated_tokens": total_without_mcp,
        "estimated_tokens_saved": total_saved,
        "estimated_savings_percent": round((total_saved / total_without_mcp * 100), 2) if total_without_mcp else 0.0,
        "total_duration_ms": round(total_ms, 2),
        "total_duration_seconds": round(total_ms / 1000, 2),
        "by_tool": by_tool,
        "note": "Token counts are heuristic estimates for MCP output vs loading all supported source files.",
    }


def _function_rows(name: str, limit: int) -> list[dict[str, Any]]:
    supabase = get_supabase_client()

    symbol_response = (
        supabase.table("code_chunks")
        .select("content,metadata")
        .contains("metadata", {"project": "umre_ops", "symbol_names": [name]})
        .eq("model_name", active_model_name())
        .limit(limit)
        .execute()
    )
    rows = getattr(symbol_response, "data", None) or []

    if not rows:
        fallback_response = (
            supabase.table("code_chunks")
            .select("content,metadata")
            .contains("metadata", {"project": "umre_ops"})
            .eq("model_name", active_model_name())
            .ilike("content", f"%{name}%")
            .limit(limit)
            .execute()
        )
        rows = getattr(fallback_response, "data", None) or []

    return rows


@mcp.tool()
def search_code(query: str, limit: int = DEFAULT_MATCH_COUNT) -> list[dict[str, Any]]:
    """Semantic search over indexed umre_ops code chunks.

    Use this first when looking for implementation logic. It returns compact
    snippets with file paths, scores, and metadata so the agent can decide
    whether to fetch a full file or function next.
    """

    bounded_limit = max(1, min(limit, 20))
    return _with_usage(
        "search_code",
        {"query": query, "limit": bounded_limit},
        lambda: semantic_search(query, bounded_limit),
    )


@mcp.tool()
def get_file(path: str, max_chars: int = 20000) -> dict[str, Any]:
    """Read a file from the local umre_ops codebase after safe path validation.

    Use this only after search has identified a likely relevant file. Large
    files are truncated by default to keep agent context small.
    """

    def work() -> dict[str, Any]:
        file_path = safe_file_path(_codebase_root(), path)
        content = read_text(file_path)
        original_characters = len(content)
        truncated = len(content) > max_chars
        if truncated:
            content = content[:max_chars].rstrip() + "\n..."
        return {
            "file_path": str(file_path.relative_to(_codebase_root())),
            "content": content,
            "truncated": truncated,
            "characters": len(content),
            "original_characters": original_characters,
        }

    return _with_usage("get_file", {"path": path, "max_chars": max_chars}, work)


@mcp.tool()
def get_function(name: str, limit: int = 5, max_chars: int = 20000) -> list[dict[str, Any]]:
    """Find indexed function/class chunks by symbol name or content fallback.

    Use this when the agent knows a function name such as
    get_tour_cost_breakdown. Results include line ranges and compact content.
    """

    bounded_limit = max(1, min(limit, 20))

    def work() -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for row in _function_rows(name, bounded_limit):
            metadata = row.get("metadata") or {}
            content = row.get("content") or ""
            truncated = len(content) > max_chars
            if truncated:
                content = normalize_snippet(content, max_chars)
            results.append(
                {
                    "file_path": metadata.get("file_path"),
                    "language": metadata.get("language"),
                    "symbol_names": metadata.get("symbol_names", []),
                    "symbol_type": metadata.get("symbol_type"),
                    "start_line": metadata.get("start_line"),
                    "end_line": metadata.get("end_line"),
                    "content": content,
                    "truncated": truncated,
                    "metadata": metadata,
                }
            )
        return results

    return _with_usage("get_function", {"name": name, "limit": bounded_limit, "max_chars": max_chars}, work)


@mcp.tool()
def code_index_status() -> dict[str, Any]:
    """Return lightweight status for the active code intelligence index."""

    def work() -> dict[str, Any]:
        supabase = get_supabase_client()
        count_response = (
            supabase.table("code_chunks")
            .select("id", count="exact")
            .eq("model_name", active_model_name())
            .limit(1)
            .execute()
        )
        run_response = (
            supabase.table("code_index_runs")
            .select("*")
            .eq("model_name", active_model_name())
            .order("id", desc=True)
            .limit(1)
            .execute()
        )
        runs = getattr(run_response, "data", None) or []
        return {
            "project": "umre_ops",
            "model_name": active_model_name(),
            "chunk_rows": getattr(count_response, "count", None),
            "latest_run": runs[0] if runs else None,
        }

    return _with_usage("code_index_status", {}, work)


@mcp.tool()
def estimate_context_savings(query: str, limit: int = DEFAULT_MATCH_COUNT) -> dict[str, Any]:
    """Estimate token savings from MCP retrieval vs loading the whole codebase.

    This is an approximate diagnostic tool. It compares indexed semantic-search
    snippets for a query against all supported source files in the codebase.
    """

    bounded_limit = max(1, min(limit, 20))

    def work() -> dict[str, Any]:
        results = semantic_search(query, bounded_limit)
        retrieved_text = "\n\n".join(result.get("snippet") or "" for result in results)
        retrieved_tokens = estimate_tokens(retrieved_text)
        full_context, _ = _baseline_context()
        full_tokens = full_context["estimated_tokens"]
        saved_tokens = max(full_tokens - retrieved_tokens, 0)
        savings_percent = round((saved_tokens / full_tokens * 100), 2) if full_tokens else 0.0

        return {
            "query": query,
            "model_name": active_model_name(),
            "retrieved_chunks": len(results),
            "retrieved_estimated_tokens": retrieved_tokens,
            "full_codebase_files": full_context["files"],
            "full_codebase_characters": full_context["characters"],
            "full_codebase_estimated_tokens": full_tokens,
            "estimated_tokens_saved": saved_tokens,
            "estimated_savings_percent": savings_percent,
            "note": "Token counts are heuristic estimates based on the project tokenizer approximation.",
        }

    return _with_usage("estimate_context_savings", {"query": query, "limit": bounded_limit}, work)


@mcp.tool()
def mcp_usage_summary(limit: int = 100) -> dict[str, Any]:
    """Return aggregate token and duration savings from recent MCP tool calls."""

    bounded_limit = max(1, min(limit, 10000))
    return _usage_summary(bounded_limit)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
