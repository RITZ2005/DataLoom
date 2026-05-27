"""
Workspace Dashboard Builder — Per-table fingerprinting engine.

Uses the proven DashboardMixin from kpi_builder.py to generate widgets
for each table in a workspace by sampling data into pandas DataFrames.

Architecture:
  1. Sample each table into a DataFrame (max 5000 rows)
  2. Create a lightweight DashboardMixin wrapper with that DataFrame
  3. Run _build_file_fingerprint() + generate_kpi_dashboard() per table
  4. LLM selects the best widgets across tables + creates cross-table insights
  5. Return merged dashboard with full chartData/values/items (no SQL at render time)
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional, AsyncGenerator

import pandas as pd

from app.utils.logging import logger, log_full_exception
from app.core.dashboard.kpi_builder import DashboardMixin
from app.core.formatters import FormattersMixin

# ── Langfuse stubs (the mixin calls these) ──────────────────────────
try:
    from app.config import observe, langfuse_context, _LANGFUSE_CALLBACK_AVAILABLE
except ImportError:
    def observe(_func=None, **kwargs):
        def decorator(func): return func
        return decorator(_func) if _func else decorator
    class langfuse_context:
        @staticmethod
        def update_current_trace(**kwargs): pass
        @staticmethod
        def update_current_observation(**kwargs): pass
    _LANGFUSE_CALLBACK_AVAILABLE = False

# Max rows to sample per table
_MAX_SAMPLE_ROWS = 5000
# Max tables to fingerprint
_MAX_TABLES = 8
# Max total widgets to return
_MAX_DASHBOARD_WIDGETS = 14


class _TableDashboardAgent(DashboardMixin, FormattersMixin):
    """
    Lightweight wrapper around DashboardMixin for a single table.
    Sets up just enough state for _build_file_fingerprint() and
    generate_kpi_dashboard() to work.
    """

    def __init__(self, df: pd.DataFrame, table_name: str, llm=None):
        # Required by DashboardMixin
        self.df = df
        self.filename = table_name
        self.file_uuid = f"ws-table-{uuid.uuid4().hex[:8]}"
        self.llm = llm
        self.db = None  # No DB persistence for per-table gen
        self.table_name = table_name

        # Stubs required by various mixin methods
        self.embed_model = None
        self.embedding_dim = 0
        self.semantic_cache = None
        self.semantic_cache_threshold = 0
        self._last_normalized_query = None
        self.pandas_agent = None
        self.code_fixer_callback = None
        self.is_deleted = False
        self._sql_connection_mode = False
        self.mode = None
        self.user_id = None
        self.project_id = None
        self.subproject_id = None
        self.sheet_name = None
        self.file_group_id = None
        self.progress_callback = None
        self._last_dashboard_trace_info = None
        self.columns = df.columns.tolist() if df is not None else []

    def save_dashboard(self, widgets, fingerprint=None):
        """No-op: we don't persist per-table dashboards to DB."""
        pass

    def load_dashboard(self):
        """No cached dashboard — always generate fresh."""
        return None

    def delete_dashboard(self):
        """No-op."""
        pass


