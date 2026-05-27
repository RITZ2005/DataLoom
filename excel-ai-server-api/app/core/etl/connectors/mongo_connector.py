"""
MongoDB Connector — handles MongoDB external databases.

Uses pymongo for connection management and pd.json_normalize for
flattening nested BSON documents into tabular DataFrames.
"""
from __future__ import annotations

import os
import logging
from typing import Any, Dict, List

import pandas as pd

from app.core.etl.connectors.base_connector import BaseConnector, ConnectionConfig

logger = logging.getLogger("HybridSystem")

# Optional import
try:
    from pymongo import MongoClient
    _PYMONGO_AVAILABLE = True
except ImportError:
    MongoClient = None  # type: ignore[assignment,misc]
    _PYMONGO_AVAILABLE = False


class MongoConnector(BaseConnector):
    """
    Connector for MongoDB databases via pymongo.

    Flattens nested documents with pd.json_normalize before writing
    Parquet files to disk.
    """

    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        if not _PYMONGO_AVAILABLE:
            raise ImportError(
                "pymongo is required for MongoDB connectors. "
                "Install it with: pip install pymongo"
            )
        self._client: Any = None
        self._db: Any = None

    # ── lifecycle ─────────────────────────────────────────────────────

    def _build_uri(self) -> str:
        c = self.config
        if c.username and c.password:
            uri = (
                f"mongodb://{c.username}:{c.password}@{c.host}:{c.port}"
                f"/{c.database}?authSource={c.auth_source}"
            )
        else:
            uri = f"mongodb://{c.host}:{c.port}/{c.database}"
        return uri

    def connect(self) -> None:
        uri = self._build_uri()
        self._client = MongoClient(
            uri,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
        )
        self._db = self._client[self.config.database]
        logger.info(
            "[MongoConnector] Connected to mongodb://%s:%s/%s",
            self.config.host, self.config.port, self.config.database,
        )

    def disconnect(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self._db = None
            logger.info("[MongoConnector] Client closed")

    # ── discovery ─────────────────────────────────────────────────────

    def test_connection(self) -> bool:
        try:
            if self._client is None:
                self.connect()
            # Force a round-trip to the server
            self._client.admin.command("ping")
            return True
        except Exception as e:
            logger.error("[MongoConnector] Connection test failed: %s", e)
            return False

    def list_tables(self) -> List[Dict[str, Any]]:
        """List MongoDB collections as 'tables'."""
        if self._db is None:
            self.connect()
        collections = []
        for coll_name in self._db.list_collection_names():
            # Skip system collections
            if coll_name.startswith("system."):
                continue
            row_count = None
            columns = None
            try:
                row_count = self._db[coll_name].estimated_document_count()
                # Sample one document to infer top-level keys
                sample = self._db[coll_name].find_one()
                if sample:
                    columns = [
                        {"name": k, "type": type(v).__name__}
                        for k, v in sample.items()
                        if k != "_id"
                    ]
            except Exception:
                pass
            collections.append({
                "name": coll_name,
                "row_count": row_count,
                "columns": columns,
            })
        return collections

    def preview_table(
        self, table_name: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        if self._db is None:
            self.connect()
        cursor = self._db[table_name].find({}, {"_id": 0}).limit(limit)
        docs = list(cursor)
        if docs:
            # Flatten nested structures
            df = pd.json_normalize(docs, sep="_")
            return df.to_dict(orient="records")
        return []

    # ── extraction ────────────────────────────────────────────────────

    def extract_to_parquet(
        self,
        table_names: List[str],
        output_dir: str,
        chunk_size: int = 100_000,
        limit: int | None = None,
        datasets: List[Dict[str, Any]] | None = None,
    ) -> List[str]:
        if self._db is None:
            self.connect()

        os.makedirs(output_dir, exist_ok=True)
        generated_files: List[str] = []

        if datasets:
            extracted_collections = [d.get("table_name") for d in datasets if d.get("table_name")]
        else:
            extracted_collections = table_names

        for coll_name in extracted_collections:
            out_path = os.path.join(output_dir, f"{coll_name}.parquet")
            logger.info("[MongoConnector] Extracting %s (chunk_size=%d)...", coll_name, chunk_size)

            collection = self._db[coll_name]
            cursor = collection.find({}, {"_id": 0})
            if limit is not None:
                cursor = cursor.limit(limit)

            all_chunks: List[pd.DataFrame] = []
            batch: List[dict] = []
            total_rows = 0

            for doc in cursor:
                batch.append(doc)
                if len(batch) >= chunk_size:
                    chunk_df = pd.json_normalize(batch, sep="_")
                    all_chunks.append(chunk_df)
                    total_rows += len(chunk_df)
                    logger.info(
                        "[MongoConnector]   %s: fetched %d rows so far...",
                        coll_name, total_rows,
                    )
                    batch = []

            # Final partial batch
            if batch:
                chunk_df = pd.json_normalize(batch, sep="_")
                all_chunks.append(chunk_df)
                total_rows += len(chunk_df)

            if all_chunks:
                full_df = pd.concat(all_chunks, ignore_index=True)
                full_df.to_parquet(out_path, index=False, engine="pyarrow")
                generated_files.append(out_path)
                logger.info(
                    "[MongoConnector] %s -> %s (%d rows, %d cols)",
                    coll_name, out_path, total_rows, len(full_df.columns),
                )
            else:
                pd.DataFrame().to_parquet(out_path, index=False, engine="pyarrow")
                generated_files.append(out_path)
                logger.info("[MongoConnector] %s -> %s (empty collection)", coll_name, out_path)

        return generated_files
