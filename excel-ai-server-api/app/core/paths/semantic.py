"""
Semantic path mixin for HybridAgent.

Extracted from agent.py — handles PGVector hybrid retrieval
(vector search + keyword search) and LLM-based semantic analysis.
"""
from __future__ import annotations

import json

import pandas as pd

from app.utils.logging import logger, log_full_exception
from app.core.llm import invoke_llm_with_retry
from app.config import observe, langfuse_context


class SemanticPathMixin:
    """Mixin providing semantic search, vector/keyword retrieval, and search term extraction."""

    @observe(name="llm.extract_search_terms")
    def _extract_search_terms(self, query):
        """Extracts exact names/IDs from the query using the LLM."""
        try:
            prompt = f"""
            Extract specific entities (names, IDs, unique codes) from this query.
            Query: "{query}"
            Return ONLY the entities separated by commas. If none, return NO_ENTITIES.
            Example: "Compare John and ID-99" -> "John, ID-99"
            """
            langfuse_context.update_current_observation(
                input={"query": query, "prompt": prompt.strip()},
                tags=["entity-extraction"],
            )
            try:
                try:
                    lf_cb = langfuse_context.get_current_langchain_handler()
                    _ste_cbs = [lf_cb] if lf_cb else None
                except Exception:
                    _ste_cbs = None
                response = invoke_llm_with_retry(
                    self.llm, prompt, max_retries=2, context_name="Search term extraction",
                    callbacks=_ste_cbs,
                )
            except Exception:
                logger.warning("⚠️ Search term extraction failed, defaulting to no entities")
                langfuse_context.update_current_observation(output={"entities": [], "fallback": True})
                return []

            if "NO_ENTITIES" in response:
                langfuse_context.update_current_observation(output={"entities": []})
                return []
            terms = [t.strip() for t in response.split(',') if t.strip()]
            langfuse_context.update_current_observation(output={"entities": terms})
            return terms
        except:
            return []

    # ========================================================================
    # SEMANTIC PATH — PGVector helpers exposed as observable child spans
    # ========================================================================
    @observe(name="pgvector.vector_search")
    def _pgvector_vector_search(self, query_vec: list, cols_select: str) -> "pd.DataFrame":
        """KNN vector search against PGVector. Child span records latency + row count."""
        with self.db.get_connection() as conn:
            df = pd.read_sql(
                f"""
                SELECT {cols_select} FROM {self.table_name}
                ORDER BY row_embedding <=> %s::vector
                LIMIT 10
                """,
                conn,
                params=(query_vec,),
            )
        langfuse_context.update_current_observation(
            output={
                "rows_retrieved": len(df),
                "table": self.table_name,
            },
            metadata={"file_uuid": self.file_uuid},
            tags=["pgvector", "vector-search", "semantic-search"],
        )
        return df

    @observe(name="pgvector.keyword_search")
    def _pgvector_keyword_search(self, search_terms: list, cols: list, cols_select: str) -> "pd.DataFrame":
        """ILIKE keyword search against PGVector table. Child span records latency + row count."""
        where_clauses, params = [], []
        for term in search_terms:
            col_likes = [f"{col}::text ILIKE %s" for col in cols]
            where_clauses.append(f"({' OR '.join(col_likes)})")
            params.extend([f"%{term}%"] * len(cols))

        full_where = " OR ".join(where_clauses)

        with self.db.get_connection() as conn:
            df = pd.read_sql(
                f"SELECT {cols_select} FROM {self.table_name} WHERE {full_where} LIMIT 10",
                conn,
                params=tuple(params),
            )
        langfuse_context.update_current_observation(
            output={
                "rows_retrieved": len(df),
                "search_terms": search_terms,
                "table": self.table_name,
            },
            metadata={"file_uuid": self.file_uuid},
            tags=["pgvector", "keyword-search", "semantic-search"],
        )
        return df

    @observe(as_type="span", name="Semantic Path")
    def run_semantic_path(self, query):
        langfuse_context.update_current_observation(
            input={"query": query},
            metadata={"file_uuid": self.file_uuid, "filename": self.filename},
            tags=["semantic-path", "semantic-search"],
        )
        try:
            logger.info(f"🔍 SEMANTIC PATH (HYBRID): {query}")
            
            # 1. Vector Search (Semantic) — child span via helper
            query_vec = self.embed_model.embed_query(query)
            cols = [f'"{c}"' for c in self.columns]
            cols_select = ", ".join(cols)

            df_vector = self._pgvector_vector_search(query_vec, cols_select)

            # 2. Keyword Search (Exact Match) — child span via helper
            df_keyword = pd.DataFrame()
            search_terms = self._extract_search_terms(query)
            
            if search_terms:
                logger.info(f"🔎 Detected Exact Terms: {search_terms}")
                df_keyword = self._pgvector_keyword_search(search_terms, cols, cols_select)

            # 3. Merge & Deduplicate
            if not df_keyword.empty:
                df_combined = pd.concat([df_vector, df_keyword])
                # Deduplicate based on all columns (converting to tuple to handle hashability)
                df_combined = df_combined.loc[df_combined.astype(str).drop_duplicates().index]
            else:
                df_combined = df_vector

            if df_combined.empty:
                _no_results_msg = "I searched the database but found no relevant text records matching your query."
                self._trace_path_output(
                    path_name="Semantic Path",
                    query=query,
                    output_value=_no_results_msg,
                    exit_point="no_results",
                )
                return _no_results_msg

            # 4. Generate Answer
            # Format dates and percentages for readability
            df_for_context = self._format_dataframe_for_display(df_combined.head(20))
            context = df_for_context.to_json(orient='records', indent=2)

            # Surface retrieved chunks in the span so they appear in Langfuse.
            langfuse_context.update_current_observation(
                metadata={
                    "file_uuid": self.file_uuid,
                    "vector_rows": len(df_vector),
                    "keyword_rows": len(df_keyword),
                    "combined_rows": len(df_combined),
                    "search_terms": search_terms,
                },
            )

            prompt = f"""
            You are a Senior Data Investigator. 
            Your goal is to answer the user's query using strictly the retrieved database records below.

            ### CONTEXT:
            **User Query:** "{query}"
            **Retrieved Records (Evidence):** {context}

            ### INSTRUCTIONS:
            1. **Analyze the Evidence**: Look at the retrieved records. Do they answer the question directly? Do they contain conflicting info?
            2. **Synthesize the Answer**:
               - **Direct Answer**: Start with a clear, direct summary of what was found.
               - **The Proof**: Present the relevant details from the records.
                 - **CRITICAL**: If the user asks to COMPARE items, you **MUST** use a Markdown Table.
                 - If listing specific details, use clean bullet points with **bold keys**.
               - **Analyst Insight**: If you spot a trend (e.g., "Notice that all high-value transactions occurred in Q4"), highlight it.

            ### STRICT RULES:
            - Answer **ONLY** using the Retrieved Records. Do not invent info.
            - If the records don't fully answer the query, state clearly what is missing.
            - Do NOT describe the data structure (e.g., never say "The JSON object has a field..."). Talk about the data itself.
            - Use **Bold** for key entities (Names, IDs, Dates, Money).

            ### RESPONSE FORMAT:
            
            **🔍 Search Findings**
            [Direct summary answer]

            **📄 Detailed Evidence**
            [Markdown Table or Bulleted List of the records]

            **💡 Analyst Insights**
            [Any patterns, anomalies, or comparisons found in these specific records]
            """

            # Log the prompt with full context so developers see exactly what evidence was passed.
            langfuse_context.update_current_observation(
                input={
                    "query": query,
                    "prompt": prompt.strip(),
                    "retrieved_rows": {
                        "vector": len(df_vector),
                        "keyword": len(df_keyword),
                        "combined": len(df_combined),
                    },
                },
            )

            try:
                try:
                    lf_cb = langfuse_context.get_current_langchain_handler()
                    callbacks = [lf_cb] if lf_cb else None
                except Exception:
                    callbacks = None
                response = invoke_llm_with_retry(
                    self.llm, prompt, max_retries=2,
                    context_name="Semantic analysis", callbacks=callbacks,
                )
                self._trace_path_output(
                    path_name="Semantic Path",
                    query=query,
                    output_value=response or "",
                    exit_point="semantic_response",
                    extra={"response_preview": (response or "")[:300]},
                )
            except Exception as e:
                logger.error("Semantic LLM call failed after retries")
                _err_msg = "I couldn't complete the semantic search due to a service error. Please try again later."
                self._trace_path_output(
                    path_name="Semantic Path",
                    query=query,
                    output_value=_err_msg,
                    exit_point="semantic_llm_error",
                    status="error",
                    extra={"error": str(e)[:200]},
                )
                return _err_msg
            
            return response
            
        except Exception as e:
            log_full_exception(e, "Semantic path error")
            _err_msg = "I couldn't complete the semantic search due to an internal error. Please try again later."
            self._trace_path_output(
                path_name="Semantic Path",
                query=query,
                output_value=_err_msg,
                exit_point="semantic_path_error",
                status="error",
                extra={"error": str(e)[:200]},
            )
            return _err_msg