class WorkspaceDashboardBuilder:
    """
    Orchestrates per-table fingerprinting and widget generation for a workspace.
    
    Usage:
        builder = WorkspaceDashboardBuilder(db=db, workspace_id=workspace_id, llm=llm)
        result = builder.generate()
        # result = {"status": "success", "widgets": [...], "fingerprint": {...}}
    """

    def __init__(self, db, workspace_id: str, llm=None, schema_name: str = None):
        self.db = db
        self.workspace_id = workspace_id
        self.llm = llm
        self.schema_name = schema_name or f"ws_{workspace_id.replace('-', '_')}"

    async def generate_stream(self):
        """Async generator yielding widgets as they are created."""
        tables = self._get_tables()[:_MAX_TABLES]
        
        for t in tables:
            # Add a small delay to make the streaming visual effect more obvious
            # import asyncio; await asyncio.sleep(0.1)
            
            df = self._sample_table(t["table_name"])
            if df is not None:
                tr = self._generate_per_table_widgets(t["table_name"], df)
                for w in tr.get("widgets", []):
                    yield w

    def _get_tables(self) -> List[Dict]:
        """Get table metadata from workspace."""
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                # Get schema name
                cur.execute(
                    "SELECT schema_name FROM etl_system.workspaces WHERE workspace_id = %s",
                    (self.workspace_id,),
                )
                row = cur.fetchone()
                if row:
                    self.schema_name = row[0]

                # Get tables with row counts
                cur.execute(
                    """SELECT table_name, row_count, description
                       FROM etl_system.tables_metadata
                       WHERE workspace_id = %s
                       ORDER BY COALESCE(row_count, 0) DESC""",
                    (self.workspace_id,),
                )
                tables = []
                for r in cur.fetchall():
                    tables.append({
                        "table_name": r[0],
                        "row_count": r[1] or 0,
                        "description": r[2] or "",
                    })
                return tables

    def _sample_table(self, table_name: str, limit: int = _MAX_SAMPLE_ROWS) -> Optional[pd.DataFrame]:
        """Sample a table into a pandas DataFrame."""
        try:
            with self.db.get_connection() as conn:
                with conn.cursor() as cur:
                    # Set search_path for workspace schema
                    cur.execute(f"SET search_path TO \"{self.schema_name}\", public")

                    # Get row count first
                    cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
                    total_rows = cur.fetchone()[0]

                    if total_rows == 0:
                        return None

                    # Sample with LIMIT
                    cur.execute(f'SELECT * FROM "{table_name}" LIMIT {limit}')
                    columns = [desc[0] for desc in cur.description]
                    rows = cur.fetchall()

                df = pd.DataFrame(rows, columns=columns)

                # Drop obvious system columns
                drop_cols = [c for c in df.columns if c.lower() in {
                    'id', 'uuid', 'created_at', 'updated_at', 'deleted_at',
                    'is_processed', '_etl_loaded_at', '_etl_row_hash',
                }]
                if drop_cols:
                    df = df.drop(columns=drop_cols, errors='ignore')

                logger.info(
                    "[WorkspaceBuilder] Sampled %s: %d rows × %d cols (of %d total)",
                    table_name, len(df), len(df.columns), total_rows,
                )
                return df

        except Exception as e:
            logger.warning("[WorkspaceBuilder] Failed to sample %s: %s", table_name, e)
            return None

    def _generate_per_table_widgets(self, table_name: str, df: pd.DataFrame) -> Dict:
        """Generate widgets for a single table using the proven DashboardMixin.
        
        Uses llm=None for fast, data-driven widgets only (KPIs, charts, lists).
        This avoids expensive LLM calls for summaries/insights per table,
        keeping generation fast. Cross-table insights are handled separately
        by the relational builder.
        """
        t0 = time.perf_counter()
        # Pass llm=self.llm to enable LLM-heavy summaries/insights per-table
        agent = _TableDashboardAgent(df=df, table_name=table_name, llm=self.llm)

        try:
            result = agent.generate_kpi_dashboard()
            widgets = result.get("widgets", [])
            fingerprint = result.get("fingerprint", {})

            # Tag each widget with source table
            for w in widgets:
                w["source_table"] = table_name
                # Prefix ID to avoid collisions across tables
                w["id"] = f"ws-{table_name[:16]}-{w['id']}"

            elapsed = round((time.perf_counter() - t0) * 1000, 1)
            logger.info(
                "[WorkspaceBuilder] Table '%s': %d widgets in %dms",
                table_name, len(widgets), elapsed,
            )
            return {
                "table_name": table_name,
                "widgets": widgets,
                "fingerprint": fingerprint,
                "row_count": len(df),
                "col_count": len(df.columns),
            }

        except Exception as e:
            logger.warning("[WorkspaceBuilder] Widget gen failed for %s: %s", table_name, e)
            return {"table_name": table_name, "widgets": [], "fingerprint": {}, "error": str(e)}

    def _llm_select_and_synthesize(
        self,
        all_table_results: List[Dict],
        max_widgets: int = _MAX_DASHBOARD_WIDGETS,
    ) -> List[Dict]:
        """
        Use LLM to select the best widgets across tables and generate
        cross-table insight widgets.
        """
        if not self.llm:
            # No LLM: just take top widgets from each table proportionally
            return self._rule_based_selection(all_table_results, max_widgets)

        # Build a summary of all available widgets for the LLM
        widget_summaries = []
        all_widgets_map = {}
        for tr in all_table_results:
            for w in tr["widgets"]:
                wid = w["id"]
                all_widgets_map[wid] = w
                widget_summaries.append({
                    "id": wid,
                    "type": w.get("type"),
                    "title": w.get("title"),
                    "table": tr["table_name"],
                    "chart_type": w.get("chartType"),
                    "value": w.get("value", "")[:50] if w.get("type") == "kpi" else None,
                })

        table_info = []
        for tr in all_table_results:
            fp = tr.get("fingerprint", {})
            table_info.append({
                "table": tr["table_name"],
                "rows": tr.get("row_count", 0),
                "cols": tr.get("col_count", 0),
                "measures": len(fp.get("measures", [])),
                "dimensions": len(fp.get("dimensions", [])),
                "widget_count": len(tr["widgets"]),
            })

        prompt = f"""You are a BI dashboard curator. A workspace has {len(all_table_results)} tables.
Each table has been analyzed and widgets have been generated.

TABLES:
{json.dumps(table_info, indent=2)}

AVAILABLE WIDGETS ({len(widget_summaries)} total):
{json.dumps(widget_summaries, indent=2)}

YOUR TASK:
1. Select the {max_widgets} most diverse and insightful widgets from the list above.
   - Include widgets from MULTIPLE tables (don't favor one table)
   - Prefer: 1 summary, 3-4 KPIs, 2-3 charts (different types), 1-2 lists, 1 insight
   - Avoid duplicate metrics (e.g., don't pick "Total Revenue" from two tables)

2. Generate 1-2 cross-table INSIGHT widgets with analytical text.
   These should reference relationships between tables.

Return a JSON object:
{{
  "selected_widget_ids": ["id1", "id2", ...],
  "cross_table_insights": [
    {{
      "title": "Cross-Table Analysis",
      "text": "Analytical insight spanning multiple tables...",
      "icon": "lightbulb"
    }}
  ]
}}

Return ONLY the JSON, no markdown fences."""

        try:
            from app.core.llm import invoke_llm_with_retry
            raw = invoke_llm_with_retry(
                self.llm, 
                prompt, 
                max_retries=2, 
                context_name="Dashboard Synthesis"
            )
            
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            result = json.loads(raw)
            selected_ids = result.get("selected_widget_ids", [])
            cross_insights = result.get("cross_table_insights", [])

            # Build final widget list from selected IDs
            final_widgets = []
            for wid in selected_ids[:max_widgets]:
                if wid in all_widgets_map:
                    final_widgets.append(all_widgets_map[wid])

            # Add cross-table insights
            for ci in cross_insights[:2]:
                final_widgets.append({
                    "id": f"ws-cross-{uuid.uuid4().hex[:8]}",
                    "type": "insight",
                    "title": ci.get("title", "Cross-Table Insight"),
                    "text": ci.get("text", ""),
                    "icon": ci.get("icon", "lightbulb"),
                    "gridW": 6, "gridH": 2,
                    "source_table": "_cross_table",
                })

            if len(final_widgets) < 4:
                # LLM selection was too sparse — fall back to rule-based
                logger.warning("[WorkspaceBuilder] LLM selected only %d widgets, falling back", len(final_widgets))
                return self._rule_based_selection(all_table_results, max_widgets)

            logger.info("[WorkspaceBuilder] LLM selected %d widgets + %d cross-insights",
                        len(final_widgets) - len(cross_insights), len(cross_insights))
            return final_widgets

        except Exception as e:
            logger.warning("[WorkspaceBuilder] LLM synthesis failed: %s — using rule-based", e)
            return self._rule_based_selection(all_table_results, max_widgets)

    def _rule_based_selection(self, all_table_results: List[Dict], max_widgets: int) -> List[Dict]:
        """Fallback: select widgets proportionally from each table."""
        all_widgets = []
        for tr in all_table_results:
            all_widgets.extend(tr["widgets"])

        if len(all_widgets) <= max_widgets:
            return all_widgets

        # Strategy: summary first, then interleave by type
        selected = []
        summaries = [w for w in all_widgets if w.get("type") == "summary"]
        kpis = [w for w in all_widgets if w.get("type") == "kpi"]
        charts = [w for w in all_widgets if w.get("type") == "chart"]
        lists = [w for w in all_widgets if w.get("type") == "list"]
        insights = [w for w in all_widgets if w.get("type") == "insight"]

        # Take 1 summary (preferably from largest table)
        if summaries:
            selected.append(summaries[0])

        # Take proportional KPIs, charts, lists, insights
        remaining = max_widgets - len(selected)
        for bucket, cap in [(kpis, 4), (charts, 5), (lists, 3), (insights, 2)]:
            take = min(len(bucket), cap, remaining)
            selected.extend(bucket[:take])
            remaining -= take
            if remaining <= 0:
                break

        return selected[:max_widgets]

    def generate(self) -> Dict[str, Any]:
        """
        Main entry point — generates the full workspace dashboard.
        
        Branching logic:
          - Single table  → Fast Pandas-based DashboardMixin (per-table fingerprinting)
          - Multiple tables → LLM Relational Builder (SQL JOINs, cross-table insights)
        
        Returns:
            {"status": "success", "widgets": [...], "fingerprint": {...}}
        """
        t0 = time.perf_counter()
        logger.info("[WorkspaceBuilder] Starting workspace dashboard generation | workspace_id=%s", self.workspace_id)

        # 1. Get tables
        tables = self._get_tables()
        if not tables:
            return {"status": "success", "widgets": [], "fingerprint": {"mode": "workspace", "table_count": 0}}

        # Filter to tables with data, limit to top N
        tables = [t for t in tables if t.get("row_count", 0) > 0][:_MAX_TABLES]
        logger.info("[WorkspaceBuilder] Processing %d tables", len(tables))

        # ── BRANCH: Single table → Pandas engine ──
        if len(tables) == 1:
            logger.info("[WorkspaceBuilder] Single table detected → using Pandas engine")
            df = self._sample_table(tables[0]["table_name"])
            if df is None or len(df) == 0:
                return {"status": "success", "widgets": [], "fingerprint": {"mode": "workspace", "table_count": 1}}

            result = self._generate_per_table_widgets(tables[0]["table_name"], df)
            widgets = result.get("widgets", [])
            for idx, w in enumerate(widgets):
                w["id"] = f"ws-{self.workspace_id[:8]}-w{idx + 1}"

            elapsed = round((time.perf_counter() - t0) * 1000, 1)
            logger.info("[WorkspaceBuilder] ✅ Single-table dashboard: %d widgets in %dms", len(widgets), elapsed)
            return {
                "status": "success",
                "widgets": widgets,
                "fingerprint": {"mode": "single_table", "table_count": 1, "table": tables[0]["table_name"]},
            }

        # ── MULTIPLE TABLES → Relational SQL Builder ──
        relational_widgets = []
        if len(tables) > 1:
            logger.info("[WorkspaceBuilder] Multiple tables (%d) detected → using Relational Builder", len(tables))
            try:
                relational = WorkspaceRelationalBuilder(
                    db=self.db,
                    workspace_id=self.workspace_id,
                    llm=self.llm,
                    schema_name=self.schema_name,
                )
                result = relational.generate(tables)
                if result.get("status") == "success" and result.get("widgets"):
                    relational_widgets = result["widgets"]
                    elapsed = round((time.perf_counter() - t0) * 1000, 1)
                    logger.info("[WorkspaceBuilder] ✅ Relational dashboard: %d widgets in %dms", len(relational_widgets), elapsed)
                else:
                    logger.warning("[WorkspaceBuilder] Relational builder returned no widgets")
            except Exception as e:
                logger.warning("[WorkspaceBuilder] Relational builder failed: %s", e)

        # ── COMBINE: Per-table generation ──
        all_table_results = []
        for t in tables:
            df = self._sample_table(t["table_name"])
            if df is not None and len(df) > 0:
                result = self._generate_per_table_widgets(t["table_name"], df)
                if result["widgets"]:
                    all_table_results.append(result)

        if not all_table_results and not relational_widgets:
            return {"status": "success", "widgets": [], "fingerprint": {"mode": "workspace", "table_count": len(tables)}}

        total_per_table_widgets = sum(len(tr["widgets"]) for tr in all_table_results)
        logger.info("[WorkspaceBuilder] Generated %d per-table widgets across %d tables",
                    total_per_table_widgets, len(all_table_results))

        # 3. Combine widgets: keep all relational and ALL per-table widgets
        final_widgets = relational_widgets.copy()
        if all_table_results:
            for tr in all_table_results:
                final_widgets.extend(tr["widgets"])

        # 4. Re-number widget IDs cleanly, ensuring global uniqueness
        for idx, w in enumerate(final_widgets):
            w["id"] = f"ws-{self.workspace_id[:8]}-w{idx + 1}"

        # 5. Build combined fingerprint
        all_measures = []
        all_dimensions = []
        for tr in all_table_results:
            fp = tr.get("fingerprint", {})
            for m in fp.get("measures", []):
                m_copy = dict(m) if isinstance(m, dict) else {"col": str(m)}
                m_copy["table"] = tr["table_name"]
                all_measures.append(m_copy)
            for d in fp.get("dimensions", []):
                d_copy = dict(d) if isinstance(d, dict) else {"col": str(d)}
                d_copy["table"] = tr["table_name"]
                all_dimensions.append(d_copy)

        combined_fingerprint = {
            "mode": "workspace",
            "workspace_id": self.workspace_id,
            "table_count": len(tables),
            "tables_analyzed": len(all_table_results),
            "total_per_table_widgets": total_per_table_widgets,
            "measures": all_measures[:12],
            "dimensions": all_dimensions[:10],
        }

        elapsed = round((time.perf_counter() - t0) * 1000, 1)
        logger.info(
            "[WorkspaceBuilder] ✅ Dashboard complete: %d widgets in %dms (from %d tables)",
            len(final_widgets), elapsed, len(all_table_results),
        )

        return {
            "status": "success",
            "widgets": final_widgets,
            "fingerprint": combined_fingerprint,
        }

