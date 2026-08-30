"""
HybridAgent (Tri-Agent) — Facade / Coordinator.

This module is the public API surface. All business logic has been extracted
into domain-specific mixin classes:

  • IngestionMixin      — file parsing, cleaning, embedding, DB storage
  • FileOpsMixin        — soft/hard delete, restore
  • FormattersMixin     — response formatting, KPI display helpers
  • RoutingMixin        — intent detection, cache check/save/delete
  • AnalyticalPathMixin — pandas agent setup & analytical query path
  • MetadataPathMixin   — metadata / schema query path
  • SemanticPathMixin   — PGVector hybrid retrieval & semantic analysis
  • PlotPathMixin       — chart detection, data extraction, plot path
  • DashboardMixin      — KPI dashboard, insights, comparison, persistence

HybridAgent inherits from all mixins so that `self` references remain
unchanged — zero API surface changes for callers.
"""
from __future__ import annotations

import os
import json
import uuid
import time
from typing import Any, Dict, Optional

import pandas as pd
from psycopg2.extras import execute_values
from dotenv import load_dotenv

# LangChain components
from langchain_openai import ChatOpenAI
try:
    from langchain_ollama import ChatOllama, OllamaEmbeddings  # type: ignore[import-not-found]
    _LANGCHAIN_OLLAMA_AVAILABLE = True
except ImportError:
    ChatOllama = None  # type: ignore[assignment]
    OllamaEmbeddings = None  # type: ignore[assignment]
    _LANGCHAIN_OLLAMA_AVAILABLE = False

# Modular imports from app package
from app.utils.logging import logger, log_full_exception
from app.core.llm import (
    _normalize_base_url, _is_ollama_url, _is_openwebui_url,
)
from app.core.embeddings import OpenWebUIEmbeddings
from app.core.cache import RedisSemanticCache
from app.core.database import DatabaseManager

# Langfuse observability (optional)
from app.config import (
    observe, langfuse_context, LANGFUSE_AVAILABLE,
    LangfuseCallbackHandler, _LANGFUSE_CALLBACK_AVAILABLE
)

# ── Mixin imports (business logic lives here) ────────────────────────
from app.core.ingestion import IngestionMixin
from app.core.file_ops import FileOpsMixin
from app.core.formatters import FormattersMixin
from app.core.routing import RoutingMixin
from app.core.paths.analytical import AnalyticalPathMixin
from app.core.paths.metadata import MetadataPathMixin
from app.core.paths.semantic import SemanticPathMixin
from app.core.paths.plot import PlotPathMixin
from app.core.dashboard.kpi_builder import DashboardMixin
from app.core.paths.sql_agent import SqlAgentPathMixin

load_dotenv()


