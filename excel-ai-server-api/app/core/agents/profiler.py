"""
ProfilerAgent — Auto-generates business-friendly descriptions for tables and columns.

Called after ETL Load phase to populate the Semantic Catalog with:
  1. Table-level descriptions (what this data represents)
  2. Column-level descriptions (what each column means)
  3. Embedding vectors for RAG-to-SQL retrieval

Uses the existing LLM setup from app.core.agent for consistency.
"""
from __future__ import annotations

import json
import os
import uuid
import logging
from typing import Any, Dict, List, Optional

from app.core.database import DatabaseManager
from app.utils.logging import log_full_exception

logger = logging.getLogger("HybridSystem")


class ProfilerAgent:
    """Generates semantic descriptions and embeddings for workspace tables."""

    def __init__(self, db: DatabaseManager, llm=None, embed_model=None):
        self.db = db
        self.llm = llm
        self.embed_model = embed_model

    def profile_table(
        self,
        workspace_id: str,
        schema_name: str,
        table_name: str,
    ) -> Dict[str, Any]:
        """
        Auto-profile a table: fetch sample data, generate descriptions via LLM,
        and store embeddings for RAG retrieval.

        Returns a dict with table_description and column_descriptions.
        """
        # 1. Fetch table metadata + sample data
        table_info = self._fetch_table_info(workspace_id, table_name)
        sample_data = self._fetch_sample_rows(schema_name, table_name, limit=10)

        if not table_info:
            logger.warning("[Profiler] No metadata found for %s.%s", schema_name, table_name)
            return {}

        # 2. Generate descriptions via LLM
        descriptions = self._generate_descriptions(
            table_name=table_name,
            columns=table_info.get("columns", []),
            sample_data=sample_data,
        )

        # 3. Store descriptions back into the catalog
        self._save_descriptions(workspace_id, table_name, descriptions)

        # 4. Generate and store embeddings for RAG
        if self.embed_model:
            self._generate_and_store_embeddings(workspace_id, table_name, descriptions)

        logger.info("[Profiler] ✅ Profiled table %s.%s", schema_name, table_name)
        return descriptions

    def profile_workspace(self, workspace_id: str) -> List[Dict[str, Any]]:
        """Profile all tables in a workspace."""
        results = []

        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT table_name, schema_name
                    FROM etl_system.tables_metadata
                    WHERE workspace_id = %s
                    """,
                    (workspace_id,),
                )
                tables = cur.fetchall()

        for table_name, schema_name in tables:
            try:
                result = self.profile_table(workspace_id, schema_name, table_name)
                results.append({"table_name": table_name, **result})
            except Exception as e:
                log_full_exception(e, f"Profiling failed for {table_name}")
                results.append({"table_name": table_name, "error": str(e)})

        return results

    # ── Internal Helpers ──────────────────────────────────────────────

    def _fetch_table_info(self, workspace_id: str, table_name: str) -> Optional[Dict]:
        """Fetch table + column metadata from etl_system catalog."""
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT metadata_id, row_count, auto_profile, description
                    FROM etl_system.tables_metadata
                    WHERE workspace_id = %s AND table_name = %s
                    """,
                    (workspace_id, table_name),
                )
                row = cur.fetchone()
                if not row:
                    return None

                cur.execute(
                    """
                    SELECT column_name, data_type, sample_values, stats, description
                    FROM etl_system.columns_metadata
                    WHERE workspace_id = %s AND table_name = %s
                    ORDER BY column_name
                    """,
                    (workspace_id, table_name),
                )
                columns = [
                    {
                        "name": c[0],
                        "type": c[1],
                        "samples": c[2],
                        "stats": c[3],
                        "description": c[4],
                    }
                    for c in cur.fetchall()
                ]

        return {
            "metadata_id": row[0],
            "row_count": row[1],
            "auto_profile": row[2],
            "existing_description": row[3],
            "columns": columns,
        }

    def _fetch_sample_rows(self, schema_name: str, table_name: str, limit: int = 10) -> List[Dict]:
        """Fetch sample rows from the actual data table."""
        try:
            with self.db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(f'SELECT * FROM "{schema_name}"."{table_name}" LIMIT %s', (limit,))
                    cols = [desc[0] for desc in cur.description]
                    rows = cur.fetchall()
                    return [dict(zip(cols, row)) for row in rows]
        except Exception as e:
            logger.warning("[Profiler] Failed to fetch sample rows for %s.%s: %s", schema_name, table_name, e)
            return []

    def _generate_descriptions(
        self,
        table_name: str,
        columns: List[Dict],
        sample_data: List[Dict],
    ) -> Dict[str, Any]:
        """Use LLM to generate table + column descriptions."""
        if not self.llm:
            # Fallback: return basic auto-generated descriptions
            return self._generate_basic_descriptions(table_name, columns)

        # Build a compact prompt
        col_info = "\n".join([
            f"  - {c['name']} ({c['type']}): samples={c.get('samples', [])}"
            for c in columns[:30]  # Cap at 30 columns
        ])

        sample_str = ""
        if sample_data:
            sample_str = "\nSample rows (first 5):\n" + json.dumps(sample_data[:5], default=str, indent=1)

        prompt = f"""You are a data catalog expert. Given the following database table, generate:
1. A concise business description of the TABLE (1-2 sentences).
2. A concise business description for EACH COLUMN (1 sentence each).

Table name: {table_name}
Columns:
{col_info}
{sample_str}

Return valid JSON in this format:
{{
  "table_description": "...",
  "column_descriptions": {{
    "column_name": "description",
    ...
  }}
}}

Return ONLY valid JSON. No markdown formatting."""

        try:
            response = self.llm.invoke(prompt)
            content = response.content.strip()
            # Strip markdown code fences if present
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            result = json.loads(content)
            return result
        except Exception as e:
            logger.warning("[Profiler] LLM description generation failed: %s. Using basic fallback.", e)
            return self._generate_basic_descriptions(table_name, columns)

    def _generate_basic_descriptions(
        self, table_name: str, columns: List[Dict]
    ) -> Dict[str, Any]:
        """Fallback: generate simple descriptions without LLM."""
        col_descs = {}
        for c in columns:
            dtype = c.get("type", "unknown")
            stats = c.get("stats") or {}
            unique = stats.get("unique_count", "?")
            col_descs[c["name"]] = f"{dtype} column with {unique} unique values"

        return {
            "table_description": f"Data table '{table_name}' with {len(columns)} columns",
            "column_descriptions": col_descs,
        }

    def _save_descriptions(
        self,
        workspace_id: str,
        table_name: str,
        descriptions: Dict[str, Any],
    ) -> None:
        """Persist generated descriptions into the semantic catalog."""
        table_desc = descriptions.get("table_description", "")
        col_descs = descriptions.get("column_descriptions", {})

        logger.info(
            "[Profiler] Saving descriptions | workspace_id=%s | table=%s | has_table_desc=%s | column_desc_count=%d",
            workspace_id,
            table_name,
            bool(table_desc),
            len(col_descs),
        )

        # Stitch together schema_info
        schema_info_lines = [f"Table: {table_name}"]
        if table_desc:
            schema_info_lines.append(f"Description: {table_desc}")
        if col_descs:
            schema_info_lines.append("Columns:")
            for col_name, desc in col_descs.items():
                schema_info_lines.append(f"- {col_name}: {desc}")
        schema_info = "\n".join(schema_info_lines)

        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                # Update table description and schema_info
                cur.execute(
                    """
                    UPDATE etl_system.tables_metadata
                    SET description = COALESCE(NULLIF(%s, ''), description),
                        schema_info = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE workspace_id = %s AND table_name = %s
                    """,
                    (table_desc, schema_info, workspace_id, table_name),
                )
                table_updates = cur.rowcount

                # Update column descriptions
                col_updates = 0
                for col_name, desc in col_descs.items():
                    cur.execute(
                        """
                        UPDATE etl_system.columns_metadata
                        SET description = %s
                        WHERE workspace_id = %s AND table_name = %s AND column_name = %s
                          AND (description IS NULL OR description = '')
                        """,
                        (desc, workspace_id, table_name, col_name),
                    )
                    col_updates += cur.rowcount
            conn.commit()

        logger.info(
            "[Profiler] Descriptions saved | workspace_id=%s | table=%s | table_updates=%d | column_updates=%d",
            workspace_id,
            table_name,
            table_updates,
            col_updates,
        )

    def _generate_and_store_embeddings(
        self,
        workspace_id: str,
        table_name: str,
        descriptions: Dict[str, Any],
    ) -> None:
        """Generate embeddings for the whole-table schema summary and store in semantic_vectors."""
        table_desc = descriptions.get("table_description", "")
        col_descs = descriptions.get("column_descriptions", {})

        schema_info_lines = [f"Table: {table_name}"]
        if table_desc:
            schema_info_lines.append(f"Description: {table_desc}")
        if col_descs:
            schema_info_lines.append("Columns:")
            for col_name, desc in col_descs.items():
                schema_info_lines.append(f"- {col_name}: {desc}")
        schema_info = "\n".join(schema_info_lines)

        texts_to_embed = [{
            "content_type": "schema",
            "source_id": f"{workspace_id}_{table_name}_schema",
            "text": schema_info,
        }]

        if not texts_to_embed:
            return

        logger.info(
            "[Profiler] Generating schema embeddings | workspace_id=%s | table=%s | chunks=%d",
            workspace_id,
            table_name,
            len(texts_to_embed),
        )

        try:
            # Batch embed
            raw_texts = [t["text"] for t in texts_to_embed]
            embeddings = self.embed_model.embed_documents(raw_texts)

            with self.db.get_connection() as conn:
                with conn.cursor() as cur:
                    # Clear old vectors for this table
                    cur.execute(
                        """
                        DELETE FROM etl_system.semantic_vectors
                        WHERE workspace_id = %s AND source_id LIKE %s
                        """,
                        (workspace_id, f"{workspace_id}_{table_name}%"),
                    )

                    for item, embedding in zip(texts_to_embed, embeddings):
                        vector_id = str(uuid.uuid4())
                        cur.execute(
                            """
                            INSERT INTO etl_system.semantic_vectors
                                (vector_id, workspace_id, content_type, source_id, content_text, embedding, metadata)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                vector_id,
                                workspace_id,
                                item["content_type"],
                                item["source_id"],
                                item["text"],
                                str(embedding),  # pgvector accepts string representation
                                json.dumps({"table_name": table_name}),
                            ),
                        )
                conn.commit()

            logger.info(
                "[Profiler] 🔗 Stored %d embeddings for %s (workspace=%s)",
                len(texts_to_embed), table_name, workspace_id,
            )
        except Exception as e:
            log_full_exception(e, f"Embedding storage failed for {table_name}")