class BaseSqlWidgetBuilder:
    """Base class for builders that execute and self-heal SQL-based dashboard widgets.

    Provides:
      - _execute_widget_sql() — single SQL attempt with result caching
      - _execute_and_retry_widget_sql() — structured 2-pass retry using
        shared error diagnostics from app.core.llm (same logic as chat pipeline)
    """

    # Maximum time per widget query (seconds)
    _WIDGET_SQL_TIMEOUT = "15s"
    _shared_conn = None  # Reusable connection for batch widget execution

    class _ConnectionScope:
        """Context manager that acquires ONE connection and shares it across widget SQL calls."""
        def __init__(self, builder):
            self.builder = builder
            self._ctx = None

        def __enter__(self):
            self._ctx = self.builder.db.get_connection()
            self.builder._shared_conn = self._ctx.__enter__()
            return self.builder._shared_conn

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.builder._shared_conn = None
            if self._ctx:
                self._ctx.__exit__(exc_type, exc_val, exc_tb)

    def connection_scope(self):
        """Acquire a shared DB connection for all widget SQL within this scope.

        Usage:
            with self.connection_scope():
                for widget in widgets:
                    self._execute_widget_sql(widget)
        """
        return self._ConnectionScope(self)

    def _execute_widget_sql(self, widget: Dict) -> Dict:
        """Execute a widget's SQL query and cache the results into the widget object.

        If _shared_conn is set (via connection_scope()), reuses it instead of
        acquiring a new connection per widget.
        """
        sql = widget.get("sql_query", "")
        if not sql:
            return widget

        def _run_sql(conn):
            with conn.cursor() as cur:
                cur.execute(f'SET search_path TO "{self.schema_name}", public')
                cur.execute(f"SET statement_timeout = '{self._WIDGET_SQL_TIMEOUT}'")
                cur.execute(sql)
                columns = [d[0] for d in cur.description]
                rows = cur.fetchall()
            return columns, rows

        try:
            # Log SQL execution attempt
            logger.info(
                "[_execute_widget_sql] Executing SQL for widget '%s' (type=%s)\nSQL:\n%s",
                widget.get("title"), widget.get("type"), sql
            )
            
            # Reuse shared connection if available, else acquire a new one
            if self._shared_conn:
                columns, rows = _run_sql(self._shared_conn)
            else:
                with self.db.get_connection() as conn:
                    columns, rows = _run_sql(conn)

            logger.info(
                "[_execute_widget_sql] ✅ SQL executed successfully for '%s' | Returned %d rows, %d columns",
                widget.get("title"), len(rows), len(columns)
            )

            wtype = widget.get("type", "chart")
            
            if wtype == "kpi":
                if rows and columns:
                    widget["value"] = str(rows[0][-1]) if rows[0] else "0"
                    widget["subtitle"] = widget.get("subtitle", f"from {len(rows)} records")
            elif wtype == "list":
                widget["items"] = [
                    {"label": str(r[0]), "value": str(r[-1]) if len(r) > 1 else ""}
                    for r in rows[:10]
                ]
            elif wtype == "chart":
                if len(columns) >= 2:
                    labels = [str(r[0]) for r in rows]
                    values = [float(r[-1]) if r[-1] is not None else 0 for r in rows]
                    widget["chartData"] = {
                        "labels": labels,
                        "series": [{"name": columns[-1], "data": values}],
                    }

            widget["_data_cached"] = True

        except Exception as e:
            logger.error(
                "[_execute_widget_sql] ❌ SQL EXECUTION FAILED for widget '%s' (type=%s)\nSQL:\n%s\n\nERROR:\n%s",
                widget.get("title"), widget.get("type"), sql, str(e)
            )
            widget["_sql_error"] = str(e)
            # Rollback aborted transaction so subsequent queries on same connection don't cascade-fail
            if self._shared_conn:
                try:
                    self._shared_conn.rollback()
                    # Re-set search_path after rollback so next widget SQL finds the right tables
                    with self._shared_conn.cursor() as _cur:
                        _cur.execute(f'SET search_path TO "{self.schema_name}", public')
                except Exception:
                    pass

        return widget

    def _execute_and_retry_widget_sql(
        self,
        widget: Dict,
        context_text: str,
        builder_name: str,
        column_metadata: Optional[List[Dict]] = None,
    ) -> Dict:
        """Execute widget SQL with structured 2-pass self-healing retry.

        Pass 1: Execute → if error, extract structured diagnostics → regenerate SQL.
        Pass 2: If regenerated SQL repeats the failing predicate, retry with strict=True.
        Fallback: Return widget as error card (not silently dropped).
        """
        from app.core.llm import (
            invoke_llm_with_retry,
            extract_sql_error_hints,
            regenerated_sql_repeats_error,
            strip_markdown_fences,
        )

        # ── Attempt 1: initial execution ──
        widget = self._execute_widget_sql(widget)
        if not widget.get("_sql_error") or not getattr(self, "llm", None):
            return widget

        error_msg = widget["_sql_error"]
        original_sql = widget.get("sql_query", "")
        columns = column_metadata or []

        # ── Extract structured diagnostics ──
        error_hints = extract_sql_error_hints(error_msg, columns)
        logger.info(
            "[%s] 🔍 DIAGNOSING SQL error for widget '%s'\nRaw Error: %s\n\nDiagnostics:\n"
            "  • Type Mismatch: %s\n"
            "  • Expected Type: %s\n"
            "  • Bad Value: %s\n"
            "  • Failing Expression: %s\n"
            "  • Comparison Column: %s\n"
            "  • Summary: %s\n"
            "  • Recommended Action: %s",
            builder_name,
            widget.get("title"),
            error_msg,
            error_hints.get("is_type_mismatch"),
            error_hints.get("expected_type"),
            error_hints.get("bad_value"),
            error_hints.get("line_expr"),
            error_hints.get("comparison_column"),
            error_hints.get("human_summary"),
            error_hints.get("recommended_action"),
        )

        # ── Build enhanced retry prompt with diagnostics ──
        diagnostics_section = ""
        if error_hints.get("is_type_mismatch") or error_hints.get("recommended_action"):
            diagnostics_section = f"""
=== EXECUTION ERROR DIAGNOSTICS ===
  expected_type: {error_hints.get('expected_type')}
  bad_value: {error_hints.get('bad_value')}
  failing_expression: {error_hints.get('line_expr')}
  comparison_column: {error_hints.get('comparison_column')}
  is_type_mismatch: {error_hints.get('is_type_mismatch')}
  summary: {error_hints.get('human_summary')}
  recommended_action: {error_hints.get('recommended_action')}
"""
            if error_hints.get("candidate_name_columns"):
                diagnostics_section += f"  suggested_name_columns: {', '.join(error_hints['candidate_name_columns'][:5])}\n"
            elif error_hints.get("candidate_text_columns"):
                diagnostics_section += f"  suggested_text_columns: {', '.join(error_hints['candidate_text_columns'][:5])}\n"

        for attempt, strict in enumerate([(False,), (True,)], start=1):
            is_strict = strict[0]
            strict_instruction = ""
            if is_strict:
                strict_instruction = (
                    "\nIMPORTANT: Your previous recovery repeated the same failure pattern. "
                    "Do NOT reuse the same failing comparison. If a value is a person name and "
                    "the previous column is numeric, switch the filter to an appropriate "
                    "text/name column from diagnostics."
                )

            retry_prompt = f"""You are a PostgreSQL expert fixing a failed query for a dashboard widget.

DATABASE CONTEXT:
{context_text}

FAILED SQL:
{original_sql}

ERROR RETURNED BY POSTGRESQL:
{error_msg}
{diagnostics_section}
YOUR TASK:
Fix the SQL query so it executes successfully.
- ONLY use tables and columns explicitly defined in the TABLE-COLUMN MAP.
- Ensure the query uses standard PostgreSQL syntax.
- Do NOT use any schema prefixes for table names.
- Never repeat the exact failing predicate from the error message.
- If diagnostics indicate type mismatch, replace the failing column with an appropriate text column.
- Return ONLY the raw SQL query, without markdown blocks or explanation.
{strict_instruction}

Corrected SQL:"""

            try:
                logger.info(
                    "[%s] 🔧 RETRY PASS %d%s for widget '%s'\nAttempting LLM SQL repair...",
                    builder_name, attempt, " (STRICT MODE)" if is_strict else "", widget.get("title")
                )
                
                fixed_sql = invoke_llm_with_retry(
                    self.llm,
                    retry_prompt,
                    max_retries=1,
                    context_name=f"Widget SQL Retry (pass {attempt}{'—strict' if is_strict else ''})",
                )
                fixed_sql = strip_markdown_fences(fixed_sql)

                if not fixed_sql:
                    logger.warning("[%s] ⚠️ LLM returned empty SQL on retry pass %d", builder_name, attempt)
                    continue

                logger.info(
                    "[%s] 📝 LLM generated repaired SQL on pass %d:\n%s",
                    builder_name, attempt, fixed_sql
                )

                # Check if regenerated SQL repeats the same bad predicate
                if not is_strict and regenerated_sql_repeats_error(fixed_sql, error_hints):
                    logger.warning(
                        "[%s] ⚠️ DIAGNOSTICS: Regenerated SQL on pass %d STILL REPEATS the failing predicate '%s'\n"
                        "Original bad value: '%s' | Failing column: '%s'\n"
                        "Escalating to STRICT MODE (pass 2) with explicit instructions to avoid this pattern",
                        builder_name, attempt, error_hints.get("bad_value"), 
                        error_hints.get("bad_value"), error_hints.get("comparison_column"),
                    )
                    original_sql = fixed_sql  # Feed the latest attempt into the next pass
                    continue

                logger.info(
                    "[%s] ✅ Diagnostics passed: Repaired SQL does not repeat bad predicate. Executing...",
                    builder_name
                )
                widget["sql_query"] = fixed_sql
                widget.pop("_sql_error", None)
                widget = self._execute_widget_sql(widget)

                if not widget.get("_sql_error"):
                    logger.info(
                        "[%s] 🎉 SQL SELF-HEALED SUCCESSFULLY for '%s' on pass %d!",
                        builder_name, widget.get("title"), attempt,
                    )
                    return widget

                # Update error info for next pass
                logger.warning(
                    "[%s] ⚠️ Execution still failed on pass %d. Retrying... Error: %s",
                    builder_name, attempt, widget.get("_sql_error")
                )
                error_msg = widget["_sql_error"]
                original_sql = fixed_sql

            except Exception as retry_err:
                logger.error(
                    "[%s] ❌ SQL Retry pass %d EXCEPTION: %s",
                    builder_name, attempt, retry_err
                )

        # ── All retries exhausted — return error card ──
        if widget.get("_sql_error"):
            logger.error(
                "[%s] ❌❌ WIDGET PERMANENTLY FAILED after all retry passes\n"
                "Widget: '%s' (type=%s)\n"
                "Final Error: %s\n"
                "This widget will be persisted with _sql_error flag and shown as broken in the dashboard.",
                builder_name, widget.get("title"), widget.get("type"), widget.get("_sql_error"),
            )

        return widget


