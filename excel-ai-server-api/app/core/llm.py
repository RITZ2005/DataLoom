"""
LLM utilities — extracted from hybrid_chat_system.py.

Includes:
  - URL normalization helpers
  - invoke_llm_with_retry with exponential backoff
  - create_workspace_llm() factory (DRY — replaces 6 duplicated init blocks)
  - SQL error diagnostic helpers (shared between chat and dashboard pipelines)
  - strip_markdown_fences() for cleaning LLM responses
"""
from __future__ import annotations

import os
import re
import time
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("HybridSystem")


def _normalize_base_url(url: str, default: str) -> str:
    return (url or default).strip().rstrip('/')


def _is_ollama_url(base_url: str) -> bool:
    normalized = _normalize_base_url(base_url, "")
    return normalized.endswith(":11434") or "ollama" in normalized.lower()


def _is_openwebui_url(base_url: str) -> bool:
    normalized = _normalize_base_url(base_url, "")
    return normalized == "http://164.52.196.104:8084"


def invoke_llm_with_retry(llm, prompt, max_retries=2, context_name="LLM call", callbacks=None):
    """Helper method to invoke LLM with automatic retry on connection errors.

    Args:
        llm: The LLM instance (self.llm)
        prompt: The prompt string to send to LLM
        max_retries: Number of retries after initial attempt (default 2 = 3 total attempts)
        context_name: Name for logging what this LLM call is for
        callbacks: Optional list of LangChain callbacks (e.g. Langfuse handler) to attach
                   to this specific invocation for token-level tracing.

    Returns:
        The LLM response content as string

    Raises:
        Exception: If all retries exhausted or permanent error encountered
    """
    if llm is None:
        raise ValueError("LLM instance is None")

    _invoke_config = {"callbacks": callbacks} if callbacks else {}

    for attempt in range(max_retries + 1):
        try:
            response = llm.invoke(prompt, config=_invoke_config).content.strip()
            if attempt > 0:
                logger.info(f"✅ {context_name} succeeded after retry")
            return response
        except Exception as e:
            error_str = str(e)

            # HTTP 4xx errors (client errors) = permanent failures, fail fast
            if "status code: 4" in error_str:
                logger.error(f"{context_name} - {error_str}")
                raise

            # Check for transient connection/network errors
            is_connection_error = (
                "10054" in error_str or "10051" in error_str or "10060" in error_str or
                "Connection" in error_str or "timeout" in error_str.lower() or
                "Connection refused" in error_str or "unreachable" in error_str.lower()
            )

            # Check for transient LLM response errors (server returned None/empty/malformed)
            is_empty_response_error = (
                "model_dump" in error_str or
                "'NoneType'" in error_str or
                "object has no attribute 'content'" in error_str or
                "object has no attribute 'text'" in error_str or
                "Expected a non-empty value" in error_str
            )

            if (is_connection_error or is_empty_response_error) and attempt < max_retries:
                reason = "connection lost" if is_connection_error else "empty/malformed response"
                logger.warning(f"⚠️ {context_name} - {reason}, retrying (attempt {attempt + 1}/{max_retries})...")
                time.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s, 4s...
                continue

            # Either not a retryable error, or this was the last retry - log and raise
            logger.error(f"{context_name} - {error_str}")
            raise


# ═══════════════════════════════════════════════════════════════════════════
# MARKDOWN FENCE STRIPPING
# ═══════════════════════════════════════════════════════════════════════════

def strip_markdown_fences(text: str) -> str:
    """Remove ```json or ``` fences from LLM output, returning raw content."""
    text = (text or "").strip()
    if text.startswith("```json"):
        text = text.split("```json", 1)[1].split("```")[0].strip()
    elif text.startswith("```sql"):
        text = text.split("```sql", 1)[1].split("```")[0].strip()
    elif text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return text


# ═══════════════════════════════════════════════════════════════════════════
# DRY LLM FACTORY  (replaces duplicated init blocks in workspace routers & agents)
# ═══════════════════════════════════════════════════════════════════════════

def get_llm_provider() -> str:
    """Return the active LLM provider as defined in the environment."""
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    if provider in ["openai", "ollama", "openwebui", "auto"]:
        return provider
    return "auto"


