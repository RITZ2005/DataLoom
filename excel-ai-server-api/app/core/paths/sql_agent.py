"""
SQL Agent path mixin for HybridAgent.

When the active data source is an ETL-loaded database (not a file upload),
queries are routed to a LangChain SQL Agent that queries PostgreSQL directly
via a read-only database role, instead of the standard Pandas agent.
"""
from __future__ import annotations

import os
import logging
import re
from typing import Any, Dict, List, Optional

from app.utils.logging import logger, log_full_exception
from app.core.llm import invoke_llm_with_retry
from app.config import observe, langfuse_context
from app.core.schema_utils import split_qualified_table_name

# Optional imports — only needed when SQL agent is actually used
try:
    from langchain_community.agent_toolkits import SQLDatabaseToolkit
    from langchain_community.utilities import SQLDatabase
    from langchain_community.agent_toolkits.sql.base import create_sql_agent
    _SQL_AGENT_AVAILABLE = True
except ImportError:
    _SQL_AGENT_AVAILABLE = False

try:
    from sqlalchemy import create_engine
    _SQLALCHEMY_AVAILABLE = True
except ImportError:
    _SQLALCHEMY_AVAILABLE = False


class SqlAgentPathMixin:
    """
    Mixin providing LangChain SQL Agent execution path for ETL-loaded data.

    Instead of running pandas code on in-memory DataFrames, this path sends
    natural language queries to a LangChain SQL Agent that generates and
    executes SQL against the internal PostgreSQL database using a read-only
    database role for security.

    The SQL Agent only has access to the specific tables loaded by the ETL
    pipeline, not system tables or other users' data.
    """

    def _init_sql_agent(self, table_names: List[str]) -> None:
        """
        Initialize the LangChain SQL Agent for the given ETL tables.

        Parameters
        ----------
        table_names : list[str]
            Names of the PostgreSQL tables to expose to the SQL agent.
            Only these tables will be queryable.
        """
        if not _SQL_AGENT_AVAILABLE:
            raise ImportError(
                "langchain-community is required for the SQL Agent. "
                "Install with: pip install langchain-community"
            )
        if not _SQLALCHEMY_AVAILABLE:
            raise ImportError(
                "sqlalchemy is required for the SQL Agent. "
                "Install with: pip install sqlalchemy"
            )

        # Build read-only connection URI
        readonly_user = os.getenv("ETL_READONLY_USER", "ai_readonly")
        readonly_password = os.getenv("ETL_READONLY_PASSWORD", "readonly_pass")
        pg_host = os.getenv("PG_HOST", "localhost")
        pg_port = os.getenv("PG_PORT", "5432")
        pg_database = os.getenv("PG_DATABASE", "hybrid")

        readonly_uri = (
            f"postgresql+psycopg2://{readonly_user}:{readonly_password}"
            f"@{pg_host}:{pg_port}/{pg_database}"
        )

        logger.info(
            "[SqlAgent] Initializing SQL agent with %d table(s): %s",
            len(table_names),
            table_names,
        )

        # Clean table names and extract schema
        # (e.g., '"db_etl_test_db"."etl_4_board"' → schema: 'db_etl_test_db', table: 'etl_4_board')
        cleaned_tables = []
        schemas = set()
        
        for name in table_names:
            schema_name, table_name = split_qualified_table_name(name)
            if schema_name and table_name:
                schemas.add(schema_name)
                cleaned_tables.append(table_name)
            else:
                cleaned_tables.append((name or "").strip('"').strip("'"))
        
        target_schema = list(schemas)[0] if schemas else None

        engine_args = {}
        if target_schema:
            engine_args["connect_args"] = {"options": f"-c search_path={target_schema},public"}

        self._sql_db = SQLDatabase.from_uri(
            readonly_uri,
            schema=target_schema,
            include_tables=cleaned_tables,
            sample_rows_in_table_info=3,  # Show 3 sample rows in schema info
            engine_args=engine_args,
        )

        # Create toolkit and agent
        self._sql_toolkit = SQLDatabaseToolkit(db=self._sql_db, llm=self.llm)

        custom_prefix = """You are an agent designed to interact with a SQL database.
Given an input question, create a syntactically correct PostgreSQL query to run, then look at the results of the query and return the answer.
Unless the user specifies a specific number of examples they wish to obtain, always limit your query to at most 10 results.
You can order the results by a relevant column to return the most interesting examples in the database.
Never query for all the columns from a specific table, only ask for the relevant columns given the question.
You have access to tools for interacting with the database.
Only use the given tools. Only use the information returned by the tools to construct your final answer.
You MUST double check your query before executing it. If you get an error while executing a query, rewrite the query and try again.

IMPORTANT RULES:
1. When writing SQL queries, you MUST ALWAYS use the FULLY QUALIFIED table name including the schema, exactly as it appears in the schema definitions.
2. For example, if the schema tool shows the table as `my_schema.my_table`, you MUST write `FROM my_schema.my_table` in your query, NOT `FROM my_table`.
3. Do not assume tables exist in the `public` schema.
"""

        self._sql_agent = create_sql_agent(
            llm=self.llm,
            toolkit=self._sql_toolkit,
            verbose=True,
            agent_type="zero-shot-react-description",
            handle_parsing_errors=True,
            max_iterations=10,
            prefix=custom_prefix,
        )
        if hasattr(self._sql_agent, "handle_parsing_errors"):
            self._sql_agent.handle_parsing_errors = True

        # Store the table names for reference
        self._sql_table_names = list(table_names)
        self._sql_all_table_names = list(table_names)
        logger.info("[SqlAgent] ✅ SQL Agent initialized successfully")

    def _ensure_sql_agent(self, table_names: Optional[List[str]] = None) -> bool:
        """Ensure SQL agent is available, initializing lazily if needed."""
        if getattr(self, "_sql_agent", None) is not None:
            existing_tables = getattr(self, "_sql_table_names", None)
            if table_names is None or existing_tables == list(table_names):
                return True
            self._sql_agent = None
            self._sql_toolkit = None
            self._sql_db = None

        if table_names is None:
            table_names = getattr(self, "sql_table_names", None)

        if table_names is None:
            table_names = getattr(self, "_sql_all_table_names", None)

        if table_names is None:
            table_names = [getattr(self, "table_name", None)] if getattr(self, "table_name", None) else None

        if not table_names:
            logger.error("[SqlAgent] Cannot initialize SQL agent without table_names")
            return False

        try:
            self._init_sql_agent(table_names)
            return True
        except Exception as e:
            log_full_exception(e, "Failed to initialize SQL agent")
            return False

    def _normalize_table_name_tokens(self, table_name: str) -> set[str]:
        tokens = re.split(r"[^a-zA-Z0-9]+", table_name.lower())
        return {token for token in tokens if len(token) > 2}

    def _select_sql_tables_for_query(self, query: str, table_names: Optional[List[str]] = None, max_tables: int = 8) -> List[str]:
        """Pick a small relevant table subset so full-db chat does not load every schema into the prompt.
        
        Strategy:
        1. If ≤ max_tables, use all of them.
        2. Fast path: token overlap + recency boost (no LLM call).
        3. If fast path yields < 2 results AND there are many tables, use LLM semantic routing.
        """
        available_tables = [name for name in (table_names or getattr(self, "sql_table_names", None) or []) if name]
        if not available_tables:
            return []

        if len(available_tables) <= max_tables:
            self._recent_sql_tables = list(available_tables)
            return available_tables

        # ── Fast path: token-based matching ──
        query_tokens = self._normalize_table_name_tokens(query)
        recent_tables = [name for name in getattr(self, "_recent_sql_tables", []) if name in available_tables]
        scored_tables: list[tuple[int, int, str]] = []

        for index, table_name in enumerate(available_tables):
            table_tokens = self._normalize_table_name_tokens(table_name)
            overlap = len(query_tokens & table_tokens)
            recent_boost = 1 if table_name in recent_tables else 0
            scored_tables.append((overlap, recent_boost, table_name))

        scored_tables.sort(key=lambda x: (x[0], x[1]), reverse=True)
        token_selected = [item[2] for item in scored_tables if item[0] > 0][:max_tables]

        # Add recent tables to fill gaps
        if len(token_selected) < max_tables:
            for table_name in recent_tables:
                if table_name not in token_selected:
                    token_selected.append(table_name)
                if len(token_selected) >= max_tables:
                    break

        # If token matching found enough results, skip the LLM call
        if len(token_selected) >= 2:
            self._recent_sql_tables = list(token_selected)
            return token_selected

        # ── LLM semantic routing (only when token matching fails) ──
        try:
            prompt = f"""You are an expert data analyst. Select the most relevant database tables to answer this query.

User Query: {query}
Available Tables: {', '.join(available_tables)}

Select up to {max_tables} tables most relevant to answering this query.
Return ONLY a comma-separated list of exact table names. No explanation."""

            response = invoke_llm_with_retry(
                self.llm, prompt, max_retries=1, context_name="SQL table routing"
            )

            llm_selected = []
            if response:
                tokens = [t.strip(' "\'') for t in response.replace(',', ' ').split() if t.strip(' "\'')]
                for token in tokens:
                    if token in available_tables and token not in llm_selected:
                        llm_selected.append(token)

            if llm_selected:
                self._recent_sql_tables = list(llm_selected)
                logger.info("[SqlAgent] LLM semantic routing selected: %s", llm_selected)
                return llm_selected
        except Exception as e:
            logger.warning("[SqlAgent] LLM table routing failed, using fallback: %s", str(e)[:200])

        # Fallback: use whatever token matching found, or first N tables
        selected = token_selected if token_selected else available_tables[:max_tables]
        self._recent_sql_tables = list(selected)
        return selected

    @observe(as_type="span", name="SQL Agent Path")
    def run_sql_agent_path(self, query: str, table_names: Optional[List[str]] = None) -> str:
        """
        Execute a natural language query via the LangChain SQL Agent.

        The agent generates SQL queries, executes them against the read-only
        PostgreSQL connection, and synthesizes a human-readable answer.

        Parameters
        ----------
        query : str
            Natural language question from the user.
        table_names : list[str], optional
            Names of tables to expose. Required on first call.

        Returns
        -------
        str
            The agent's synthesized answer.
        """
        accessible_tables = table_names or getattr(self, "sql_table_names", None) or [getattr(self, "table_name", None)]
        selected_tables = self._select_sql_tables_for_query(query, accessible_tables)

        langfuse_context.update_current_observation(
            input={"query": query, "table_names": accessible_tables, "selected_tables": selected_tables},
            metadata={
                "file_uuid": getattr(self, "file_uuid", None),
                "filename": getattr(self, "filename", None),
            },
            tags=["sql-agent-path"],
        )

        # Ensure agent is initialized
        if not self._ensure_sql_agent(selected_tables):
            _err_msg = (
                "SQL Agent is not available. This could be because:\n"
                "1. Required packages (langchain-community, sqlalchemy) are not installed\n"
                "2. The read-only database role is not configured\n"
                "Please contact the administrator."
            )
            self._trace_path_output(
                path_name="SQL Agent Path",
                query=query,
                output_value=_err_msg,
                exit_point="sql_agent_unavailable",
                status="error",
            )
            return _err_msg

        # Execute with retry
        max_retries = 2
        last_error = ""

        for attempt in range(max_retries + 1):
            try:
                logger.info(
                    "[SqlAgent] SQL AGENT PATH (Attempt %d): %s",
                    attempt + 1, query,
                )

                current_query = query
                if last_error:
                    current_query = (
                        f"User Query: {query}\n\n"
                        f"PREVIOUS ATTEMPT FAILED: {last_error}\n"
                        f"Try a different SQL approach."
                    )

                # Compose callbacks
                try:
                    lf_cb = langfuse_context.get_current_langchain_handler()
                    callbacks = [lf_cb] if lf_cb else None
                except Exception:
                    callbacks = None

                response = self._sql_agent.invoke(
                    {"input": current_query},
                    config={"callbacks": callbacks} if callbacks else {},
                )

                raw_answer = response.get("output", str(response))

                # Validate the response
                if not raw_answer or raw_answer.strip() == "":
                    last_error = "SQL agent returned empty response"
                    logger.warning("[SqlAgent] Empty response on attempt %d", attempt + 1)
                    continue

                logger.info(
                    "[SqlAgent] ✅ SQL Agent response (%d chars)",
                    len(raw_answer),
                )

                # Humanize the response if the method is available
                if hasattr(self, "_humanize_response"):
                    humanized = self._humanize_response(query, raw_answer, [])
                    self._trace_path_output(
                        path_name="SQL Agent Path",
                        query=query,
                        output_value=humanized,
                        exit_point="humanized_response",
                    )
                    return humanized
                else:
                    self._trace_path_output(
                        path_name="SQL Agent Path",
                        query=query,
                        output_value=raw_answer,
                        exit_point="raw_response",
                    )
                    return raw_answer

            except Exception as e:
                last_error = str(e)
                log_full_exception(e, f"SQL Agent error (Attempt {attempt + 1})")

        _fail_msg = (
            "I tried to query the database multiple times but couldn't generate "
            "a valid answer. Please try rephrasing your question."
        )
        self._trace_path_output(
            path_name="SQL Agent Path",
            query=query,
            output_value=_fail_msg,
            exit_point="exhausted_retries",
            status="error",
        )
        return _fail_msg
