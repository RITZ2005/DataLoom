"""
SQL Connector — handles MySQL and PostgreSQL external databases.

Uses SQLAlchemy for connection management and Pandas for chunked
extraction into Parquet files.
"""
from __future__ import annotations

import os
import re
import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from app.core.etl.connectors.base_connector import BaseConnector, ConnectionConfig

logger = logging.getLogger("HybridSystem")

# Optional imports — installed via requirements
try:
    from sqlalchemy import create_engine, inspect, text
    _SQLALCHEMY_AVAILABLE = True
except ImportError:
    _SQLALCHEMY_AVAILABLE = False


class SQLConnector(BaseConnector):
    """
    Connector for MySQL and PostgreSQL databases via SQLAlchemy.

    Streams large tables in chunks to avoid RAM exhaustion.
    """

    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        if not _SQLALCHEMY_AVAILABLE:
            raise ImportError(
                "sqlalchemy is required for SQL connectors. "
                "Install it with: pip install sqlalchemy pymysql"
            )

    # ── lifecycle ─────────────────────────────────────────────────────

    def _build_uri(self) -> str:
        """Build a SQLAlchemy connection URI from config."""
        import urllib.parse
        c = self.config
        if c.db_type == "mysql":
            # pymysql is the pure-Python MySQL driver
            driver = "mysql+pymysql"
        elif c.db_type == "postgresql":
            driver = "postgresql+psycopg2"
        else:
            raise ValueError(f"Unsupported SQL db_type: {c.db_type}")

        encoded_user = urllib.parse.quote_plus(c.username or "")
        encoded_pass = urllib.parse.quote_plus(c.password or "")
        uri = f"{driver}://{encoded_user}:{encoded_pass}@{c.host}:{c.port}/{c.database}"
        return uri

    def connect(self) -> None:
        uri = self._build_uri()
        self._engine = create_engine(
            uri,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            connect_args=self.config.options.get("connect_args", {}),
        )
        logger.info(
            "[SQLConnector] Connected to %s @ %s:%s/%s",
            self.config.db_type, self.config.host, self.config.port, self.config.database,
        )

    def disconnect(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            logger.info("[SQLConnector] Engine disposed")

    # ── discovery ─────────────────────────────────────────────────────

    def test_connection(self) -> bool:
        try:
            if self._engine is None:
                self.connect()
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error("[SQLConnector] Connection test failed: %s", e)
            return False

    def list_tables(self) -> List[Dict[str, Any]]:
        if self._engine is None:
            self.connect()
        insp = inspect(self._engine)
        tables = []
        for table_name in insp.get_table_names():
            columns = []
            for col in insp.get_columns(table_name):
                columns.append({
                    "name": col["name"],
                    "type": str(col["type"]),
                })
            # Attempt row count (fast estimate)
            row_count = None
            try:
                with self._engine.connect() as conn:
                    result = conn.execute(
                        text(f"SELECT COUNT(*) FROM \"{table_name}\"")
                        if self.config.db_type == "postgresql"
                        else text(f"SELECT COUNT(*) FROM `{table_name}`")
                    )
                    row_count = result.scalar()
            except Exception:
                pass  # Non-critical

            tables.append({
                "name": table_name,
                "row_count": row_count,
                "columns": columns,
            })
        return tables

    def preview_table(
        self, table_name: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        import json
        if self._engine is None:
            self.connect()
        quote = '"' if self.config.db_type == "postgresql" else '`'
        query = f"SELECT * FROM {quote}{table_name}{quote} LIMIT {limit}"
        df = pd.read_sql(query, self._engine)
        # Convert to JSON string then back to Python objects to safely 
        # convert numpy types, NaNs, and datetimes into standard JSON-serializable objects.
        json_str = df.to_json(orient="records", date_format="iso")
        return json.loads(json_str)

    # ── extraction ────────────────────────────────────────────────────

    def extract_to_parquet(
        self,
        table_names: List[str],
        output_dir: str,
        chunk_size: int = 100_000,
        limit: int | None = None,
        datasets: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        if self._engine is None:
            self.connect()

        os.makedirs(output_dir, exist_ok=True)
        generated_files: List[str] = []

        extraction_units: List[Dict[str, Any]] = []
        if datasets:
            extraction_units.extend(datasets)
        elif table_names:
            extraction_units.extend({"table_name": table} for table in table_names)

        if not extraction_units:
            raise ValueError("No extract sources provided")

        for idx, unit in enumerate(extraction_units):
            table_name = (unit.get("table_name") or "").strip()
            custom_query = (unit.get("custom_query") or "").strip()
            output_name = (unit.get("output_name") or table_name or f"dataset_{idx + 1}").strip()
            is_custom_query = bool(custom_query)

            if custom_query:
                query = self._normalize_read_query(custom_query, limit=limit)
                log_name = f"query:{output_name}"
            else:
                if not table_name:
                    raise ValueError("Dataset requires table_name or custom_query")
                quote = '"' if self.config.db_type == "postgresql" else '`'
                query = f"SELECT * FROM {quote}{table_name}{quote}"
                if limit is not None:
                    query += f" LIMIT {limit}"
                log_name = table_name

            out_path = os.path.join(output_dir, f"{self._sanitize_output_name(output_name)}.parquet")
            logger.info("[SQLConnector] Extracting %s (chunk_size=%d)...", log_name, chunk_size)

            # Stream in chunks and write consolidated parquet
            chunks: List[pd.DataFrame] = []
            total_rows = 0
            for chunk_df in pd.read_sql(query, self._engine, chunksize=chunk_size):
                if is_custom_query and limit is not None:
                    remaining = limit - total_rows
                    if remaining <= 0:
                        break
                    if len(chunk_df) > remaining:
                        chunk_df = chunk_df.head(remaining)

                chunks.append(chunk_df)
                total_rows += len(chunk_df)
                logger.info(
                    "[SQLConnector]   %s: fetched %d rows so far...",
                    log_name, total_rows,
                )

                if is_custom_query and limit is not None and total_rows >= limit:
                    break

            if chunks:
                full_df = pd.concat(chunks, ignore_index=True)
                full_df.to_parquet(out_path, index=False, engine="pyarrow")
                generated_files.append(out_path)
                logger.info(
                    "[SQLConnector] %s -> %s (%d rows)",
                    log_name, out_path, total_rows,
                )
            else:
                # Empty table — write empty parquet
                pd.DataFrame().to_parquet(out_path, index=False, engine="pyarrow")
                generated_files.append(out_path)
                logger.info("[SQLConnector] %s -> %s (empty dataset)", log_name, out_path)

        return generated_files

    @staticmethod
    def _sanitize_output_name(name: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", name).strip("_")
        return safe or "dataset"

    @staticmethod
    def _normalize_read_query(query: str, limit: Optional[int] = None) -> str:
        q = query.strip().rstrip(";")
        if not q:
            raise ValueError("custom_query cannot be empty")

        lowered = q.lower()
        if not (lowered.startswith("select") or lowered.startswith("with")):
            raise ValueError("Only read-only SELECT/CTE queries are supported")

        if ";" in q:
            raise ValueError("Only one SQL statement is allowed in custom_query")

        shorthand_match = re.fullmatch(r"select\s+([a-zA-Z0-9_\"`\.]+)", q, flags=re.IGNORECASE)
        if shorthand_match:
            table_ref = shorthand_match.group(1)
            return f"SELECT * FROM {table_ref}"

        return q
