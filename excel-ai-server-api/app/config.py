"""
Application configuration — extracted from main.py and hybrid_chat_system.py.

Central place for environment loading, Langfuse client initialization,
and the observe/langfuse_context shims.
"""
from __future__ import annotations

import os
import sys
import types
import logging

from dotenv import load_dotenv

# Load .env FIRST so every subsequent import reads correct values
load_dotenv(override=True)

logger = logging.getLogger("HybridSystem")
_LANGFUSE_ENABLED = os.getenv("LANGFUSE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}

# ============================================================================
# LANGFUSE OBSERVABILITY  (optional – gracefully disabled when not installed)
# ============================================================================
try:
    if not _LANGFUSE_ENABLED:
        raise ImportError("Langfuse disabled by LANGFUSE_ENABLED")

    from langfuse import Langfuse as _Langfuse  # type: ignore
    from langfuse.decorators import observe, langfuse_context  # type: ignore

    # -----------------------------------------------------------------------
    # langfuse v2 CallbackHandler was written for langchain 0.x where
    # callbacks and schema lived under `langchain.*`.  In langchain 1.x they
    # moved fully into `langchain_core`.  Inject compat shims into sys.modules
    # so the old import paths resolve transparently.
    # -----------------------------------------------------------------------
    import langchain_core.callbacks as _lcc
    import langchain_core.callbacks.base as _lcc_base
    import langchain_core.callbacks.manager as _lcc_mgr
    import langchain_core.agents as _lcc_agents
    import langchain_core.documents as _lcc_docs

    def _shim(alias: str, module) -> None:
        """Register `module` under `alias` only if not already present."""
        if alias not in sys.modules:
            sys.modules[alias] = module

    _shim("langchain.callbacks",         _lcc)
    _shim("langchain.callbacks.base",    _lcc_base)
    _shim("langchain.callbacks.manager", _lcc_mgr)
    _shim("langchain.schema.agent",      _lcc_agents)   # AgentAction, AgentFinish
    _shim("langchain.schema.document",   _lcc_docs)     # Document

    # langchain.schema itself must expose AgentAction, AgentFinish, Document
    if "langchain.schema" not in sys.modules:
        _schema_mod = types.ModuleType("langchain.schema")
        _schema_mod.AgentAction = _lcc_agents.AgentAction        # type: ignore[attr-defined]
        _schema_mod.AgentFinish = _lcc_agents.AgentFinish        # type: ignore[attr-defined]
        _schema_mod.Document    = _lcc_docs.Document             # type: ignore[attr-defined]
        sys.modules["langchain.schema"] = _schema_mod

    try:
        from langfuse.callback import CallbackHandler as LangfuseCallbackHandler  # type: ignore
        _LANGFUSE_CALLBACK_AVAILABLE = True
    except (ImportError, ModuleNotFoundError) as _cb_err:
        logger.warning(
            "⚠️  Langfuse CallbackHandler not available — agent-level spans "
            "will be missing. Error: %s", _cb_err
        )
        LangfuseCallbackHandler = None  # type: ignore[assignment,misc]
        _LANGFUSE_CALLBACK_AVAILABLE = False

    # Create the Langfuse client (reads env vars)
    langfuse_client = _Langfuse()
    LANGFUSE_AVAILABLE = True
    
    # Silence the langchain error logs completely since we don't use it anymore
    if hasattr(langfuse_context, "get_current_langchain_handler"):
        langfuse_context.get_current_langchain_handler = lambda *a, **k: None

except ImportError as _lf_import_err:  # pragma: no cover
    langfuse_client = None  # type: ignore[assignment]
    LANGFUSE_AVAILABLE = False
    _LANGFUSE_CALLBACK_AVAILABLE = False

    if not _LANGFUSE_ENABLED:
        logger.info("Langfuse explicitly disabled by LANGFUSE_ENABLED")
    else:
        logger.warning("Langfuse import unavailable; observability disabled: %s", _lf_import_err)

    # --------------------------------------------------------------------------
    # No-op shims so the rest of the codebase runs unchanged without langfuse.
    # --------------------------------------------------------------------------
    def observe(_func=None, *, name: str = "", as_type: str = None, **kwargs):  # type: ignore[misc]
        """No-op replacement for langfuse.decorators.observe."""
        def decorator(func):
            return func
        if _func is not None:
            return _func
        return decorator

    class _FakeLangfuseContext:  # type: ignore[no-redef]
        """No-op replacement for langfuse.decorators.langfuse_context."""
        def update_current_trace(self, **kwargs) -> None: pass
        def update_current_observation(self, **kwargs) -> None: pass
        def get_current_trace_id(self) -> None: return None
        def get_current_trace_url(self) -> None: return None
        def get_current_observation_id(self) -> None: return None

    langfuse_context = _FakeLangfuseContext()  # type: ignore[assignment]
    LangfuseCallbackHandler = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Redis client (used for Langfuse session cookie persistence)
# ---------------------------------------------------------------------------
import redis

redis_client = None
_redis_connect_attempts = 0
_MAX_REDIS_RETRIES = 3

def _try_redis_connect():
    """Attempt to connect to Redis. Returns client or None."""
    global redis_client, _redis_connect_attempts
    if redis_client is not None:
        return redis_client
    if _redis_connect_attempts >= _MAX_REDIS_RETRIES:
        return None
    _redis_connect_attempts += 1
    try:
        client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            password=os.getenv("REDIS_PASSWORD") or None,
            decode_responses=True,
            socket_connect_timeout=3
        )
        client.ping()
        redis_client = client
        logger.info("✅ Redis connected for Langfuse session persistence")
        return client
    except Exception as e:
        logger.warning(f"⚠️  Redis not available (attempt {_redis_connect_attempts}/{_MAX_REDIS_RETRIES}): {e}")
        return None

# Initial connection attempt
_try_redis_connect()