def create_workspace_llm(temperature: float = 0, streaming: bool = False, callbacks: List[Any] = None) -> Tuple[Any, Any]:
    """Create LLM + embedding model from env vars.

    Returns:
        (llm, embed_model) tuple — embed_model may be None if unavailable.
    """
    from langchain_openai import ChatOpenAI as _ChatOpenAI

    provider = get_llm_provider()
    _model = os.getenv("LLM_MODEL", "gemma3:27b")

    _ChatOllama = None
    try:
        from langchain_ollama import ChatOllama as _ChatOllama
    except ImportError:
        pass

    llm = None

    if provider == "openai":
        _key = os.getenv("OPENAI_API_KEY", "")
        _base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        llm = _ChatOpenAI(
            model=os.getenv("OPENAI_MODEL_NAME", "gpt-4o"),
            api_key=_key,
            base_url=_base,
            temperature=temperature,
            streaming=streaming,
            callbacks=callbacks,
            timeout=90,
        )
    elif provider == "ollama":
        _base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        if _ChatOllama:
            llm = _ChatOllama(
                model=_model,
                base_url=_base,
                temperature=temperature,
                callbacks=callbacks,
                timeout=90,
            )
        else:
            raise ImportError("langchain_ollama is required for ollama provider but is not installed.")
    elif provider == "openwebui":
        _base = os.getenv("OPENWEBUI_BASE_URL", "http://164.52.196.104:8084").rstrip("/")
        _key = os.getenv("OPENWEBUI_API_KEY", "sk-default-key")
        llm = _ChatOpenAI(
            model=_model,
            base_url=f"{_base}/api",
            api_key=_key,
            temperature=temperature,
            streaming=streaming,
            callbacks=callbacks,
            timeout=90,
        )
    else:
        # "auto" fallback based on URL detection matching legacy format
        _base = _normalize_base_url(
            os.getenv("OPENWEBUI_BASE_URL", "http://164.52.196.104:8084"),
            "http://164.52.196.104:8084",
        )
        _key = os.getenv("OPENWEBUI_API_KEY", "sk-default-key")

        if _is_ollama_url(_base) and _ChatOllama:
            llm = _ChatOllama(model=_model, base_url=_base, temperature=temperature, callbacks=callbacks, timeout=90)
        else:
            llm = _ChatOpenAI(
                model=_model,
                base_url=f"{_base}/api",
                api_key=_key,
                temperature=temperature,
                streaming=streaming,
                callbacks=callbacks,
                timeout=90,
            )

    embed_model = None
    try:
        from app.core.embeddings import OpenWebUIEmbeddings
        embed_base = os.getenv("EMBEDDING_BASE_URL", "http://164.52.196.104:8084").rstrip("/")
        embed_model = OpenWebUIEmbeddings(
            base_url=embed_base,
            api_key=os.getenv("OPENWEBUI_API_KEY", "sk-default-key"),
            model=os.getenv("EMBEDDING_MODEL", "nomic-embed-text:v1.5"),
        )
    except Exception:
        pass

    return llm, embed_model


def create_chat_llm(temperature: float = 0, streaming: bool = False, callbacks: List[Any] = None) -> Tuple[Any, Any]:
    """Compatibility alias for callers that expect the chat-oriented factory name."""
    return create_workspace_llm(temperature=temperature, streaming=streaming, callbacks=callbacks)


# ═══════════════════════════════════════════════════════════════════════════
# SQL ERROR DIAGNOSTICS  (shared by chat retry + dashboard widget retry)
# ═══════════════════════════════════════════════════════════════════════════

def is_numeric_pg_type(type_name: str) -> bool:
    """Check if a PostgreSQL data type is numeric."""
    t = (type_name or "").lower()
    numeric_tokens = (
        "int", "bigint", "smallint", "numeric", "decimal",
        "real", "double", "float", "serial", "bigserial",
    )
    return any(tok in t for tok in numeric_tokens)


def is_text_pg_type(type_name: str) -> bool:
    """Check if a PostgreSQL data type is text-like."""
    t = (type_name or "").lower()
    text_tokens = ("char", "text", "varchar", "name", "citext", "uuid")
    return any(tok in t for tok in text_tokens)


def _identifier_leaf(identifier: str) -> str:
    """Extract the last component of a possibly qualified identifier."""
    ident = (identifier or "").replace('"', '').strip()
    return ident.split(".")[-1].lower() if ident else ""


