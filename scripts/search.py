from dotenv import load_dotenv
import os

load_dotenv()

import argparse
import sys
from typing import Any

try:
    from scripts.code_intel_common import (
        DEFAULT_MATCH_COUNT,
        add_common_arguments,
        active_model_name,
        configure_logging,
        encode_query,
        get_embedding_model,
        get_supabase_client,
        json_dumps,
        normalize_snippet,
        set_model_config,
    )
except ModuleNotFoundError:
    from code_intel_common import (
        DEFAULT_MATCH_COUNT,
        add_common_arguments,
        active_model_name,
        configure_logging,
        encode_query,
        get_embedding_model,
        get_supabase_client,
        json_dumps,
        normalize_snippet,
        set_model_config,
    )


_MODEL = None


def get_model():
    global _MODEL
    if _MODEL is None:
        _MODEL = get_embedding_model()
    return _MODEL


def search_code(query: str, match_count: int = DEFAULT_MATCH_COUNT) -> list[dict[str, Any]]:
    if not query or not query.strip():
        return []

    model = get_model()
    supabase = get_supabase_client()
    query_embedding = encode_query(model, query)
    response = supabase.rpc(
        "match_code_chunks",
        {
            "query_embedding": query_embedding,
            "match_count": match_count,
            "query_model_name": active_model_name(),
        },
    ).execute()

    results: list[dict[str, Any]] = []
    for row in getattr(response, "data", None) or []:
        metadata = row.get("metadata") or {}
        results.append(
            {
                "file_path": metadata.get("file_path"),
                "snippet": normalize_snippet(row.get("content") or ""),
                "score": row.get("similarity"),
                "metadata": metadata,
            }
        )
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search indexed umre_ops code in Supabase pgvector.")
    add_common_arguments(parser)
    parser.add_argument("query", help="Natural-language or code query.")
    parser.add_argument("--limit", type=int, default=DEFAULT_MATCH_COUNT, help="Number of matches to return.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.verbose)
    set_model_config(args.model, args.model_revision)
    print(json_dumps(search_code(args.query, args.limit)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