class HybridAgent(
    IngestionMixin,
    FileOpsMixin,
    FormattersMixin,
    RoutingMixin,
    AnalyticalPathMixin,
    MetadataPathMixin,
    SemanticPathMixin,
    PlotPathMixin,
    DashboardMixin,
    SqlAgentPathMixin,
):
    """
    Public facade for the Tri-Agent query-processing engine.

    All business logic is delegated to mixin superclasses.
    This class only contains:
      • __init__           — wiring, model setup, data loading
      • from_dataframe     — lightweight board-file constructor
      • _trace_path_output — Langfuse observability helper
      • _get_embedding_dim — embedding probe
      • _init_redis_cache  — Redis semantic cache bootstrap
    """

    def __init__(
        self,
        file_path: str = None,
        filename: str = None,
        file_uuid: str = None,
        load_existing: bool = False,
        user_id: str = None,
        project_id: str = None,
        subproject_id: str = None,
        progress_callback: callable = None,
        sheet_name: str = None,
        file_group_id: str = None,
        mode: str = None,
    ):
        self.db = DatabaseManager()
        self.user_id = user_id
        self.project_id = project_id
        self.subproject_id = subproject_id
        self.progress_callback = progress_callback
        self.sheet_name = sheet_name
        self.file_group_id = file_group_id
        self.mode = mode
        self.sql_table_names = None
        self._sql_connection_mode = False

        if progress_callback:
            progress_callback("initializing", 3, 100, "Connecting to database...")

        
        # Store file_uuid - generate if not provided
        self.file_uuid = file_uuid or str(uuid.uuid4())
        self.filename = filename
        
        # NEW: Default deleted state
        self.is_deleted = False
        
        # 1. SETUP MODELS
        embedding_model = os.getenv("EMBEDDING_MODEL", "nomic-embed-text:v1.5")
        embedding_base_url = _normalize_base_url(
            os.getenv("EMBEDDING_BASE_URL", "http://164.52.196.104:8084"),
            "http://164.52.196.104:8084",
        )
        embedding_api_key = os.getenv("OPENWEBUI_API_KEY", "sk-default-key")
        embedding_provider = os.getenv("EMBEDDING_PROVIDER", "auto").strip().lower()

        if embedding_provider == "openai":
            # Cloud-compatible: works with OpenAI, Jina AI, Voyage AI, Together AI, etc.
            from langchain_openai import OpenAIEmbeddings as _OpenAIEmbeddings
            _emb_key = os.getenv("EMBEDDING_API_KEY", os.getenv("OPENAI_API_KEY", ""))
            _emb_base = os.getenv("EMBEDDING_BASE_URL", "https://api.openai.com/v1")
            logger.info(f"🧠 Embeddings provider: OpenAI-compatible ({_emb_base})")
            self.embed_model = _OpenAIEmbeddings(
                model=embedding_model,
                openai_api_key=_emb_key,
                openai_api_base=_emb_base,
            )
        elif _is_ollama_url(embedding_base_url):
            if not _LANGCHAIN_OLLAMA_AVAILABLE:
                raise ModuleNotFoundError(
                    "langchain-ollama is required for Ollama embeddings. "
                    "Install with: pip install langchain-ollama"
                )
            logger.info(f"🧠 Embeddings provider: Ollama ({embedding_base_url})")
            self.embed_model = OllamaEmbeddings(
                model=embedding_model,
                base_url=embedding_base_url,
            )
        else:
            if _is_openwebui_url(embedding_base_url):
                logger.info(f"🧠 Embeddings provider: OpenWebUI ({embedding_base_url})")
            else:
                logger.warning(
                    f"⚠️ Unknown EMBEDDING_BASE_URL '{embedding_base_url}', defaulting to OpenWebUI-compatible embeddings API"
                )
            self.embed_model = OpenWebUIEmbeddings(
                base_url=embedding_base_url,
                api_key=embedding_api_key,
                model=embedding_model,
            )

        if progress_callback:
            progress_callback("initializing", 5, 100, "Setting up embedding model...")
        self.embedding_dim = self._get_embedding_dim()
        logger.info(f"✅ Embedding dimension detected: {self.embedding_dim}")
        
        if progress_callback:
            progress_callback("initializing", 8, 100, "Connecting to cache...")
        self.semantic_cache = self._init_redis_cache()
        self.semantic_cache_threshold = float(
            os.getenv("REDIS_SEMANTIC_CACHE_THRESHOLD", "0.15")
        )
        # Stores the normalized query from check_cache() so save_to_cache()
        # can reuse it without a second LLM call.
        self._last_normalized_query: Optional[str] = None
        self._last_normalized_query_source: Optional[str] = None
        
        # SERVER_TYPE env var drives all API path decisions — no code changes needed
        from app.core.llm import create_workspace_llm
        self.llm, _ = create_workspace_llm(temperature=0, streaming=False)
        
        if progress_callback:
            progress_callback("initializing", 10, 100, "Models ready, loading data...")

        # 2. LOAD DATA
        if load_existing and (filename or file_uuid):
            self._load_existing_metadata(filename=filename, file_uuid=file_uuid)
            if not getattr(self, "_sql_connection_mode", False):
                self.df = self._fetch_df_from_db()
            else:
                self.df = None
        elif file_path and filename:
            self.file_path = file_path
            # Generate table name from UUID instead of filename hash
            self.table_name = f"data_{self.file_uuid.replace('-', '')[:16]}"
            self.df = self._ingest_file(self.progress_callback)
        else:
            raise ValueError("Must provide file_path/filename OR set load_existing=True with filename/file_uuid")

        # 3. INITIALIZE PANDAS AGENT
        if not getattr(self, "_sql_connection_mode", False):
            self._init_pandas_agent()
        else:
            self.pandas_agent = None

    # ── Lightweight board-file constructor (no embeddings) ────────────
    @classmethod
    def from_dataframe(cls, file_path: str, filename: str, file_uuid: str | None = None):
        """Create an agent from a CSV/Excel file WITHOUT embeddings or vector storage.
        Used for Insight Board file uploads — only creates a PG data table + column_stats.
        Returns a partially-initialised agent suitable for generate_kpi_dashboard().
        """
        obj = object.__new__(cls)
        obj.db = DatabaseManager()
        obj.file_uuid = file_uuid or str(uuid.uuid4())
        obj.filename = filename
        obj.user_id = None
        obj.project_id = None
        obj.subproject_id = None
        obj.progress_callback = None
        obj.sheet_name = None
        obj.file_group_id = None
        obj.is_deleted = False
        obj.table_name = f"board_{obj.file_uuid.replace('-', '')[:16]}"

        # Parse file
        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.csv':
            df = pd.read_csv(file_path)
        else:
            df = pd.read_excel(file_path)

        df, sql_types = obj._clean_dataframe(df)
        obj.columns = df.columns.tolist()
        obj.column_stats = obj._generate_metadata_profile(df)

        # Create PG table (NO embedding column)
        with obj.db.get_connection() as conn:
            with conn.cursor() as cur:
                col_defs = [f'"{col}" {sql_types[col]}' for col in obj.columns]
                cur.execute(f'CREATE TABLE IF NOT EXISTS {obj.table_name} ({", ".join(col_defs)});')
            conn.commit()

        # Bulk-insert data
        from psycopg2.extras import execute_values as _ev
        cols_str = ", ".join(f'"{c}"' for c in obj.columns)
        rows = []
        for _, row in df.iterrows():
            vals = []
            for v in row:
                try:
                    vals.append(None if (pd.isna(v) or str(v).lower() == 'nan') else v)
                except Exception:
                    vals.append(v)
            rows.append(tuple(vals))

        with obj.db.get_connection() as conn:
            with conn.cursor() as cur:
                _ev(cur, f'INSERT INTO {obj.table_name} ({cols_str}) VALUES %s', rows)
            conn.commit()

        obj.df = df

        # Minimal LLM + agent setup so generate_kpi_dashboard works
        from app.core.llm import create_workspace_llm
        obj.llm, _ = create_workspace_llm(temperature=0, streaming=False)

        # Skip embedding model, redis cache, pandas agent — not needed for dashboard gen
        obj.embed_model = None
        obj.embedding_dim = 0
        obj.semantic_cache = None
        obj.semantic_cache_threshold = 0
        obj._last_normalized_query = None
        obj._last_normalized_query_source = None
        obj.pandas_agent = None
        obj.code_fixer_callback = None

        logger.info(f"✅ Board agent created for {filename} ({len(df)} rows, no embeddings)")
        return obj

    # ── Observability helper ─────────────────────────────────────────
    @observe(as_type="span", name="path.output")
    def _trace_path_output(
        self,
        path_name: str,
        query: str,
        output_value: Any,
        exit_point: str,
        status: str = "success",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record final path output on a dedicated child span to avoid premature parent output updates."""
        if isinstance(output_value, str):
            output_text = output_value
        else:
            try:
                output_text = json.dumps(output_value, ensure_ascii=False, default=str)
            except Exception:
                output_text = str(output_value)

        langfuse_context.update_current_observation(
            input={
                "path": path_name,
                "query": query,
                "exit_point": exit_point,
            },
            metadata={
                "file_uuid": self.file_uuid,
                "filename": self.filename,
            },
            tags=["path-output", path_name.lower().replace(" ", "-")],
        )

        payload: Dict[str, Any] = {
            "status": status,
            "output_source": path_name,
            "exit_point": exit_point,
            "final_output_preview": output_text[:1000],
            "final_output_length": len(output_text),
        }
        if extra:
            payload.update(extra)

        langfuse_context.update_current_observation(output=payload)

    # ── Infrastructure helpers ───────────────────────────────────────
    def _get_embedding_dim(self) -> int:
        try:
            sample = self.embed_model.embed_query("dimension probe")
            return len(sample)
        except Exception as e:
            log_full_exception(e, "Failed to detect embedding dimension; defaulting to 1024")
            return int(os.getenv("EMBEDDING_DIM", "1024"))

    def _init_redis_cache(self) -> RedisSemanticCache:
        host = os.getenv("REDIS_HOST", "localhost")
        port = int(os.getenv("REDIS_PORT", "6379"))
        password = os.getenv("REDIS_PASSWORD")
        ttl_seconds = int(os.getenv("REDIS_SEMANTIC_CACHE_TTL", "86400"))
        index_name = os.getenv("REDIS_SEMANTIC_CACHE_INDEX", "semantic_cache_idx")
        key_prefix = os.getenv("REDIS_SEMANTIC_CACHE_PREFIX", "semantic_cache:")

        cache = RedisSemanticCache(
            host=host,
            port=port,
            password=password,
            ttl_seconds=ttl_seconds,
            index_name=index_name,
            key_prefix=key_prefix
        )
        try:
            cache.ensure_index(self.embedding_dim)
        except Exception as e:
            log_full_exception(e, "Failed to initialize Redis semantic cache index")
        return cache