class WorkspaceRelationalBuilder(BaseSqlWidgetBuilder):
    """
    Multi-table relational dashboard builder.
    
    Uses the LLM as a Business Analyst to:
    1. Collect full workspace schema (tables, columns, sample data)
    2. Load user-defined or auto-inferred relationships (PK/FK)
    3. Ask the LLM to design cross-table SQL widgets with JOINs
    4. Execute those SQL queries and cache results into the widget objects
    """

    def __init__(self, db, workspace_id: str, llm=None, schema_name: str = None):
        self.db = db
        self.workspace_id = workspace_id
        self.llm = llm
        self.schema_name = schema_name or f"ws_{workspace_id.replace('-', '_')}"

    def _get_relationships(self) -> List[Dict]:
        """Load user-defined relationships from DB."""
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT source_table, source_column, target_table, target_column, relationship_type
                       FROM etl_system.workspace_relationships
                       WHERE workspace_id = %s""",
                    (self.workspace_id,),
                )
                return [
                    {"source_table": r[0], "source_column": r[1],
                     "target_table": r[2], "target_column": r[3],
                     "type": r[4]}
                    for r in cur.fetchall()
                ]

    def _get_full_schema(self, tables: List[Dict]) -> List[Dict]:
        """Collect column metadata + sample values for all tables."""
        schema_info = []
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f'SET search_path TO "{self.schema_name}", public')
                for t in tables:
                    tname = t["table_name"]
                    # Get columns
                    cur.execute(
                        """SELECT column_name, data_type, description, sample_values
                           FROM etl_system.columns_metadata
                           WHERE workspace_id = %s AND table_name = %s""",
                        (self.workspace_id, tname),
                    )
                    columns = []
                    for c in cur.fetchall():
                        columns.append({
                            "name": c[0],
                            "type": c[1]
                        })

                    schema_info.append({
                        "table_name": tname,
                        "columns": columns
                    })
        return schema_info

    def _save_inferred_relationships(self, inferred: List[Dict]):
        """Persist LLM-inferred relationships to DB."""
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                for rel in inferred:
                    rel_id = f"rel-{uuid.uuid4().hex[:12]}"
                    try:
                        cur.execute(
                            """INSERT INTO etl_system.workspace_relationships
                                   (relationship_id, workspace_id, source_table, source_column,
                                    target_table, target_column, relationship_type, inferred_by)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, 'llm')
                               ON CONFLICT DO NOTHING""",
                            (rel_id, self.workspace_id, rel.get("source_table"), rel.get("source_column"),
                             rel.get("target_table"), rel.get("target_column"), rel.get("type", "foreign_key")),
                        )
                    except Exception:
                        pass
            conn.commit()



    def generate(self, tables: List[Dict]) -> Dict[str, Any]:
        """
        Main entry: design a multi-table relational dashboard.
        
        1. Collect schema + relationships
        2. LLM designs widgets with SQL queries
        3. Execute SQL and cache results
        """
        if not self.llm:
            logger.warning("[RelationalBuilder] No LLM available, cannot generate relational dashboard")
            return {"status": "error", "widgets": []}

        t0 = time.perf_counter()
        logger.info("[RelationalBuilder] Starting multi-table dashboard | %d tables", len(tables))

        # 1. Collect full schema
        schema_info = self._get_full_schema(tables)

        # 2. Load existing relationships
        relationships = self._get_relationships()
        has_user_relationships = len(relationships) > 0

        # 3. Build prompt strings
        schema_lines = ["=== TABLE-COLUMN MAP ==="]
        for tbl in schema_info:
            cnames = [c["name"] for c in tbl["columns"]]
            schema_lines.append(f"  - \"{tbl['table_name']}\": " + ", ".join(f'"{c}"' for c in cnames))
        schema_text = "\n".join(schema_lines)

        # ── Phase A: If no relationships, ask LLM to infer them first ──
        if not has_user_relationships:
            infer_prompt = f"""You are a Database Architect. Analyze this schema and infer foreign key relationships.

