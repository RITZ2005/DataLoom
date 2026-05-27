"""
WorkspaceSqlAgent â€” RAG-to-SQL pipeline for workspace-scoped chat queries.

Architecture:
  1. Vector Search: embed user query â†’ find relevant tables/columns from semantic_vectors
  2. Context Assembly: build schema + descriptions prompt context
  3. SQL Writer: LLM generates SQL constrained to the workspace schema
  4. SQL Validator: second LLM pass validates SQL for correctness + safety
  5. Execution: run validated SQL against read-only workspace schema
  6. Response: format results for chat display / widget pinning

Security:
  - SQL is executed with search_path restricted to the workspace schema
  - Uses ai_readonly role when available
"""
from __future__ import annotations

import json
import os
import logging
import time
import uuid
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple, AsyncGenerator

import psycopg2
from psycopg2.extras import RealDictCursor

from app.core.database import DatabaseManager
from app.core.schema_utils import get_workspace_schema_name
from app.utils.logging import log_full_exception

logger = logging.getLogger("HybridSystem")

# Maximum rows returned from SQL execution
MAX_RESULT_ROWS = 500
# Maximum columns in the context window
MAX_CONTEXT_COLUMNS = 80

# Regex pattern for numeric columns that should be treated as dimensions (not measures)
_IDENTIFIER_COLUMN_PATTERN = re.compile(
    r'(?i)(^id$|_id$|\byear\b|\bphone\b|\bmobile\b|\bzip\b|\bpin\b|\bcode\b|\blat\b|\blon\b|\blongitude\b|\blatitude\b|\bfax\b|\baadhar\b|\baadhaar\b|\bssn\b|\bpassport\b|\broll.?no\b|\benrollment\b|\bserial\b|\bpincode\b|\bpostal\b)'
)

# Regex pattern for columns that should strictly be treated as measures
_MEASURE_COLUMN_PATTERN = re.compile(
    r'(?i)(\bpercent\b|\bpercentage\b|\bpct\b|\brate\b|\bratio\b|\bgrowth\b|\btotal\b|\bsum\b|\bamount\b|\bvalue\b|\bcount\b)'
)