def extract_sql_error_hints(error_msg: str, columns: List[Dict]) -> Dict[str, Any]:
    """Extract structured hints from a PostgreSQL error to guide SQL recovery.

    Args:
        error_msg: The raw error string from psycopg2.
        columns: List of column metadata dicts with keys: table_name, column_name, data_type.

    Returns:
        Dict with keys: raw_error, expected_type, bad_value, line_expr,
        comparison_column, is_type_mismatch, candidate_text_columns,
        candidate_name_columns, human_summary, recommended_action.
    """
    msg = error_msg or ""
    hints: Dict[str, Any] = {
        "raw_error": msg,
        "expected_type": None,
        "bad_value": None,
        "line_expr": None,
        "comparison_column": None,
        "is_type_mismatch": False,
        "candidate_text_columns": [],
        "candidate_name_columns": [],
        "human_summary": None,
        "recommended_action": None,
    }

    type_match = re.search(
        r'invalid input syntax for type\s+([a-zA-Z0-9_]+):\s+"([^"]+)"', msg, re.IGNORECASE
    )
    if type_match:
        hints["expected_type"] = type_match.group(1)
        hints["bad_value"] = type_match.group(2)

    line_match = re.search(r"LINE\s+\d+:\s+(.+)", msg)
    if line_match:
        hints["line_expr"] = line_match.group(1).strip()

    if hints["line_expr"] and hints["bad_value"]:
        cmp_pattern = rf'(["A-Za-z0-9_\.]+)\s*=\s*\'\s*{re.escape(hints["bad_value"])}\s*\''
        cmp_match = re.search(cmp_pattern, hints["line_expr"], re.IGNORECASE)
        if cmp_match:
            hints["comparison_column"] = cmp_match.group(1)

    expected_type = hints.get("expected_type") or ""
    bad_value = hints.get("bad_value") or ""
    hints["is_type_mismatch"] = is_numeric_pg_type(expected_type) and not bad_value.isdigit()

    for c in columns:
        tname = c.get("table_name")
        cname = c.get("column_name")
        dtype = c.get("data_type")
        if not tname or not cname:
            continue
        fq = f"{tname}.{cname}"
        if is_text_pg_type(dtype):
            hints["candidate_text_columns"].append(fq)
            leaf = cname.lower()
            if any(tok in leaf for tok in ("name", "employee", "person", "user", "full_name", "emp")):
                hints["candidate_name_columns"].append(fq)

    if hints["is_type_mismatch"]:
        col = hints.get("comparison_column") or "unknown column"
        hints["human_summary"] = (
            f"Type mismatch detected: {col} expects numeric values ({expected_type}), "
            f"but SQL compared it with text value '{bad_value}'."
        )
        if hints.get("candidate_name_columns"):
            hints["recommended_action"] = (
                "Use a text/name column for person values instead of numeric id column. "
                f"Try one of: {', '.join(hints['candidate_name_columns'][:5])}."
            )
        elif hints.get("candidate_text_columns"):
            hints["recommended_action"] = (
                "Use a text-compatible column for this filter value or convert the value to numeric id. "
                f"Text candidates: {', '.join(hints['candidate_text_columns'][:5])}."
            )
        else:
            hints["recommended_action"] = (
                "Use a text-compatible column for person names, or compare id column with a numeric literal."
            )
    else:
        hints["human_summary"] = "SQL execution failed; see raw_error and failing_expression for details."
        hints["recommended_action"] = "Adjust predicate types/columns and regenerate SQL with schema-aligned filters."

    return hints


def regenerated_sql_repeats_error(sql: str, error_hints: Dict[str, Any]) -> bool:
    """Detect if regenerated SQL repeats the same bad literal comparison that already failed."""
    if not sql:
        return False
    bad_value = (error_hints or {}).get("bad_value")
    if not bad_value:
        return False

    normalized_sql = re.sub(r"\s+", " ", sql)
    quoted_bad = f"'{bad_value}'"
    if quoted_bad not in normalized_sql:
        return False

    comparison_column = (error_hints or {}).get("comparison_column")
    if not comparison_column:
        return True

    leaf = _identifier_leaf(comparison_column)
    if not leaf:
        return True

    pattern = rf'(["A-Za-z0-9_\.]+)\s*=\s*\'\s*{re.escape(bad_value)}\s*\''
    for m in re.finditer(pattern, normalized_sql, re.IGNORECASE):
        if _identifier_leaf(m.group(1)) == leaf:
            return True
    return False