SCHEMA:
{schema_text}

Look at column names to identify PK/FK links.
For example: if orders has customer_id and customers has id, that's a FK.

Return a JSON array of relationships:
[
  {{"source_table": "orders", "source_column": "customer_id", "target_table": "customers", "target_column": "id", "type": "foreign_key"}}
]

Return ONLY the JSON array, no markdown."""

            try:
                from app.core.llm import invoke_llm_with_retry
                raw = invoke_llm_with_retry(self.llm, infer_prompt, max_retries=1, context_name="Relationship Inference")
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                inferred = json.loads(raw)
                if isinstance(inferred, list) and inferred:
                    relationships = inferred
                    self._save_inferred_relationships(inferred)
                    logger.info("[RelationalBuilder] LLM inferred %d relationships", len(inferred))
            except Exception as e:
                logger.warning("[RelationalBuilder] Relationship inference failed: %s", e)

        rel_lines = ["=== RELATIONSHIPS ==="]
        if relationships:
            for rel in relationships:
                src = f"{rel.get('source_table', '?')}.{rel.get('source_column', '?')}"
                tgt = f"{rel.get('target_table', '?')}.{rel.get('target_column', '?')}"
                rel_lines.append(f"  - {src} -> {tgt}")
        else:
            rel_lines.append("  (No relationships defined)")
        rel_text = "\n".join(rel_lines)

        # ── Phase B: Business Analyst prompt for widget design ──
        analyst_prompt = f"""You are an expert Business Analyst designing a comprehensive dashboard.

WORKSPACE SCHEMA ({len(tables)} tables):
{schema_text}