class WorkspaceSqlAgent:
    """Handles natural-language-to-SQL for workspace-scoped queries."""

    def __init__(
        self,
        db: DatabaseManager,
        workspace_id: str,
        llm=None,
        embed_model=None,
    ):
        self.db = db
        self.workspace_id = workspace_id
        self.schema_name = get_workspace_schema_name(workspace_id)
        self.llm = llm
        self.embed_model = embed_model

    @staticmethod
    def _normalize_text(value: str) -> str:
        """Normalize text for robust phrase matching (spaces/underscores/punctuation tolerant)."""
        return re.sub(r"[^a-z0-9]+", "", (value or "").lower())

    def _metric_matches_question(self, metric_name: str, question: str) -> bool:
        """Return True when metric name likely appears in question (handles spacing and minor typos)."""
        metric_name = (metric_name or "").strip()
        if not metric_name:
            return False

        question_lower = (question or "").lower()
        metric_lower = metric_name.lower()

        # Exact phrase match first
        if metric_lower in question_lower:
            return True

        
        normalized_metric = self._normalize_text(metric_name)
        normalized_question = self._normalize_text(question)
        if normalized_metric and normalized_metric in normalized_question:
            return True

        # Token containment with underscore/space normalization
        metric_terms = set(re.findall(r"[a-z0-9]+", metric_lower.replace("_", " ")))
        question_terms = set(re.findall(r"[a-z0-9]+", question_lower))
        if metric_terms and metric_terms.issubset(question_terms):
            return True

        # Fuzzy token match for minor per-word typos (e.g., ratio vs ration)
        if metric_terms and question_terms:
            all_terms_match = True
            for mt in metric_terms:
                best = max((SequenceMatcher(None, mt, qt).ratio() for qt in question_terms), default=0.0)
                if best < 0.8:
                    all_terms_match = False
                    break
            if all_terms_match:
                return True

        # Minor typo tolerance (e.g., ratio vs ration)
        if normalized_metric and normalized_question:
            return SequenceMatcher(None, normalized_metric, normalized_question).ratio() >= 0.85

        return False

    @staticmethod
    def _is_numeric_pg_type(type_name: str) -> bool:
        from app.core.llm import is_numeric_pg_type
        return is_numeric_pg_type(type_name)

    @staticmethod
    def _is_text_pg_type(type_name: str) -> bool:
        from app.core.llm import is_text_pg_type
        return is_text_pg_type(type_name)

    @staticmethod
    def _identifier_leaf(identifier: str) -> str:
        from app.core.llm import _identifier_leaf
        return _identifier_leaf(identifier)

    def _extract_sql_error_hints(self, error_msg: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Delegate to shared implementation in app.core.llm."""
        from app.core.llm import extract_sql_error_hints
        return extract_sql_error_hints(error_msg, context.get("columns", []))

    def _regenerated_sql_repeats_error(self, sql: str, error_hints: Dict[str, Any]) -> bool:
        """Delegate to shared implementation in app.core.llm."""
        from app.core.llm import regenerated_sql_repeats_error
        return regenerated_sql_repeats_error(sql, error_hints)


    def chat(self, question: str) -> Dict[str, Any]:
        """
        Full chat-to-SQL pipeline:
          1. Retrieve relevant context via vector search
          2. Generate SQL via Writer LLM
          3. Validate SQL via Validator LLM
          4. Execute and return results
        """
        try:
            started_at = time.perf_counter()
            logger.info(
                "[WorkspaceSqlAgent] Chat started | workspace_id=%s | schema=%s | question=%s",
                self.workspace_id,
                self.schema_name,
                question,
            )

            # 1. Retrieve semantic context
            context = self._retrieve_context(question)
            logger.info(
                "[WorkspaceSqlAgent] Context assembled | workspace_id=%s | tables=%d | columns=%d | metrics=%d | synonyms=%d | vector_hits=%d",
                self.workspace_id,
                len(context.get("tables", [])),
                len(context.get("columns", [])),
                len(context.get("metrics", [])),
                len(context.get("synonyms", [])),
                len(context.get("vector_hits", [])),
            )
            if context.get("metrics"):
                logger.info(
                    "[WorkspaceSqlAgent] Context metrics detail | workspace_id=%s | metrics=%s",
                    self.workspace_id,
                    json.dumps(context.get("metrics", []), ensure_ascii=False, default=str),
                )

            # 2. Generate SQL
            sql = self._generate_sql(question, context)

            if not sql:
                logger.warning(
                    "[WorkspaceSqlAgent] SQL generation returned empty | workspace_id=%s | question=%s",
                    self.workspace_id,
                    question,
                )
                return {
                    "status": "error",
                    "message": "Could not generate a valid SQL query for your question.",
                    "question": question,
                }

            logger.info(
                "[WorkspaceSqlAgent] Generated SQL | workspace_id=%s | sql=%s",
                self.workspace_id,
                sql,
            )

            # 3. Validate SQL
            validated_sql, validation_notes = self._validate_sql(sql, context)
            logger.info(
                "[WorkspaceSqlAgent] Validated SQL | workspace_id=%s | notes=%s | sql=%s",
                self.workspace_id,
                validation_notes,
                validated_sql,
            )

            # 4. Execute with auto-retry on error
            results, columns = None, None
            exec_error = None
            for attempt in range(1, 3):  # 2 attempts: initial + 1 retry
                try:
                    results, columns = self._execute_sql(validated_sql)
                    exec_error = None
                    break  # Success, exit retry loop
                except RuntimeError as e:
                    exec_error = str(e)
                    error_hints = self._extract_sql_error_hints(exec_error, context)
                    logger.warning(
                        "[WorkspaceSqlAgent] SQL execution failed on attempt %d | workspace_id=%s | error=%s | summary=%s | recommendation=%s | diagnostics=%s",
                        attempt,
                        self.workspace_id,
                        exec_error,
                        error_hints.get("human_summary"),
                        error_hints.get("recommended_action"),
                        json.dumps(error_hints, ensure_ascii=False),
                    )
                    # If first attempt failed, try to regenerate SQL using error feedback
                    if attempt == 1:
                        logger.info(
                            "[WorkspaceSqlAgent] Attempting SQL recovery | workspace_id=%s | error_feedback=%s",
                            self.workspace_id,
                            exec_error,
                        )
                        regenerated_sql = self._regenerate_sql_from_error(
                            question, validated_sql, exec_error, context, error_hints=error_hints, strict=False
                        )
                        if regenerated_sql and self._regenerated_sql_repeats_error(regenerated_sql, error_hints):
                            logger.warning(
                                "[WorkspaceSqlAgent] Regenerated SQL still repeats failing predicate; retrying regeneration with strict diagnostics | workspace_id=%s",
                                self.workspace_id,
                            )
                            regenerated_sql = self._regenerate_sql_from_error(
                                question, validated_sql, exec_error, context, error_hints=error_hints, strict=True
                            )
                        if regenerated_sql:
                            validated_sql, validation_notes = self._validate_sql(regenerated_sql, context)
                            logger.info(
                                "[WorkspaceSqlAgent] Regenerated SQL from error | workspace_id=%s | sql=%s",
                                self.workspace_id,
                                validated_sql,
                            )
                        else:
                            raise RuntimeError(exec_error)
                    else:
                        raise RuntimeError(exec_error)

            if exec_error:
                raise RuntimeError(exec_error)
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            logger.info(
                "[WorkspaceSqlAgent] Chat completed | workspace_id=%s | rows=%d | columns=%d | duration_ms=%d",
                self.workspace_id,
                len(results),
                len(columns),
                duration_ms,
            )

            return {
                "status": "success",
                "question": question,
                "sql": validated_sql,
                "columns": columns,
                "data": results,
                "row_count": len(results),
                "context_tables": [t.get("table_name") for t in context.get("tables", [])],
                "validation_notes": validation_notes,
            }

        except Exception as e:
            log_full_exception(e, f"WorkspaceSqlAgent.chat failed for: {question}")
            return {
                "status": "error",
                "message": str(e),
                "question": question,
            }

    # â”€â”€ Phase 1: Vector Search (RAG Context Retrieval) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _retrieve_context(self, question: str) -> Dict[str, Any]:
        """Retrieve relevant tables and columns using vector similarity search."""
        context: Dict[str, Any] = {
            "tables": [],
            "columns": [],
            "metrics": [],
            "synonyms": [],
            "foreign_keys": [],
        }

        # Step 1: Check total number of tables
        total_tables = 0
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM etl_system.tables_metadata WHERE workspace_id = %s", (self.workspace_id,))
                total_tables = cur.fetchone()[0]
                
        logger.info("[WorkspaceSqlAgent] Detected %d total tables in workspace '%s'", total_tables, self.workspace_id)

        # Add semantic metrics
        context["metrics"] = self._get_semantic_metrics()

        # Add synonym mappings
        context["synonyms"] = self._get_synonyms()

        # Add foreign key mappings
        context["foreign_keys"] = self._get_foreign_keys()

        relevant_tables = None

        # Step 2: THRESHOLD LOGIC (< 5 tables)
        if total_tables < 5:
            logger.info("[WorkspaceSqlAgent] Table count < 5. Bypassing semantic routing and loading all tables.")

        if total_tables >= 5 and self.embed_model:
            logger.info("[WorkspaceSqlAgent] Table count >= 5. Initiating Semantic Table Routing via Vector Search.")
            try:
                # Step 3: Run Vector Search on 'schema'
                ranked_items = self._vector_search(question, top_k=5)
                context["vector_hits"] = ranked_items
                
                logger.info("[WorkspaceSqlAgent] Raw Vector Search returned %d hits.", len(ranked_items))
                
                relevant_tables_set = set()
                for item in ranked_items:
                    sim_score = item.get("similarity", 0.0)
                    source_id = item.get("source_id", "unknown")
                    logger.info("  -> Vector Hit | source: %s | similarity: %.4f", source_id, sim_score)
                    
                    metadata = item.get("metadata", {})
                    if isinstance(metadata, str):
                        try:
                            metadata = json.loads(metadata)
                        except:
                            pass
                    tname = metadata.get("table_name")
                    if tname:
                        relevant_tables_set.add(tname)
                
                logger.info("[WorkspaceSqlAgent] Vector search hits for relevant tables: %s", list(relevant_tables_set))
                
                # Step 4: METRIC DEPENDENCY LOGIC
                matched_metrics: List[str] = []
                for m in context["metrics"]:
                    metric_name = m.get("name", "")
                    if self._metric_matches_question(metric_name, question):
                        matched_metrics.append(metric_name)
                        related_tables = m.get("related_tables")
                        if related_tables:
                            if isinstance(related_tables, str):
                                try:
                                    related_tables = json.loads(related_tables)
                                except:
                                    # Fallback if it's just a comma-separated string
                                    related_tables = [t.strip() for t in related_tables.split(",")]
                            if isinstance(related_tables, list):
                                logger.info("[WorkspaceSqlAgent] Detected metric keyword '%s'. Injecting dependent tables: %s", metric_name, related_tables)
                                for rt in related_tables:
                                    relevant_tables_set.add(rt)

                if matched_metrics:
                    logger.info(
                        "[WorkspaceSqlAgent] Matched metrics from question | workspace_id=%s | metrics=%s",
                        self.workspace_id,
                        matched_metrics,
                    )
                
                if relevant_tables_set:
                    relevant_tables = list(relevant_tables_set)
                    logger.info("[WorkspaceSqlAgent] Final routed context configured with tables: %s", relevant_tables)
                else:
                    logger.warning("[WorkspaceSqlAgent] Vector search yielded 0 valid tables. Falling back to loading ALL tables into context.")
                    
            except Exception as e:
                logger.warning("[WorkspaceSqlAgent] Vector search failed: %s", e)

        # Now include schema context using relevant_tables filter
        context["tables"] = self._get_all_tables_metadata(relevant_tables)
        context["columns"] = self._get_all_columns_metadata(relevant_tables)

        return context

    def _get_all_tables_metadata(self, relevant_tables: Optional[List[str]] = None) -> List[Dict]:
        """Get all table metadata for this workspace."""
        query = """
            SELECT table_name, description, row_count
            FROM etl_system.tables_metadata
            WHERE workspace_id = %s
        """
        params = [self.workspace_id]
        if relevant_tables is not None:
            query += " AND table_name = ANY(%s)"
            params.append(relevant_tables)
        query += " ORDER BY table_name"
        
        with self.db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, tuple(params))
                return [dict(r) for r in cur.fetchall()]

    def _get_all_columns_metadata(self, relevant_tables: Optional[List[str]] = None) -> List[Dict]:
        """Get all column metadata for this workspace (capped)."""
        query = """
            SELECT table_name, column_name, data_type, description, sample_values, stats
            FROM etl_system.columns_metadata
            WHERE workspace_id = %s
        """
        params = [self.workspace_id]
        if relevant_tables is not None:
            query += " AND table_name = ANY(%s)"
            params.append(relevant_tables)
        query += " ORDER BY table_name, column_name LIMIT %s"
        params.append(MAX_CONTEXT_COLUMNS)
        
        with self.db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, tuple(params))
                return [dict(r) for r in cur.fetchall()]

    def _get_semantic_metrics(self) -> List[Dict]:
        """Get user-defined metrics for SQL context."""
        with self.db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT name, formula, description, related_tables FROM etl_system.semantic_metrics WHERE workspace_id = %s",
                    (self.workspace_id,),
                )
                return [dict(r) for r in cur.fetchall()]

    def _get_foreign_keys(self) -> List[Dict]:
        """Extract explicit foreign key relationships from PostgreSQL schema for the workspace."""
        query = """
            SELECT
                tc.table_name, 
                kcu.column_name, 
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name 
            FROM 
                information_schema.table_constraints AS tc 
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                  AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage AS ccu
                  ON ccu.constraint_name = tc.constraint_name
                  AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
            AND tc.table_schema = %s;
        """
        with self.db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, (self.schema_name,))
                return [dict(r) for r in cur.fetchall()]

    def _get_synonyms(self) -> List[Dict]:
        """Get synonym mappings for SQL context."""
        with self.db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT keyword, mapped_to, mapped_type FROM etl_system.semantic_synonyms WHERE workspace_id = %s",
                    (self.workspace_id,),
                )
                return [dict(r) for r in cur.fetchall()]

    def _vector_search(self, query: str, top_k: int = 10) -> List[Dict]:
        """Perform vector similarity search against semantic_vectors."""
        query_embedding = self.embed_model.embed_query(query)

        with self.db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT content_type, source_id, content_text, metadata,
                           1 - (embedding <=> %s::vector) as similarity
                    FROM etl_system.semantic_vectors
                    WHERE workspace_id = %s AND content_type = 'schema'
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (str(query_embedding), self.workspace_id, str(query_embedding), top_k),
                )
                return [dict(r) for r in cur.fetchall()]

    # â”€â”€ Phase 2: SQL Writer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _regenerate_sql_from_error(
        self,
        question: str,
        failed_sql: str,
        error_msg: str,
        context: Dict,
        error_hints: Optional[Dict[str, Any]] = None,
        strict: bool = False,
    ) -> Optional[str]:
        """Regenerate SQL using the execution error as feedback with detailed schema analysis."""
        if not self.llm:
            return None

        schema_desc = self._build_schema_description(context)
        
        # Build explicit table-column-to-table mapping for debugging
        tables = context.get("tables", [])
        columns = context.get("columns", [])
        metrics = context.get("metrics", [])
        
        # Create tableâ†’columns index
        table_col_index = {}
        for c in columns:
            tname = c["table_name"]
            if tname not in table_col_index:
                table_col_index[tname] = []
            table_col_index[tname].append(c["column_name"])
        
        table_info = "=== EXPLICIT TABLE-COLUMN MAPPING ===\n"
        for tname in sorted(table_col_index.keys()):
            table_info += f'  "{tname}": {", ".join(table_col_index[tname])}\n'
        
        metric_info = ""
        if metrics:
            metric_info = "\n=== METRICS & THEIR TABLES ===\n"
            for m in metrics:
                related_tables = m.get("related_tables")
                if isinstance(related_tables, str) and related_tables:
                    try:
                        related_tables = json.loads(related_tables)
                    except:
                        pass
                related_str = ", ".join(str(t) for t in related_tables) if related_tables else "unknown"
                metric_info += f'  - {m["name"]}: formula=({m["formula"]}) uses tables: {related_str}\n'

        hints = error_hints or {}
        diagnostics_info = ""
        if hints:
            diagnostics_info = (
                "\n=== EXECUTION ERROR DIAGNOSTICS ===\n"
                f"  expected_type: {hints.get('expected_type')}\n"
                f"  bad_value: {hints.get('bad_value')}\n"
                f"  failing_expression: {hints.get('line_expr')}\n"
                f"  comparison_column: {hints.get('comparison_column')}\n"
                f"  is_type_mismatch: {hints.get('is_type_mismatch')}\n"
                f"  natural_language_summary: {hints.get('human_summary')}\n"
                f"  recommended_action: {hints.get('recommended_action')}\n"
            )
            if hints.get("candidate_name_columns"):
                diagnostics_info += (
                    "  suggested_name_columns: "
                    + ", ".join(hints.get("candidate_name_columns", [])[:20])
                    + "\n"
                )
            elif hints.get("candidate_text_columns"):
                diagnostics_info += (
                    "  suggested_text_columns: "
                    + ", ".join(hints.get("candidate_text_columns", [])[:20])
                    + "\n"
                )

        strict_instruction = ""
        if strict:
            strict_instruction = (
                "\nIMPORTANT: Your previous recovery repeated the same failure pattern. "
                "Do NOT reuse the same failing comparison. If a value is a person name and the previous column is numeric, "
                "switch the filter to an appropriate text/name column from diagnostics."
            )
        
        error_feedback_prompt = f"""You are an expert SQL debugger. The following SQL query failed. Fix it by:
1. Analyzing which table each column belongs to (from the mapping below).
2. Ensuring every table alias correctly references a table.
3. Ensuring every column is qualified with the right table alias.
4. If a metric is used, expanding it to its formula using the correct table aliases.

Failed SQL:
{failed_sql}

Error Message:
{error_msg}

CRITICAL: Every column must belong to a table. Use the explicit mapping below to find the correct table for each column. Then ensure the table alias in the FROM/JOIN clause matches.

{table_info}{metric_info}{diagnostics_info}

Schema:
{schema_desc}

User Question: {question}

REGENERATION STEPS:
1. Identify which columns are missing (from the error).
2. Find which table contains those columns (using the mapping above).
3. Ensure that table is in the FROM or JOIN clause.
4. Ensure the table alias used for that column matches the table alias in FROM/JOIN.
5. Correct all table aliases if needed.
6. ALWAYS use ILIKE instead of '=' for string comparisons to ensure case-insensitivity.
7. If diagnostics indicate type mismatch (e.g., bigint vs person-name string), replace the failing numeric-column comparison with a suitable text/name column comparison.
8. Never repeat the exact failing predicate from the error message.
9. Return ONLY the corrected SQL. No explanation.
{strict_instruction}

Corrected SQL:"""

        try:
            from app.core.llm import invoke_llm_with_retry
            sql = invoke_llm_with_retry(self.llm, error_feedback_prompt, context_name="SQL Regeneration")
            if sql.startswith("```"):
                sql = sql.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            logger.info(
                "[WorkspaceSqlAgent] SQL regeneration prompt sent | workspace_id=%s",
                self.workspace_id,
            )
            return sql if sql else None
        except Exception as e:
            logger.error("[WorkspaceSqlAgent] SQL regeneration from error failed: %s", e)
            return None

    def _generate_sql(self, question: str, context: Dict) -> Optional[str]:
        """Use LLM to generate SQL from question + context."""
        if not self.llm:
            return None

        # Build schema description
        schema_desc = self._build_schema_description(context)

        prompt = f"""You are an expert PostgreSQL SQL generator.

    Generate one correct, executable SELECT query for the user question using ONLY the provided context.

Follow ALL rules below carefully and strictly.

---
1. Use ONLY tables and columns from the provided DATABASE SCHEMA.
2. Do NOT use schema prefixes. Use only table names in double quotes ("table_name").
3. Return ONLY the SQL query. No explanation, no markdown, no comments.
4. Only SELECT queries are allowed. Never use INSERT, UPDATE, DELETE, DROP, ALTER, etc.
5. Limit results to {MAX_RESULT_ROWS} rows.
6. Do NOT invent tables or columns. Use only what exists in the schema.
7. IMPORTANT: If a CUSTOM METRIC is referenced, use its exact formula in SQL query .(do not replace with raw columns).
8. If a synonym is used, map it using the SYNONYMS section before generating SQL.
9. Use ONLY the relevant columns provided (RAG context). Do not assume unrelated schema.
10. Identify required tables based on selected columns (column â†’ table mapping).
11. If multiple tables are needed, use JOINs (never UNION for relational queries).
12. Always map columns to the correct table. Do not confuse same column names across tables.
13. Use correct join conditions based on relationships (e.g., user_id â†’ id).
14. Apply correct aggregations (SUM, COUNT, AVG, etc.) when needed.
16. Apply filters and time conditions correctly (e.g., last month using DATE functions).
17. Avoid unnecessary tables or joins. Use only what is required.
18. ALWAYS use ILIKE instead of '=' for string comparisons to ensure case-insensitivity (e.g. column ILIKE 'value').
19. NEVER aggregate (SUM, AVG) columns that represent identifiers, years, phone numbers, ZIP codes, serial numbers, or other contextual numeric data. Use them only in GROUP BY, WHERE, or ORDER BY.
Ensure the final SQL is valid, executable, and logically correct.

{schema_desc}

User question: {question}

SQL:"""

        if os.getenv("WORKSPACE_SQL_LOG_PROMPT", "true").lower() in {"1", "true", "yes"}:
            logger.info(
                "[WorkspaceSqlAgent] SQL prompt snapshot | workspace_id=%s | prompt=%s",
                self.workspace_id,
                prompt,
            )

        try:
            from app.core.llm import invoke_llm_with_retry
            sql = invoke_llm_with_retry(self.llm, prompt, context_name="SQL Generation")

            # Strip markdown code fences
            if sql.startswith("```"):
                sql = sql.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            return sql if sql else None
        except Exception as e:
            logger.error("[WorkspaceSqlAgent] SQL generation failed: %s", e)
            return None

    def _build_schema_description(self, context: Dict) -> str:
        """Build compact schema context for SQL generation."""
        parts = []

        # Compact table-column map only (no samples/descriptions to reduce prompt noise)
        parts.append("=== TABLE-COLUMN MAP ===")
        tables = context.get("tables", [])
        columns = context.get("columns", [])

        # Group columns by table
        cols_by_table: Dict[str, List[Dict]] = {}
        for c in columns:
            t = c["table_name"]
            if t not in cols_by_table:
                cols_by_table[t] = []
            cols_by_table[t].append(c)

        for table in tables:
            tname = table["table_name"]
            col_names = [f'"{col["column_name"]}"' for col in cols_by_table.get(tname, [])]
            parts.append(f'  - "{tname}": {", ".join(col_names)}')

        # Metrics
        metrics = context.get("metrics", [])
        if metrics:
            parts.append("\n=== CUSTOM METRICS ===")
            for m in metrics:
                related_tables = m.get("related_tables")
                related_tables_str = ""
                if isinstance(related_tables, list) and related_tables:
                    related_tables_str = f" | related_tables: {', '.join(str(t) for t in related_tables)}"
                elif isinstance(related_tables, str) and related_tables.strip():
                    related_tables_str = f" | related_tables: {related_tables}"
                parts.append(
                    f"  - metric: {m['name']} | formula: {m['formula']}{related_tables_str}"
                )

        # Synonyms
        synonyms = context.get("synonyms", [])
        if synonyms:
            parts.append("\n=== SYNONYMS ===")
            for s in synonyms:
                parts.append(f"  '{s['keyword']}' â†’ {s['mapped_to']} ({s['mapped_type']})")

        # Foreign Keys
        foreign_keys = context.get("foreign_keys", [])
        if foreign_keys:
            parts.append("\n=== FOREIGN KEY RELATIONSHIPS ===")
            for fk in foreign_keys:
                parts.append(f"  {fk['table_name']}.{fk['column_name']} -> {fk['foreign_table_name']}.{fk['foreign_column_name']}")

        return "\n".join(parts)

    # â”€â”€ Phase 3: SQL Validator â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _validate_sql(self, sql: str, context: Dict) -> Tuple[str, str]:
        """Validate SQL for safety and correctness. Returns (validated_sql, notes)."""
        # Basic safety checks (always enforced)
        sql_upper = sql.upper().strip()

        # Block any non-SELECT statement
        dangerous_keywords = ["DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", "TRUNCATE", "GRANT", "REVOKE"]
        for kw in dangerous_keywords:
            if kw in sql_upper.split():
                raise ValueError(f"SQL query contains forbidden keyword: {kw}")

        if not sql_upper.startswith("SELECT") and not sql_upper.startswith("WITH"):
            raise ValueError("Only SELECT/WITH queries are allowed")

        # LLM-based validation (if LLM available)
        if self.llm:
            try:
                schema_tables = [f'"{t["table_name"]}"' for t in context.get('tables', [])]
                validation_prompt = f"""You are a SQL validator. Check this PostgreSQL query for:
1. Correct table/column references (only tables from the schema should be used)
2. Proper SQL syntax
3. No dangerous operations (only SELECT allowed)
4. Do NOT use any schema prefixes for table names. Just use the table name in double quotes.

IMPORTANT: Do NOT add any schema prefix to table names.

If the query is correct, return it exactly as-is.
If it has issues, fix them and return the corrected query.

Return ONLY the SQL query, nothing else.

Available tables: {schema_tables}

Query to validate:
{sql}

Validated SQL:"""
                from app.core.llm import invoke_llm_with_retry
                validated = invoke_llm_with_retry(self.llm, validation_prompt, context_name="SQL Validation")
                if validated.startswith("```"):
                    validated = validated.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                if validated:
                    return validated, "LLM-validated"
            except Exception as e:
                logger.warning("[WorkspaceSqlAgent] Validation LLM failed: %s", e)

        return sql, "basic-validated"

    # â”€â”€ Phase 4: SQL Execution â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def apply_filters_to_sql(self, sql: str, filters: Dict[str, Any]) -> str:
        """
        Safely injects global filters into an existing SQL query using subquery wrapping.
        """
        if not filters:
            return sql
            
        filter_clauses = []
        for col, val in filters.items():
            if val is None or val == "__all__":
                continue
            # Basic sanitization: escape single quotes for string values
            if isinstance(val, str):
                safe_val = val.replace("'", "''")
                filter_clauses.append(f'"{col}" = \'{safe_val}\'')
            else:
                filter_clauses.append(f'"{col}" = {val}')
                
        if not filter_clauses:
            return sql
            
        where_stmt = " AND ".join(filter_clauses)
        
        # Remove trailing semicolon if present
        sql = sql.strip().rstrip(';')
        
        # Wrap in subquery to ensure filters apply to result columns regardless of original complexity
        return f"SELECT * FROM ({sql}) AS filtered_base WHERE {where_stmt}"

    def _execute_sql(self, sql: str) -> Tuple[List[Dict], List[str]]:
        """Execute SQL against the workspace schema with search_path isolation."""
        readonly_user = os.getenv("ETL_READONLY_USER")
        readonly_pass = os.getenv("ETL_READONLY_PASSWORD")
        pg_host = os.getenv("PG_HOST", "localhost")
        pg_port = os.getenv("PG_PORT", "5432")
        pg_database = os.getenv("PG_DATABASE", "hybrid")
        db_url = os.getenv("DATABASE_URL", "")

        # Try to use read-only connection if configured
        conn = None
        use_pool = True

        if readonly_user and readonly_pass:
            try:
                # Prefer explicit PG_* settings (main data DB). Fall back to DATABASE_URL parsing.
                import urllib.parse

                if pg_host and pg_port and pg_database:
                    ro_url = (
                        f"postgresql://{readonly_user}:{urllib.parse.quote(readonly_pass)}"
                        f"@{pg_host}:{pg_port}/{pg_database}"
                    )
                elif db_url:
                    parsed = urllib.parse.urlparse(db_url)
                    ro_url = parsed._replace(
                        netloc=f"{readonly_user}:{urllib.parse.quote(readonly_pass)}@{parsed.hostname}:{parsed.port or 5432}"
                    ).geturl()
                else:
                    ro_url = ""

                if not ro_url:
                    raise RuntimeError("Could not construct read-only DB URL")

                conn = psycopg2.connect(ro_url)
                use_pool = False
                logger.debug("[WorkspaceSqlAgent] Using read-only connection")
            except Exception as e:
                logger.warning("[WorkspaceSqlAgent] Read-only connection failed, using pool: %s", e)
                conn = None

        try:
            if use_pool or conn is None:
                cm = self.db.get_connection()
                conn = cm.__enter__()

            conn.autocommit = True
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Restrict search_path to workspace schema only
                cur.execute(f'SET search_path TO "{self.schema_name}", public;')

                # Execute with timeout
                cur.execute("SET statement_timeout = '30s';")
                logger.info(
                    "[WorkspaceSqlAgent] Executing SQL | workspace_id=%s | schema=%s | sql=%s",
                    self.workspace_id,
                    self.schema_name,
                    sql,
                )
                cur.execute(sql)

                columns = [desc[0] for desc in cur.description] if cur.description else []
                rows = cur.fetchmany(MAX_RESULT_ROWS)
                results = [dict(r) for r in rows]

            return results, columns

        except Exception as e:
            raise RuntimeError(f"SQL execution failed: {str(e)}")
        finally:
            if conn and not use_pool:
                conn.close()
            elif conn and use_pool:
                try:
                    cm.__exit__(None, None, None)
                except Exception:
                    pass

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # DASHBOARD AUTO-GENERATION (SQL-driven)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def _format_number(self, val: float, format_hint: str = "number") -> str:
        """Format a numeric value for dashboard display."""
        if format_hint == "currency":
            if abs(val) >= 1e7:
                return f"â‚¹{val:,.0f}"
            return f"â‚¹{val:,.2f}"
        if format_hint == "percentage":
            return f"{val:.1f}%"
        if val == int(val) and abs(val) < 1e12:
            return f"{int(val):,}"
        if abs(val) >= 1e6:
            return f"{val:,.0f}"
        return f"{val:,.1f}"

    def _infer_format_hint(self, col_name: str) -> str:
        """Infer format hint from column name."""
        lower = (col_name or "").lower()
        if any(kw in lower for kw in ("price", "cost", "revenue", "salary", "amount", "fee", "income", "expense", "total", "budget")):
            return "currency"
        if any(kw in lower for kw in ("rate", "ratio", "percent", "pct", "growth")):
            return "percentage"
        return "number"

    def _get_workspace_metadata(self) -> Dict[str, Any]:
        """Collect full workspace metadata for dashboard generation."""
        tables = self._get_all_tables_metadata()
        columns = self._get_all_columns_metadata()
        metrics = self._get_semantic_metrics()
        foreign_keys = self._get_foreign_keys()

        # Group columns by table
        cols_by_table: Dict[str, List[Dict]] = {}
        for c in columns:
            t = c["table_name"]
            if t not in cols_by_table:
                cols_by_table[t] = []
            cols_by_table[t].append(c)

        # Classify columns
        numeric_cols: List[Dict] = []
        categorical_cols: List[Dict] = []
        date_cols: List[Dict] = []

        for c in columns:
            dtype = (c.get("data_type") or "").lower()
            cname = c["column_name"]
            tname = c["table_name"]
            stats = c.get("stats") or {}
            if isinstance(stats, str):
                try:
                    stats = json.loads(stats)
                except Exception:
                    stats = {}

            entry = {**c, "stats": stats}

            if self._is_numeric_pg_type(dtype):
                lower_name = cname.lower()
                
                # 1. Explicit measure keywords (prioritize as measures even if identifier-like)
                if _MEASURE_COLUMN_PATTERN.search(lower_name):
                    numeric_cols.append(entry)
                    continue

                # 2. ID columns with low cardinality are useful as dimensions
                # (e.g. department_id with 10 departments is a valid grouping column)
                if lower_name.endswith("_id") or lower_name == "id":
                    distinct = stats.get("distinct_count", stats.get("nunique", 0))
                    if isinstance(distinct, (int, float)) and 2 <= distinct <= 100:
                        # Low-cardinality numeric ID → treat as dimension
                        categorical_cols.append(entry)
                    # Otherwise skip (high-cardinality IDs like row PKs are not useful)
                    continue
                # Identifier-like numeric columns (years, phones, zips, etc.)
                # should be treated as dimensions, not measures
                if _IDENTIFIER_COLUMN_PATTERN.search(lower_name):
                    categorical_cols.append(entry)
                    continue

                numeric_cols.append(entry)
            elif any(kw in dtype for kw in ("date", "time", "timestamp")):
                date_cols.append(entry)
            elif self._is_text_pg_type(dtype):
                # Expose all text columns to the Chart Builder UI.
                # Cardinality filtering is done at the UI level.
                categorical_cols.append(entry)

        return {
            "tables": tables,
            "columns": columns,
            "cols_by_table": cols_by_table,
            "numeric_cols": numeric_cols,
            "categorical_cols": categorical_cols,
            "date_cols": date_cols,
            "metrics": metrics,
            "foreign_keys": foreign_keys,
        }

    def update_incremental_dashboard(self, list_of_new_tables: List[str], user_hints: str = "") -> Dict[str, Any]:
        """
        Triggered by the ETL pipeline when new tables are uploaded.
        Generates delta SQL widgets using WorkspaceIncrementalBuilder and persists them.
        """
        logger.info(
            "[WorkspaceSqlAgent] Triggering incremental dashboard update | workspace_id=%s | new_tables=%s",
            self.workspace_id, list_of_new_tables
        )
        
        # 1. Fetch current DB State
        meta = self._get_workspace_metadata()
        
        # 2. Fetch existing widgets
        existing_widgets = []
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT widget_id as id, title, widget_type as type, chart_type as \"chartType\", config, sql_query FROM etl_system.dashboard_widgets WHERE workspace_id = %s",
                    (self.workspace_id,)
                )
                columns = [desc[0] for desc in cur.description]
                for r in cur.fetchall():
                    existing_widgets.append(dict(zip(columns, r)))
        
        # If no existing widgets exist, the dashboard hasn't been initialized.
        # Run the full builder to generate everything for the first time.
        if not existing_widgets:
            logger.info("[WorkspaceSqlAgent] Dashboard empty. Running FULL dashboard generation for %s", list_of_new_tables)
            return self.generate_workspace_dashboard()
        
        # 3. Call the Builder
        from app.core.dashboard.workspace_builder import WorkspaceIncrementalBuilder
        builder = WorkspaceIncrementalBuilder(
            db=self.db,
            workspace_id=self.workspace_id,
            llm=self.llm,
        )
        
        result = builder.build_incremental_dashboard(
            list_of_new_tables=list_of_new_tables,
            full_database_schema=meta,
            semantic_layer=meta.get("metrics", []),
            existing_widgets=existing_widgets,
            user_hints=user_hints
        )
        
        new_widgets = result.get("new_widgets", [])
        remove_widgets = result.get("remove_widgets", [])

        # Even partial success (Pandas-only) should persist what we have
        if not new_widgets and not remove_widgets:
            logger.warning("[WorkspaceSqlAgent] Incremental update produced no widgets")
            return result
        
        # 4. State Persistence (Delete obsolete, Insert new)
        try:
            with self.db.get_connection() as conn:
                with conn.cursor() as cur:
                    # Ensure dashboard parent row exists before inserting widgets
                    dashboard_id = f"dash-{self.workspace_id}"
                    cur.execute(
                        """
                        INSERT INTO etl_system.workspace_dashboards (dashboard_id, workspace_id, name)
                        VALUES (%s, %s, 'Auto Dashboard')
                        ON CONFLICT (dashboard_id) DO NOTHING
                        """,
                        (dashboard_id, self.workspace_id)
                    )

                    # Remove is_newly_added from all existing widgets for this workspace
                    cur.execute(
                        "UPDATE etl_system.dashboard_widgets SET config = config::jsonb - 'is_newly_added' WHERE workspace_id = %s",
                        (self.workspace_id,)
                    )

                    if remove_widgets:
                        cur.execute(
                            "DELETE FROM etl_system.dashboard_widgets WHERE workspace_id = %s AND widget_id = ANY(%s)",
                            (self.workspace_id, remove_widgets)
                        )
                        
                    for w in new_widgets:
                        # Set grid layout directly on widget (no nested config object!)
                        w.setdefault("gridW", 6)
                        w.setdefault("gridH", 3)
                        cur.execute(
                            """
                            INSERT INTO etl_system.dashboard_widgets 
                            (widget_id, dashboard_id, workspace_id, title, widget_type, chart_type, config, sql_query)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (widget_id) DO UPDATE SET
                                title = EXCLUDED.title,
                                widget_type = EXCLUDED.widget_type,
                                chart_type = EXCLUDED.chart_type,
                                config = EXCLUDED.config,
                                sql_query = EXCLUDED.sql_query
                            """,
                            (
                                w["id"], dashboard_id, self.workspace_id, w.get("title", ""), w.get("type", "chart"),
                                w.get("chartType", "bar"), json.dumps(w, default=str), w.get("sql_query", "")
                            )
                        )
                conn.commit()
        except Exception as persist_err:
            logger.warning("[WorkspaceSqlAgent] Widget persistence failed: %s", persist_err)
            
        logger.info("[WorkspaceSqlAgent] Incremental update saved to DB | new=%d | removed=%d", len(new_widgets), len(remove_widgets))
        return result

    def generate_workspace_dashboard(self) -> Dict[str, Any]:
        """
        Auto-generate a full dashboard using per-table fingerprinting.
        
        Delegates to WorkspaceDashboardBuilder which:
        1. Samples each table into a pandas DataFrame
        2. Runs the proven DashboardMixin (same as Excel file dashboards)
        3. Uses LLM to select best widgets across tables + create cross-table insights
        
        Falls back to SQL-based generation if the builder fails.
        """
        logger.info(
            "[WorkspaceSqlAgent] Generating workspace dashboard | workspace_id=%s",
            self.workspace_id,
        )

        # â”€â”€ Primary: Per-table fingerprinting via WorkspaceDashboardBuilder â”€â”€
        try:
            from app.core.dashboard.workspace_builder import WorkspaceDashboardBuilder

            builder = WorkspaceDashboardBuilder(
                db=self.db,
                workspace_id=self.workspace_id,
                llm=self.llm,
            )
            result = builder.generate()

            if result.get("status") == "success" and result.get("widgets"):
                logger.info(
                    "[WorkspaceSqlAgent] Dashboard via builder: %d widgets",
                    len(result["widgets"]),
                )
                return result

            logger.warning("[WorkspaceSqlAgent] Builder returned no widgets, falling back to SQL-based")
        except Exception as e:
            logger.warning("[WorkspaceSqlAgent] Builder failed: %s â€” falling back to SQL-based", e)

        # â”€â”€ Fallback: SQL-based generation (original approach) â”€â”€
        return self._generate_dashboard_sql_fallback()

    def _generate_dashboard_sql_fallback(self) -> Dict[str, Any]:
        """Original SQL-based dashboard generation (LLM proposes SQL queries)."""
        meta = self._get_workspace_metadata()
        tables = meta["tables"]
        if not tables:
            return {"status": "success", "widgets": [], "fingerprint": {}}

        total_tables = len(tables)
        total_rows = sum(t.get("row_count", 0) or 0 for t in tables)
        total_cols = len(meta["columns"])

        # â”€â”€ Build schema summary for LLM â”€â”€
        schema_lines: List[str] = []
        for t in tables:
            tname = t["table_name"]
            row_count = t.get("row_count", 0) or 0
            desc = t.get("description") or ""
            cols = meta["cols_by_table"].get(tname, [])
            col_strs = []
            for c in cols:
                cn = c["column_name"]
                dt = c.get("data_type", "text")
                cd = c.get("description") or ""
                stats = c.get("stats") or {}
                if isinstance(stats, str):
                    try: stats = json.loads(stats)
                    except: stats = {}
                extra = ""
                if stats.get("distinct_count"):
                    extra = f" (distinct={stats['distinct_count']})"
                col_strs.append(f'    "{cn}" {dt}{extra}{" â€” " + cd if cd else ""}')
            schema_lines.append(
                f'TABLE "{tname}" ({row_count:,} rows){" â€” " + desc if desc else ""}\n'
                + "\n".join(col_strs)
            )
        schema_text = "\n\n".join(schema_lines)

        # â”€â”€ LLM-driven widget planning â”€â”€
        widgets: List[Dict] = []
        llm_widgets_raw: List[Dict] = []

        if self.llm:
            planning_prompt = f"""You are a BI dashboard designer. Analyze this PostgreSQL database schema and generate a dashboard widget plan.

SCHEMA:
{schema_text}

Generate a JSON array of widget specifications. Analyze the data schema thoroughly and generate the MAXIMUM number of highly insightful widgets possible. Do not limit yourself; create as many meaningful widgets as the data supports. Each widget must have:
- "type": one of "kpi", "chart", "list", "insight"
- "title": short descriptive title
- "sql": a valid PostgreSQL SELECT query (use double-quoted identifiers, NO schema prefix)
- "chart_type": for charts only â€” "bar", "line", "pie", "donut", or "area"
- "icon": a lucide icon name like "trending-up", "dollar-sign", "users", "activity", "hash"
- "description": one sentence describing the widget (required for charts and insights)

RULES:
1. Skip internal/system columns (id, created_at, updated_at, is_processed, uuid, etc.)
2. Focus on BUSINESS-meaningful columns (revenue, count, name, category, status, etc.)
3. For KPIs: use aggregate queries (SUM, AVG, COUNT) on meaningful numeric columns. Include a "subtitle" field.
4. For charts: GROUP BY a categorical column, aggregate a numeric column. Always include "description".
5. For lists: show top N items ranked by a measure (LIMIT 10)
6. For insights: write an analytical "text" field with a data-driven finding. The SQL should support the finding.
7. Use only tables and columns from the schema above
8. Return ONLY the JSON array, no markdown fences
9. Make as many widgets as you can. Include a comprehensive mix of KPIs, charts (different types), lists, and insights.

Return ONLY the JSON array."""

            try:
                from app.core.llm import invoke_llm_with_retry
                raw = invoke_llm_with_retry(
                    self.llm, 
                    planning_prompt, 
                    context_name="Workspace Dashboard Planning Fallback"
                )
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                llm_widgets_raw = json.loads(raw)
                if not isinstance(llm_widgets_raw, list):
                    llm_widgets_raw = []
                logger.info("[WorkspaceSqlAgent] LLM proposed %d widgets (fallback)", len(llm_widgets_raw))
            except Exception as e:
                logger.warning("[WorkspaceSqlAgent] LLM widget planning failed: %s", e)
                llm_widgets_raw = []

        # â”€â”€ Build widgets from LLM plan â”€â”€
        widget_idx = 0

        # Always start with a summary widget
        largest_table = max(tables, key=lambda t: t.get("row_count", 0) or 0)
        summary_text = (
            f"This workspace contains {total_tables} table{'s' if total_tables != 1 else ''} "
            f"with {total_rows:,} records across {total_cols} columns. "
            f"Largest table: \"{largest_table['table_name']}\" ({(largest_table.get("row_count", 0) or 0):,} rows)."
        )
        widget_idx += 1
        widgets.append({
            "id": f"ws-widget-{widget_idx}", "type": "summary",
            "title": "Workspace Overview", "text": summary_text,
            "icon": "database", "gridW": 12, "gridH": 2,
        })

        # Static KPIs
        widget_idx += 1
        widgets.append({
            "id": f"ws-widget-{widget_idx}", "type": "kpi",
            "title": "Total Tables", "value": str(total_tables),
            "subtitle": "Tables in workspace", "trend": "neutral",
            "icon": "layers", "gridW": 3, "gridH": 2,
        })
        widget_idx += 1
        widgets.append({
            "id": f"ws-widget-{widget_idx}", "type": "kpi",
            "title": "Total Records", "value": f"{total_rows:,}",
            "subtitle": f"Across {total_tables} tables", "trend": "neutral",
            "icon": "hash", "gridW": 3, "gridH": 2,
        })

        # â”€â”€ Execute LLM-planned widgets â”€â”€
        if llm_widgets_raw:
            for spec in llm_widgets_raw:
                w_type = spec.get("type", "kpi")
                sql = spec.get("sql", "").strip()
                if not sql:
                    continue

                try:
                    results, columns = self._execute_sql(sql)
                except Exception as e:
                    logger.debug("[WorkspaceSqlAgent] Widget SQL failed: %s | %s", sql[:100], e)
                    continue

                if not results:
                    continue

                widget_idx += 1
                wid = f"ws-widget-{widget_idx}"

                if w_type == "kpi":
                    val = results[0].get(columns[0], "N/A") if columns else "N/A"
                    try:
                        display = self._format_number(float(val), self._infer_format_hint(spec.get("title", "")))
                    except (ValueError, TypeError):
                        display = str(val)
                    widgets.append({
                        "id": wid, "type": "kpi",
                        "title": spec.get("title", "Metric"),
                        "value": display,
                        "subtitle": spec.get("description", ""),
                        "trend": "neutral",
                        "icon": spec.get("icon", "activity"),
                        "sql_query": sql,
                        "gridW": 3, "gridH": 2,
                    })

                elif w_type == "chart":
                    label_col = columns[0] if columns else "label"
                    value_col = columns[1] if len(columns) > 1 else columns[0]
                    labels = [str(r.get(label_col, "")) for r in results[:30]]
                    values = []
                    for r in results[:30]:
                        try: values.append(float(r.get(value_col, 0)))
                        except: values.append(0)

                    ct = spec.get("chart_type", "bar")
                    if ct == "bar" and len(labels) <= 5:
                        ct = "pie"

                    widgets.append({
                        "id": wid, "type": "chart",
                        "chartType": ct,
                        "title": spec.get("title", "Chart"),
                        "description": spec.get("description", ""),
                        "chartData": {
                            "labels": labels,
                            "series": [{"name": value_col.replace("_", " ").title(), "data": values}],
                        },
                        "colorTheme": "indigo",
                        "icon": spec.get("icon", "bar-chart-2"),
                        "sql_query": sql,
                        "gridW": 6, "gridH": 3,
                    })

                elif w_type == "list":
                    label_col = columns[0] if columns else "label"
                    value_col = columns[1] if len(columns) > 1 else columns[0]
                    items = []
                    for r in results[:10]:
                        lbl = str(r.get(label_col, ""))
                        try: val_fmt = self._format_number(float(r.get(value_col, 0)), self._infer_format_hint(spec.get("title", "")))
                        except: val_fmt = str(r.get(value_col, ""))
                        items.append({"label": lbl, "value": val_fmt})
                    if len(items) >= 2:
                        widgets.append({
                            "id": wid, "type": "list",
                            "title": spec.get("title", "List"),
                            "items": items,
                            "icon": spec.get("icon", "trophy"),
                            "sql_query": sql,
                            "gridW": 4, "gridH": 3,
                        })
                    else:
                        widget_idx -= 1

                elif w_type == "insight":
                    insight_text = spec.get("text", spec.get("description", ""))
                    if results and columns:
                        try:
                            first_val = results[0].get(columns[0], "")
                            if first_val and not insight_text:
                                insight_text = f"Analysis shows: {first_val}"
                        except Exception:
                            pass
                    if insight_text:
                        widgets.append({
                            "id": wid, "type": "insight",
                            "title": spec.get("title", "Insight"),
                            "text": insight_text,
                            "icon": spec.get("icon", "lightbulb"),
                            "sql_query": sql,
                            "gridW": 6, "gridH": 2,
                        })
                    else:
                        widget_idx -= 1

        else:
            # â”€â”€ Fallback: rule-based generation (no LLM) â”€â”€
            numeric_cols = meta["numeric_cols"]
            categorical_cols = meta["categorical_cols"]

            _SKIP_COLS = {"id", "uuid", "is_processed", "created_at", "updated_at", "deleted_at"}
            numeric_cols = [c for c in numeric_cols if c["column_name"].lower() not in _SKIP_COLS]
            categorical_cols = [c for c in categorical_cols if c["column_name"].lower() not in _SKIP_COLS]

            for col_info in numeric_cols[:3]:
                cname = col_info["column_name"]
                tname = col_info["table_name"]
                sql = f'SELECT SUM("{cname}") AS val FROM "{tname}" LIMIT 1'
                try:
                    results, _ = self._execute_sql(sql)
                    raw_val = results[0]["val"] if results and results[0].get("val") is not None else 0
                    display = self._format_number(float(raw_val), self._infer_format_hint(cname))
                    widget_idx += 1
                    widgets.append({
                        "id": f"ws-widget-{widget_idx}", "type": "kpi",
                        "title": f"Total {cname.replace('_', ' ').title()}",
                        "value": display, "subtitle": f"Sum from {tname}",
                        "trend": "neutral", "icon": "trending-up",
                        "sql_query": sql, "gridW": 3, "gridH": 2,
                    })
                except Exception:
                    pass

            for cat_col in categorical_cols[:2]:
                cat_name = cat_col["column_name"]
                cat_table = cat_col["table_name"]
                same_num = [c for c in numeric_cols if c["table_name"] == cat_table]
                if same_num:
                    mn = same_num[0]["column_name"]
                    sql = f'SELECT "{cat_name}" AS label, SUM("{mn}") AS value FROM "{cat_table}" GROUP BY "{cat_name}" ORDER BY value DESC LIMIT 20'
                else:
                    sql = f'SELECT "{cat_name}" AS label, COUNT(*) AS value FROM "{cat_table}" GROUP BY "{cat_name}" ORDER BY value DESC LIMIT 20'
                try:
                    results, _ = self._execute_sql(sql)
                    if len(results) >= 2:
                        labels = [str(r["label"]) for r in results]
                        values = [float(r["value"]) for r in results]
                        widget_idx += 1
                        widgets.append({
                            "id": f"ws-widget-{widget_idx}", "type": "chart", "chartType": "bar",
                            "title": f"{cat_name.replace('_', ' ').title()} Distribution",
                            "chartData": {"labels": labels, "series": [{"name": "Value", "data": values}]},
                            "colorTheme": "indigo", "sql_query": sql,
                            "gridW": 6, "gridH": 3,
                        })
                except Exception:
                    pass

        # Build fingerprint
        fingerprint = {
            "mode": "workspace",
            "workspace_id": self.workspace_id,
            "table_count": total_tables,
            "total_rows": total_rows,
            "total_columns": total_cols,
            "measures": [{"col": c["column_name"], "table": c["table_name"], "agg": "sum"} for c in meta["numeric_cols"][:12]],
            "dimensions": [{"col": c["column_name"], "table": c["table_name"]} for c in meta["categorical_cols"][:10]],
        }

        logger.info("[WorkspaceSqlAgent] Dashboard generated (fallback) | widgets=%d", len(widgets))
        return {"status": "success", "widgets": widgets, "fingerprint": fingerprint}


    def generate_single_widget(self, query: str, widget_type_hint: Optional[str] = None, chart_type_hint: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate a single widget from a natural language query.
        Uses the chat pipeline to get SQL + results, then infers the widget type.
        """
        result = self.chat(query)

        if result.get("status") != "success":
            return result

        columns = result.get("columns", [])
        data = result.get("data", [])
        sql = result.get("sql", "")
        row_count = result.get("row_count", 0)

        # Infer widget type from result shape
        if widget_type_hint:
            w_type = widget_type_hint
        elif row_count == 1 and len(columns) == 1:
            w_type = "kpi"
        elif row_count == 1 and len(columns) <= 3:
            w_type = "kpi"
        elif row_count <= 20 and len(columns) == 2:
            # Check if second column is numeric â†’ chart candidate
            second_col_numeric = False
            if data:
                try:
                    float(data[0].get(columns[1], ""))
                    second_col_numeric = True
                except (ValueError, TypeError, IndexError):
                    pass
            w_type = "chart" if second_col_numeric else "list"
        else:
            w_type = "table"

        widget_id = f"ws-widget-{uuid.uuid4().hex[:8]}"

        if w_type == "kpi":
            val = data[0].get(columns[0], "N/A") if data else "N/A"
            subtitle_parts = []
            if len(columns) > 1 and data:
                for c in columns[1:3]:
                    subtitle_parts.append(f"{c}: {data[0].get(c, '')}")
            subtitle = " | ".join(subtitle_parts) if subtitle_parts else query

            try:
                display_val = self._format_number(float(val), self._infer_format_hint(columns[0]))
            except (ValueError, TypeError):
                display_val = str(val)

            widget = {
                "id": widget_id,
                "type": "kpi",
                "title": query[:80],
                "value": display_val,
                "subtitle": subtitle,
                "trend": "neutral",
                "icon": "activity",
                "sql_query": sql,
                "origin_query": query,
                "gridW": 3, "gridH": 2,
            }
        elif w_type == "list":
            label_col = columns[0] if columns else "label"
            value_col = columns[1] if len(columns) > 1 else columns[0]
            items = [
                {
                    "label": str(row.get(label_col, "")),
                    "value": str(row.get(value_col, "")),
                }
                for row in data[:10]
            ]
            widget = {
                "id": widget_id,
                "type": "list",
                "title": query[:80],
                "items": items,
                "icon": "list",
                "sql_query": sql,
                "origin_query": query,
                "gridW": 4, "gridH": 3,
            }
        elif w_type == "chart":
            chart_type = chart_type_hint or "bar"
            label_col = columns[0]
            value_col = columns[1] if len(columns) > 1 else columns[0]

            labels = [str(row.get(label_col, "")) for row in data]
            values = []
            for row in data:
                try:
                    values.append(float(row.get(value_col, 0)))
                except (ValueError, TypeError):
                    values.append(0)

            widget = {
                "id": widget_id,
                "type": "chart",
                "chartType": chart_type,
                "title": query[:80],
                "description": f"Chart generated from: {query}",
                "chartData": {
                    "labels": labels,
                    "series": [{"name": value_col.replace("_", " ").title(), "data": values}],
                },
                "colorTheme": "indigo",
                "sql_query": sql,
                "origin_query": query,
                "gridW": 6, "gridH": 3,
            }
        else:
            # Table widget â€” include all data
            widget = {
                "id": widget_id,
                "type": "table",
                "title": query[:80],
                "columns": columns,
                "data": data[:100],
                "row_count": row_count,
                "sql_query": sql,
                "origin_query": query,
                "gridW": 12, "gridH": 4,
            }

        return {
            "status": "success",
            "widget": widget,
        }

    def get_chart_schema(self) -> Dict[str, Any]:
        """
        Return column classification for the Chart Builder UI.
        Splits workspace columns into dimensions (categorical/date) and measures (numeric).
        Includes human-readable labels, sorts by cardinality, and groups by table.
        """
        meta = self._get_workspace_metadata()

        dimensions = []
        for c in meta["categorical_cols"]:
            stats = c.get("stats") or {}
            cardinality = stats.get("distinct_count", stats.get("nunique", 0)) or 0
            dimensions.append({
                "col": f"{c['table_name']}.{c['column_name']}",
                "table": c["table_name"],
                "column": c["column_name"],
                "label": c["column_name"].replace("_", " ").title(),
                "data_type": c.get("data_type", "text"),
                "cardinality": cardinality,
                "dim_type": "categorical",
            })

        for c in meta["date_cols"]:
            dimensions.append({
                "col": f"{c['table_name']}.{c['column_name']}",
                "table": c["table_name"],
                "column": c["column_name"],
                "label": c["column_name"].replace("_", " ").title(),
                "data_type": c.get("data_type", "timestamp"),
                "cardinality": 0,
                "dim_type": "temporal",
            })

        # Sort dimensions: temporal first, then by cardinality (low → useful for grouping)
        dimensions.sort(key=lambda d: (0 if d["dim_type"] == "temporal" else 1, d.get("cardinality", 0)))

        measures = []
        for c in meta["numeric_cols"]:
            measures.append({
                "col": f"{c['table_name']}.{c['column_name']}",
                "table": c["table_name"],
                "column": c["column_name"],
                "label": c["column_name"].replace("_", " ").title(),
                "data_type": c.get("data_type", "numeric"),
                "agg": "sum",
                "available_aggs": ["sum", "avg", "count", "min", "max"],
            })

        # Collect table list for grouping in the UI
        tables = [
            {"name": t["table_name"], "row_count": t.get("row_count", 0)}
            for t in meta["tables"]
        ]

        return {
            "dimensions": dimensions,
            "measures": measures,
            "tables": tables,
        }

    def generate_custom_chart(
        self,
        chart_type: str,
        dimension: str,
        measure: Optional[str] = None,
        aggregation: str = "sum",
    ) -> Dict[str, Any]:
        """
        Generate a chart widget from explicit Chart Builder parameters.
        dimension/measure format: "table_name.column_name"
        """
        # Parse dimension
        if "." in dimension:
            dim_table, dim_col = dimension.split(".", 1)
        else:
            dim_col = dimension
            # Find the table
            meta = self._get_workspace_metadata()
            dim_table = None
            for c in meta["columns"]:
                if c["column_name"] == dim_col:
                    dim_table = c["table_name"]
                    break
            if not dim_table:
                return {"status": "error", "message": f"Dimension column '{dimension}' not found"}

        # Parse measure
        agg_fn = aggregation.upper() if aggregation else "SUM"
        if agg_fn not in ("SUM", "AVG", "COUNT", "MIN", "MAX"):
            agg_fn = "SUM"

        if measure and measure != "count" and aggregation != "count":
            if "." in measure:
                meas_table, meas_col = measure.split(".", 1)
            else:
                meas_col = measure
                meas_table = dim_table

            # Build SQL with JOIN if tables differ
            if meas_table != dim_table:
                # Simplified: just use subqueries or assume same table for now
                sql = (
                    f'SELECT "{dim_col}" AS label, {agg_fn}("{meas_col}") AS value '
                    f'FROM "{dim_table}" '
                    f'GROUP BY "{dim_col}" '
                    f'ORDER BY value DESC LIMIT 50'
                )
            else:
                sql = (
                    f'SELECT "{dim_col}" AS label, {agg_fn}("{meas_col}") AS value '
                    f'FROM "{dim_table}" '
                    f'GROUP BY "{dim_col}" '
                    f'ORDER BY value DESC LIMIT 50'
                )
            series_name = f"{agg_fn.title()} of {meas_col.replace('_', ' ').title()}"
        else:
            # Count mode
            sql = (
                f'SELECT "{dim_col}" AS label, COUNT(*) AS value '
                f'FROM "{dim_table}" '
                f'GROUP BY "{dim_col}" '
                f'ORDER BY value DESC LIMIT 50'
            )
            series_name = "Count"

        try:
            results, _ = self._execute_sql(sql)
            labels = [str(r.get("label", "")) for r in results]
            values = [float(r.get("value", 0)) for r in results]

            dim_title = dim_col.replace("_", " ").title()

            widget = {
                "id": f"ws-chart-{uuid.uuid4().hex[:8]}",
                "type": "chart",
                "chartType": chart_type,
                "title": f"{series_name} by {dim_title}",
                "description": f"{chart_type.title()} chart of {series_name} grouped by {dim_title}.",
                "chartData": {
                    "labels": labels,
                    "series": [{"name": series_name, "data": values}],
                },
                "colorTheme": "indigo",
                "sql_query": sql,
                "gridW": 6, "gridH": 3,
            }

            return {"status": "success", "widget": widget}

        except Exception as e:
            return {"status": "error", "message": str(e)}
