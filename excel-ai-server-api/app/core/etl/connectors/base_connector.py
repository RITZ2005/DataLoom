"""
Abstract base class for all ETL connectors (SQL, MongoDB, etc.).

Every connector must implement:
  - test_connection()   → bool
  - list_tables()       → list[dict]
  - preview_table()     → list[dict]
  - extract_to_parquet() → list[str]   (paths to generated .parquet files)
"""
from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("HybridSystem")


@dataclass
class ConnectionConfig:
    """Universal connection parameters for any database engine."""
    db_type: str                          # "mysql" | "postgresql" | "mongodb"
    host: str = "localhost"
    port: int = 3306
    username: str = ""
    password: str = ""
    database: str = ""
    # MongoDB-specific
    auth_source: str = "admin"
    # Extra options (SSL, replica sets, etc.)
    options: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.db_type = self.db_type.strip().lower()
        # Normalise synonyms
        if self.db_type in ("postgres", "pg"):
            self.db_type = "postgresql"
        if self.db_type in ("mongo",):
            self.db_type = "mongodb"
        # Default ports per engine
        if self.port == 0:
            self.port = {"mysql": 3306, "postgresql": 5432, "mongodb": 27017}.get(
                self.db_type, 3306
            )


class BaseConnector(abc.ABC):
    """
    Abstract connector.

    Subclasses wrap a single external database and expose a uniform
    extract interface that writes Parquet files to disk.
    """

    def __init__(self, config: ConnectionConfig):
        self.config = config
        self._engine: Any = None          # SQLAlchemy engine / MongoClient

    # ── lifecycle ─────────────────────────────────────────────────────
    @abc.abstractmethod
    def connect(self) -> None:
        """Establish a connection to the external database."""

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Tear down the connection / dispose the engine."""

    # ── discovery ─────────────────────────────────────────────────────
    @abc.abstractmethod
    def test_connection(self) -> bool:
        """Return True if the connection is alive and healthy."""

    @abc.abstractmethod
    def list_tables(self) -> List[Dict[str, Any]]:
        """
        Return a list of available tables / collections.

        Each item: {"name": str, "row_count": int|None, "columns": list|None}
        """

    @abc.abstractmethod
    def preview_table(
        self, table_name: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Return up to *limit* rows from the given table as a list of dicts.
        Used for quick UI preview before extraction.
        """

    # ── extraction ────────────────────────────────────────────────────
    @abc.abstractmethod
    def extract_to_parquet(
        self,
        table_names: List[str],
        output_dir: str,
        chunk_size: int = 100_000,
        limit: Optional[int] = None,
        datasets: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        """
        Stream the requested tables into Parquet files inside *output_dir*.

        Returns a list of absolute paths to the generated .parquet files.
        Large tables are chunked with *chunk_size* rows per batch.
        If limit is provided, only extracts up to *limit* rows (for dry-run).
        datasets optionally supports mixed extraction definitions:
        {"table_name": str} or {"custom_query": str, "output_name": str}.
        """

    # ── context manager ───────────────────────────────────────────────
    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False