TABLE RELATIONSHIPS:
{rel_text}

YOUR TASK:
Analyze the data thoroughly and design the MAXIMUM number of highly impactful dashboard widgets possible. Do not restrict yourself to a specific number; create as many meaningful and distinct widgets as the data supports. You MUST prioritize **cross-table insights** using SQL JOINs where relationships exist.

WIDGET MIX REQUIREMENTS:
Ensure a comprehensive mix of:
- KPI cards (single aggregated value like Total Revenue, Avg Order Value)
- Charts (bar, line, pie — showing breakdowns across related tables)
- Lists (Top 5 / Bottom 5 rankings)
- Insight cards (text-based analytical observations)

SQL RULES:
- Write valid PostgreSQL queries.
- Use proper JOINs based on the relationships. If no relationships are defined, you MUST infer them yourself from matching column names (like 'customer_id').
- CRITICAL: ONLY query tables that are EXPLICITLY listed in the TABLE-COLUMN MAP above. Do NOT assume the existence of any other tables, even if a column name suggests it (e.g., just because 'product_id' exists does NOT mean a 'products' table exists).
- CRITICAL: Use EXACTLY the table names and column names provided in the schema. Do not hallucinate columns. Do not drop prefixes (e.g. if a table is 'etl_4_products', you MUST use 'etl_4_products', not 'products').
- CRITICAL: Do NOT assume primary keys are named 'id' or string columns are named 'name'. READ the schema explicitly to find the correct column names (e.g. 'product_id', 'first_name').
- CRITICAL: In PostgreSQL, any column in the SELECT clause that is not an aggregate function MUST appear in the GROUP BY clause.
- Every chart query must return 2-3 columns: dimension(s) + metric.
- KPI queries must return a single row with a single value.
- List queries must return label + value columns, ORDER BY value DESC, LIMIT 5-10.
- Do NOT use schema prefixes — tables are in the search_path.

Return a JSON array of widgets:
[
  {{
    "title": "Descriptive Chart Title",
    "type": "chart",
    "chartType": "bar",
    "sql_query": "",
    "gridW": 6,
    "gridH": 3
  }},
  {{
    "title": "Descriptive KPI Title",
    "type": "kpi",
    "sql_query": "",
    "icon": "dollar-sign",
    "gridW": 3,
    "gridH": 2
  }},
  {{
    "title": "Top 5 Dimension by Metric",
    "type": "list",
    "sql_query": ,
    "gridW": 4,
    "gridH": 3
  }},
  {{
    "title": "Cross-Table Analysis",
    "type": "insight",
    "text": "Your analytical insight here...",
    "icon": "lightbulb",
    "gridW": 6,
    "gridH": 2
  }}
]

