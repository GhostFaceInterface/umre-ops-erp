from dotenv import load_dotenv
import os

load_dotenv()

import argparse
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse

try:
    from scripts.code_intel_common import (
        DEFAULT_MATCH_COUNT,
        active_model_name,
        get_supabase_client,
        read_text,
        resolve_codebase_root,
        safe_file_path,
        set_model_config,
    )
    from scripts.search import search_code
except ModuleNotFoundError:
    from code_intel_common import (
        DEFAULT_MATCH_COUNT,
        active_model_name,
        get_supabase_client,
        read_text,
        resolve_codebase_root,
        safe_file_path,
        set_model_config,
    )
    from search import search_code


app = FastAPI(
    title="umre_ops Code Intelligence MCP Server",
    version="1.0.0",
    description="Agent-ready semantic code search, file access, and function lookup for umre_ops.",
)


def codebase_root() -> Path:
    return resolve_codebase_root(None)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "project": "umre_ops"}


@app.get("/search")
def search_endpoint(
    q: str = Query(..., min_length=1),
    limit: int = Query(DEFAULT_MATCH_COUNT, ge=1, le=20),
) -> list[dict[str, Any]]:
    return search_code(q, limit)


@app.get("/file", response_class=PlainTextResponse)
def file_endpoint(path: str = Query(..., min_length=1)) -> str:
    try:
        file_path = safe_file_path(codebase_root(), path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return read_text(file_path)


@app.get("/function")
def function_endpoint(name: str = Query(..., min_length=1), limit: int = Query(5, ge=1, le=20)) -> list[dict[str, Any]]:
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

    results: list[dict[str, Any]] = []
    for row in rows:
        metadata = row.get("metadata") or {}
        results.append(
            {
                "file_path": metadata.get("file_path"),
                "language": metadata.get("language"),
                "symbol_names": metadata.get("symbol_names", []),
                "symbol_type": metadata.get("symbol_type"),
                "start_line": metadata.get("start_line"),
                "end_line": metadata.get("end_line"),
                "content": row.get("content"),
                "metadata": metadata,
            }
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the umre_ops code intelligence FastAPI server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--model", default=active_model_name(), help="Embedding model used by /search.")
    parser.add_argument("--model-revision", default=None, help="Optional Hugging Face model revision.")
    args = parser.parse_args()
    set_model_config(args.model, args.model_revision)
    uvicorn.run(app, host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
