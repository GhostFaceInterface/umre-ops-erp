from dotenv import load_dotenv
import os

load_dotenv()

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

try:
    from scripts.code_intel_common import (
        DEFAULT_MATCH_COUNT,
        active_model_name,
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


def _codebase_root() -> Path:
    return resolve_codebase_root(None)


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
    return semantic_search(query, bounded_limit)


@mcp.tool()
def get_file(path: str, max_chars: int = 20000) -> dict[str, Any]:
    """Read a file from the local umre_ops codebase after safe path validation.

    Use this only after search has identified a likely relevant file. Large
    files are truncated by default to keep agent context small.
    """

    file_path = safe_file_path(_codebase_root(), path)
    content = read_text(file_path)
    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars].rstrip() + "\n..."
    return {
        "file_path": str(file_path.relative_to(_codebase_root())),
        "content": content,
        "truncated": truncated,
        "characters": len(content),
    }


@mcp.tool()
def get_function(name: str, limit: int = 5, max_chars: int = 20000) -> list[dict[str, Any]]:
    """Find indexed function/class chunks by symbol name or content fallback.

    Use this when the agent knows a function name such as
    get_tour_cost_breakdown. Results include line ranges and compact content.
    """

    bounded_limit = max(1, min(limit, 20))
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


@mcp.tool()
def code_index_status() -> dict[str, Any]:
    """Return lightweight status for the active code intelligence index."""

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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