Return ONLY the JSON array, no markdown fences."""

        try:
            logger.info("[RelationalBuilder] Prompt context schema length: %d chars", len(schema_text))
            logger.info("[RelationalBuilder] Prompt Context Schema:\n%s", schema_text)
            logger.info("[RelationalBuilder] Prompt Context Relationships:\n%s", rel_text)
            from app.core.llm import invoke_llm_with_retry
            raw = invoke_llm_with_retry(self.llm, analyst_prompt, max_retries=2, context_name="Relational Dashboard Design")
            
            logger.info("[RelationalBuilder] Raw LLM Output:\n%s", raw)
            
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            widgets = json.loads(raw)
            if not isinstance(widgets, list):
                widgets = widgets.get("widgets", [])

            logger.info("[RelationalBuilder] LLM designed %d widgets", len(widgets))
            for w in widgets:
                logger.info("[RelationalBuilder] Widget: '%s' | SQL: %s", w.get("title"), w.get("sql_query", "None"))

        except Exception as e:
            logger.error("[RelationalBuilder] LLM design failed: %s", e)
            return {"status": "error", "widgets": [], "error": str(e)}

        # 4. Execute SQL and cache data for each widget
        final_widgets = []
        with self.connection_scope():
            for idx, w in enumerate(widgets):
                w["id"] = f"ws-rel-{idx + 1}"
                w["source_table"] = "_multi_table"

                # Assign default grid sizes if missing
                if "gridW" not in w:
                    w["gridW"] = 6 if w.get("type") == "chart" else 3
                if "gridH" not in w:
                    w["gridH"] = 3 if w.get("type") in ("chart", "list") else 2

                # Execute SQL and retry if failed
                if w.get("sql_query"):
                    context_for_retry = f"{schema_text}\n{rel_text}"
                    w = self._execute_and_retry_widget_sql(w, context_text=context_for_retry, builder_name="RelationalBuilder")

                final_widgets.append(w)

        elapsed = round((time.perf_counter() - t0) * 1000, 1)
        logger.info("[RelationalBuilder] ✅ Dashboard complete: %d widgets in %dms", len(final_widgets), elapsed)

        return {
            "status": "success",
            "widgets": final_widgets,
            "fingerprint": {
                "mode": "relational",
                "workspace_id": self.workspace_id
            }
        }

class WorkspaceIncrementalBuilder(BaseSqlWidgetBuilder):
    """
    Incremental Dashboard Builder for newly added tables.
    
    When a new pipeline loads data, this builder:
    1. Loads relationships and existing schema context
    2. Asks the LLM to design widgets connecting NEW tables to OLD data
    3. Executes the SQL queries and caches results
    4. Tags all new widgets with is_newly_added=True for frontend highlighting
    """
    def __init__(self, db, workspace_id: str, llm=None, schema_name: str = None):
        self.db = db
        self.workspace_id = workspace_id
        self.llm = llm
        self.schema_name = schema_name or f"ws_{workspace_id.replace('-', '_')}"

    def _get_relationships(self) -> List[Dict]:
        """Load existing relationships from DB."""
        try:
            with self.db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT source_table, source_column, target_table, target_column, relationship_type
                           FROM etl_system.workspace_relationships
                           WHERE workspace_id = %s""",
                        (self.workspace_id,),
                    )
                    return [
                        {"source_table": r[0], "source_column": r[1],
                         "target_table": r[2], "target_column": r[3],
                         "type": r[4]}
                        for r in cur.fetchall()
                    ]
        except Exception:
            return []



    def build_incremental_dashboard(
        self,
        list_of_new_tables: List[str],
        full_database_schema: Dict,
        semantic_layer: Dict,
        existing_widgets: List[Dict],
        user_hints: str = ""
    ) -> Dict:
        """
        Takes the delta (new tables) and generates SQL-driven insight widgets.
        Returns newly generated SQL widgets and a list of obsolete widget IDs to remove.
        """
        t0 = time.perf_counter()
        logger.info(
            "[WorkspaceIncrementalBuilder] Processing delta for workspace %s | New Tables: %s",
            self.workspace_id, list_of_new_tables
        )

        if not self.llm:
            logger.warning("[WorkspaceIncrementalBuilder] No LLM provided, returning empty delta.")
            return {"new_widgets": [], "remove_widgets": []}

        # Load relationships
        relationships = self._get_relationships()

        # 1. Structure the prompt context
        schema_lines = ["=== TABLE-COLUMN MAP ==="]
        for t in full_database_schema.get("tables", []):
            tname = t.get("table_name")
            cnames = [c.get("column_name") for c in full_database_schema.get("columns", []) if c.get("table_name") == tname]
            if cnames:
                schema_lines.append(f"  - \"{tname}\": " + ", ".join(f'"{c}"' for c in cnames))
        schema_text = "\n".join(schema_lines)

        rel_lines = ["=== EXISTING RELATIONSHIPS ==="]
        if relationships:
            for rel in relationships:
                src = f"{rel.get('source_table', '?')}.{rel.get('source_column', '?')}"
                tgt = f"{rel.get('target_table', '?')}.{rel.get('target_column', '?')}"
                rel_lines.append(f"  - {src} -> {tgt}")
        else:
            rel_lines.append("  (No relationships defined)")
        rel_text = "\n".join(rel_lines)
        
        # ── Phase 1: FAST PANDAS WIDGETS (Instant UI Feedback) ──
        logger.info(
            "[IncrementalBuilder] 🚀 PHASE 1: FAST PANDAS WIDGETS (data-driven, no LLM)\nProcessing %d new table(s): %s",
            len(list_of_new_tables), list_of_new_tables
        )
        new_table_widgets = []
        try:
            from app.core.dashboard.workspace_builder import WorkspaceDashboardBuilder
            fast_builder = WorkspaceDashboardBuilder(db=self.db, workspace_id=self.workspace_id, llm=None, schema_name=self.schema_name)
            for table_idx, new_table in enumerate(list_of_new_tables, 1):
                logger.info("[IncrementalBuilder] 📊 Processing table %d/%d: '%s'...", table_idx, len(list_of_new_tables), new_table)
                df = fast_builder._sample_table(new_table)
                if df is not None and not df.empty:
                    logger.info(
                        "[IncrementalBuilder] ✅ Sampled table '%s': %d rows × %d cols",
                        new_table, len(df), len(df.columns)
                    )
                    tr = fast_builder._generate_per_table_widgets(new_table, df)
                    generated = tr.get("widgets", [])
                    logger.info(
                        "[IncrementalBuilder] 📈 Generated %d widgets for '%s' (fingerprint: %s)",
                        len(generated), new_table, tr.get("fingerprint", "unknown")
                    )
                    for idx, w in enumerate(generated, 1):
                        logger.info(
                            "[IncrementalBuilder]   • Widget %d: '%s' (type=%s, chart_type=%s)",
                            idx, w.get("title"), w.get("type"), w.get("chartType")
                        )
                        w["id"] = f"ws-{self.workspace_id[:8]}-winc{uuid.uuid4().hex[:4]}-{idx}"
                        w["is_newly_added"] = True
                        new_table_widgets.append(w)
                else:
                    logger.warning("[IncrementalBuilder] ⚠️ Table '%s' is empty or failed to sample", new_table)
            logger.info(
                "[IncrementalBuilder] ✅ PHASE 1 COMPLETE | Fast Pandas engine generated %d total widgets",
                len(new_table_widgets)
            )
        except Exception as e:
            logger.error(
                "[IncrementalBuilder] ❌ PHASE 1 FAILED | Fast Pandas engine error: %s\nContinuing with empty Phase 1...",
                e
            )

        # ── Phase 2: INFER RELATIONSHIPS VIA LLM (Slow) ──
        infer_prompt = f"""You are a Database Architect analyzing a delta database schema update.
        
FULL SCHEMA:
{schema_text}

EXISTING RELATIONSHIPS:
{rel_text}

NEWLY ADDED TABLES: {", ".join(list_of_new_tables)}

YOUR TASK:
Look at the column names in the NEWLY ADDED TABLES and infer any foreign key relationships they might have with EACH OTHER or with the EXISTING tables.
For example: if a new table 'reviews' has 'product_id', and an existing table is 'products' with 'id', that's a FK.

Return a JSON array of ONLY the NEW relationships you infer. DO NOT include existing relationships.
[
  {{"source_table": "reviews", "source_column": "product_id", "target_table": "products", "target_column": "id", "type": "foreign_key"}}
]

Return ONLY the JSON array, no markdown."""

        try:
            from app.core.llm import invoke_llm_with_retry
            raw = invoke_llm_with_retry(self.llm, infer_prompt, max_retries=1, context_name="Incremental Relationship Inference")
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            inferred = json.loads(raw)
            if isinstance(inferred, list) and inferred:
                # Append to our local list for Phase 3
                relationships.extend(inferred)
                # Save to database
                with self.db.get_connection() as conn:
                    with conn.cursor() as cur:
                        for rel in inferred:
                            rel_id = f"rel-{uuid.uuid4().hex[:12]}"
                            try:
                                cur.execute(
                                    """INSERT INTO etl_system.workspace_relationships
                                           (relationship_id, workspace_id, source_table, source_column,
                                            target_table, target_column, relationship_type, inferred_by)
                                       VALUES (%s, %s, %s, %s, %s, %s, %s, 'llm')
                                       ON CONFLICT DO NOTHING""",
                                    (rel_id, self.workspace_id, rel.get("source_table"), rel.get("source_column"),
                                     rel.get("target_table"), rel.get("target_column"), rel.get("type", "foreign_key")),
                                )
                            except Exception:
                                pass
                    conn.commit()
                logger.info("[IncrementalBuilder] LLM inferred and saved %d NEW relationships", len(inferred))
        except Exception as e:
            logger.warning("[IncrementalBuilder] Relationship inference failed: %s", e)

        # Re-build rel_text with all relationships (including newly inferred)
        rel_lines = ["=== RELATIONSHIPS ==="]
        if relationships:
            for rel in relationships:
                src = f"{rel.get('source_table', '?')}.{rel.get('source_column', '?')}"
                tgt = f"{rel.get('target_table', '?')}.{rel.get('target_column', '?')}"
                rel_lines.append(f"  - {src} -> {tgt}")
        else:
            rel_lines.append("  (No relationships defined)")
        rel_text = "\n".join(rel_lines)
        
        prompt_context_text = f"{schema_text}\n\n{rel_text}\n\n=== NEWLY ADDED TABLES ===\n" + ", ".join(list_of_new_tables)
        if user_hints:
            prompt_context_text += f"\n\n=== USER HINTS ===\n{user_hints}"

        # ── Phase 3: Instruct the LLM to ONLY focus on CROSS-TABLE insights ──
        system_prompt = """You are an elite Data Engineer and BI Analyst.
You are updating an existing dashboard with newly uploaded tables.
We have ALREADY generated basic single-table widgets for the new tables.

RULES:
1. Generate highly valuable PostgreSQL dashboard widgets that focus STRICTLY on CROSS-TABLE JOINs between the NEW tables and the EXISTING tables.
2. Do NOT generate simple single-table widgets. Only generate cross-table insights.
3. Focus entirely on the NEW tables and their relationships. Do not generate widgets that only query the existing tables.
4. If NO relationships are defined, you MUST analyze the TABLE-COLUMN MAP to infer primary and foreign keys yourself (e.g., matching 'customer_id' across tables) and use them in JOINs.
5. Generate valid PostgreSQL SELECT queries. Use aggregations (SUM, COUNT, AVG) and GROUP BY.
6. Do NOT use schema prefixes — tables are in the search_path.
7. CRITICAL: ONLY query tables that are EXPLICITLY listed in the TABLE-COLUMN MAP above. Do NOT assume the existence of any other tables.
8. Return ONLY the JSON array, no markdown code blocks.

Return a JSON array of widgets:
[
  {
    "title": "Clear Business Title (Cross-Table)",
    "type": "chart",
    "chartType": "bar",
    "sql_query": "",
    "gridW": 6,
    "gridH": 3
  }
]"""
        
        user_prompt = f"Here is the database state and delta:\n{prompt_context_text}"

        try:
            # 3. Call LLM
            from app.core.llm import invoke_llm_with_retry, create_workspace_llm
            combined_prompt = f"{system_prompt}\n\n{user_prompt}"
            logger.info("[IncrementalBuilder] Prompt context length: %d chars", len(user_prompt))
            logger.info("[IncrementalBuilder] Prompt Context:\n%s", prompt_context_text)
            
            # Allow Ollama VRAM to flush and explicitly use a fresh connection 
            # to prevent [WinError 10054] connection resets on consecutive heavy requests.
            logger.info("[IncrementalBuilder] 🧠 Preparing LLM for PHASE 3: Cross-table widget generation...")
            time.sleep(2.0)
            fresh_llm, _ = create_workspace_llm()
            
            logger.info(
                "[IncrementalBuilder] 📡 Invoking LLM for CROSS-TABLE WIDGET DESIGN\n"
                "New Tables: %s | Existing Relationships: %d | Existing Widgets: %d",
                list_of_new_tables, len(relationships), len(existing_widgets)
            )
            
            cleaned = invoke_llm_with_retry(
                fresh_llm,
                combined_prompt,
                context_name="Workspace Incremental Builder - Phase 3"
            )
            
            logger.info("[IncrementalBuilder] 📥 LLM Response received (length=%d chars)\nRaw Output:\n%s", len(cleaned), cleaned)
            
            if cleaned.startswith("```json"):
                cleaned = cleaned.split("```json")[1].split("```")[0].strip()
            elif cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1].split("```")[0].strip()
                
            logger.info("[IncrementalBuilder] 🔍 Parsing LLM JSON response...")
            delta_plan = json.loads(cleaned)
            
            if isinstance(delta_plan, list):
                new_widgets = delta_plan
            else:
                new_widgets = delta_plan.get("new_widgets", [])
                
            remove_widgets = [] # Removed widget removal logic as per user request
                
            logger.info(
                "[IncrementalBuilder] ✅ LLM PHASE 3 DESIGN COMPLETE | Generated %d cross-table widgets\n"
                "Processing individual widget SQL execution and validation...",
                len(new_widgets)
            )
            for idx, w in enumerate(new_widgets, 1):
                logger.info(
                    "[IncrementalBuilder] Widget #%d: '%s' (type=%s, chart_type=%s)\nSQL: %s",
                    idx, w.get("title"), w.get("type"), w.get("chartType"), w.get("sql_query", "None")
                )

            # Assign unique IDs, execute SQL, cache data, and tag as newly added
            logger.info("[IncrementalBuilder] 🚀 EXECUTING SQL for %d LLM-generated widgets...", len(new_widgets))
            with self.connection_scope():
                for idx, w in enumerate(new_widgets, 1):
                    w["id"] = f"ws-sql-{uuid.uuid4().hex[:8]}"
                    w["is_newly_added"] = True
                    w["source_table"] = "_multi_table"
                    if "gridW" not in w:
                        w["gridW"] = 6 if w.get("type") == "chart" else 3
                    if "gridH" not in w:
                        w["gridH"] = 3 if w.get("type") in ("chart", "list") else 2

                    # Execute and retry SQL if failed
                    if w.get("sql_query"):
                        logger.info("[IncrementalBuilder] 🔄 Executing widget %d/%d: '%s'...", idx, len(new_widgets), w.get("title"))
                        w = self._execute_and_retry_widget_sql(w, context_text=prompt_context_text, builder_name="IncrementalBuilder")
                        if w.get("_sql_error"):
                            logger.error("[IncrementalBuilder] ❌ Widget %d execution failed: %s", idx, w.get("_sql_error"))
                        else:
                            logger.info("[IncrementalBuilder] ✅ Widget %d executed successfully", idx)

            elapsed = round((time.perf_counter() - t0) * 1000, 1)
            logger.info(
                "[WorkspaceIncrementalBuilder] ✅ PHASE 3 COMPLETE: %d new cross-table widgets, %d removed in %dms",
                len(new_widgets), len(remove_widgets), elapsed
            )

            # Merge LLM cross-table widgets with fast Pandas widgets
            new_widgets.extend(new_table_widgets)
            
            total_elapsed = round((time.perf_counter() - t0) * 1000, 1)
            logger.info(
                "[WorkspaceIncrementalBuilder] 🎉 BUILD COMPLETE | Total %d widgets generated in %dms\n"
                "  • Phase 1 (Fast Pandas): %d widgets\n"
                "  • Phase 3 (LLM Cross-table): %d widgets\n"
                "  • Removed: %d widgets\n"
                "Status: SUCCESS",
                len(new_widgets), total_elapsed, len(new_table_widgets), len(new_widgets) - len(new_table_widgets), len(remove_widgets)
            )

            return {
                "status": "success",
                "new_widgets": new_widgets,
                "remove_widgets": remove_widgets
            }

        except Exception as e:
            logger.error(
                "[WorkspaceIncrementalBuilder] ❌ PHASE 3 FAILED (LLM cross-table generation)\n"
                "Error: %s\n"
                "Falling back to PHASE 1 results only (fast Pandas widgets: %d)",
                e, len(new_table_widgets)
            )

        # Even if LLM phase failed, return fast Pandas widgets so the dashboard is not empty
        if new_table_widgets:
            total_elapsed = round((time.perf_counter() - t0) * 1000, 1)
            logger.info(
                "[WorkspaceIncrementalBuilder] ⚠️ BUILD PARTIAL COMPLETION (Phase 1 only)\n"
                "Total %d widgets generated in %dms\n"
                "  • Phase 1 (Fast Pandas): %d widgets ✅\n"
                "  • Phase 3 (LLM Cross-table): 0 widgets ❌\n"
                "Status: PARTIAL SUCCESS (Phase 3 will be queued for retry)",
                len(new_table_widgets), total_elapsed, len(new_table_widgets)
            )
            return {
                "status": "success",
                "new_widgets": new_table_widgets,
                "remove_widgets": [],
            }

        logger.error(
            "[WorkspaceIncrementalBuilder] ❌ BUILD COMPLETE FAILURE\n"
            "No widgets generated from Phase 1 or Phase 3. Dashboard remains empty."
        )
        return {"status": "error", "new_widgets": [], "remove_widgets": [], "error": "No widgets generated"}
