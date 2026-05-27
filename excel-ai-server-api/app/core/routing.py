"""
Query routing mixin for HybridAgent.

Extracted from agent.py — handles intent detection, query normalization,
and semantic cache operations (check, save, delete).
"""
from __future__ import annotations

import time
import datetime as dt
from typing import Any, Dict, Optional

import requests

from app.utils.logging import logger, log_full_exception
from app.core.llm import invoke_llm_with_retry, strip_markdown_fences
from app.config import observe, langfuse_context


class RoutingMixin:
    """Mixin providing query routing, intent detection, and cache operations."""

    def _sanitize_canonical_query(self, canonical_query: str) -> str:
        """Normalize LLM output so cache lookup and save use the same canonical text."""
        text = strip_markdown_fences(canonical_query or "").strip()
        if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
            text = text[1:-1].strip()
        return text or (canonical_query or "").strip()

    # --- ADD THIS NEW HELPER METHOD ---
    @observe(name="llm.query_normalization")
    def _normalize_query_with_llm(self, query: str) -> str:
        """
        Universal normalizer that standardizes queries for any dataset.
        Handles typos, relative dates, and standard analytics terms.
        Called ONCE in check_cache(); save_to_cache() reuses the result.
        """
        try:
            # Get current context for the LLM
            today = dt.date.today().strftime("%d %B %Y")
            
            prompt = f"""
            Rewrite this data query into standard, professional English.
           
            RULES:
            1. Fix typos and use standard terms ('avg' -> 'average').
            2. RESOLVE RELATIVE DATES: If the user says "last month" and today is {today}, rewrite it as the specific month name.
               Example: "Sales last month" -> "Sales in [Previous Month Name]".
            3. Output ONLY the rewritten query.
           
            Query: "{query}"
            Rewritten:
            """

            # Record the full prompt so developers can inspect it in Langfuse.
            langfuse_context.update_current_observation(
                input={"query": query, "prompt": prompt.strip()},
                metadata={"file_uuid": self.file_uuid},
            )
            
            try:
                try:
                    lf_cb = langfuse_context.get_current_langchain_handler()
                    _norm_cbs = [lf_cb] if lf_cb else None
                except Exception:
                    _norm_cbs = None
                canonical = invoke_llm_with_retry(
                    self.llm, prompt, max_retries=2, context_name="Query normalization",
                    callbacks=_norm_cbs,
                )
            except Exception:
                logger.warning("⚠️ LLM normalization failed, using original query")
                langfuse_context.update_current_observation(output={"normalized_query": query, "fallback": True})
                return query

            result = self._sanitize_canonical_query(canonical if canonical and len(canonical) > 2 else query)
            self._last_normalized_query = result
            self._last_normalized_query_source = query
            langfuse_context.update_current_observation(output={"normalized_query": result})
            return result
        except Exception as e:
            log_full_exception(e, "LLM Normalization failed")
            self._last_normalized_query = query
            self._last_normalized_query_source = query
            return query

    # ========================================================================
    # ROUTER & EXECUTION
    # ========================================================================
    @observe(name="redis.semantic_cache.check")
    def check_cache(self, query: str) -> Optional[Dict[str, Any]]:
        started_at = time.time()
        cache_trace: Dict[str, Any] = {
            "file_uuid": self.file_uuid,
            "query_preview": (query or "")[:300],
            "strict_threshold": self.semantic_cache_threshold,
            "loose_threshold": 0.4,
            "status": "started",
        }

        def _finalize_cache_trace(**kwargs: Any) -> None:
            cache_trace.update(kwargs)
            cache_trace["duration_ms"] = round((time.time() - started_at) * 1000, 2)
            self.last_cache_trace = dict(cache_trace)

        # Log the span input so we can inspect every cache lookup in Langfuse.
        langfuse_context.update_current_observation(
            input={"query": query, "file_uuid": self.file_uuid},
            metadata={
                "strict_threshold": self.semantic_cache_threshold,
                "loose_threshold": 0.4,
            },
        )
        # 1. LLM Normalization (called once; result stored for save_to_cache)
        normalized_query = self._normalize_query_with_llm(query)
        self._last_normalized_query = normalized_query
        self._last_normalized_query_source = query
        cache_trace["normalized_query_preview"] = (normalized_query or "")[:300]
        logger.info(f"🔍 Cache lookup: '{query}' → canonical: '{normalized_query}'")
        
        try:
            query_embedding = self.embed_model.embed_query(normalized_query)
            cache_trace["embedding_dim_actual"] = len(query_embedding)
            cache_trace["embedding_dim_expected"] = self.embedding_dim
        except Exception as e:
            # If embedding service/network is unreachable, treat as cache miss (no need for full traceback)
            err_str = str(e).lower()
            is_network = isinstance(e, requests.exceptions.RequestException) or any(k in err_str for k in ("timed out", "failed to establish", "unreachable", "max retries exceeded", "10051", "10060"))
            if is_network:
                logger.warning(f"⚠️ Embedding service unreachable - skipping semantic cache (Reason: {err_str[:150]})")
                _finalize_cache_trace(
                    status="miss",
                    decision="embedding_network_error",
                    cache_hit=False,
                    error=str(e)[:200],
                )
                langfuse_context.update_current_observation(
                    output=self.last_cache_trace,
                    tags=["cache-miss", "cache-embedding-error"],
                )
                return None
            # Non-network unexpected error: log full details for developer investigation, then skip cache
            log_full_exception(e, "Embedding error during cache lookup")
            _finalize_cache_trace(
                status="miss",
                decision="embedding_error",
                cache_hit=False,
                error=str(e)[:200],
            )
            langfuse_context.update_current_observation(
                output=self.last_cache_trace,
                tags=["cache-miss", "cache-error"],
            )
            return None

        if len(query_embedding) != self.embedding_dim:
            logger.warning("Semantic cache embedding size mismatch; skipping cache lookup")
            _finalize_cache_trace(
                status="miss",
                decision="embedding_dim_mismatch",
                cache_hit=False,
            )
            langfuse_context.update_current_observation(
                output=self.last_cache_trace,
                tags=["cache-miss", "cache-embedding-mismatch"],
            )
            return None

        try:
            # 2. Tiered Cache Strategy (Cache Fix)
            # Use a LOOSER threshold (0.4) to catch "maybe" matches
            loose_threshold = 0.4
            
            result = self.semantic_cache.check_cache(
                self.file_uuid,
                query_embedding,
                similarity_threshold=loose_threshold
            )
            
            if not result:
                _finalize_cache_trace(
                    status="miss",
                    decision="no_candidate_within_loose_threshold",
                    cache_hit=False,
                )
                langfuse_context.update_current_observation(
                    output=self.last_cache_trace,
                    tags=["cache-miss"],
                )
                return None
                
            distance = result.get('distance', 1.0)
            cached_query = result.get('query_text', '')
            cache_trace["candidate"] = {
                "distance": distance,
                "query_type": result.get("query_type"),
                "cached_query_preview": (cached_query or "")[:300],
            }
            
            # TIER 1: Strict Match (High Confidence)
            # Distance below the env-configurable strict threshold → trust immediately.
            strict_threshold = self.semantic_cache_threshold   # env: REDIS_SEMANTIC_CACHE_THRESHOLD (default 0.15)
            if distance < strict_threshold:
                logger.info(f"✅ Cache HIT (Strict): dist={distance:.4f} < {strict_threshold}")
                _finalize_cache_trace(
                    status="hit",
                    decision="strict_threshold",
                    tier="strict",
                    cache_hit=True,
                )
                langfuse_context.update_current_observation(
                    output=self.last_cache_trace,
                    tags=["cache-hit"],
                )
                return result
                
            # TIER 2: Fuzzy Match (Grey Zone)
            # Distance between strict threshold and loose ceiling → LLM verifies.
            elif distance < loose_threshold:
                verification_prompt = f"""
                Act as a Strict Data Query Judge. Determine if Query A and Query B would produce the EXACT SAME output structure and values.
                
                Query A: "{normalized_query}"
                Query B: "{cached_query}"

                ✅ EQUIVALENCE RULES (Override Rejections for these specific cases):
                1. **General Metadata:** "Summary", "Overview", "Describe", "Explain" applied to "File", "Dataset", or "Data" are IDENTICAL.
                   - Example: "Overview of file" == "Summary of data" -> YES.
                   - Example: "Describe dataset" == "File summary" -> YES.
                2. **Dimension : ** Provide the User with the Row and Column Count for the dataset. "How many rows and columns are in the dataset?" == "What is the shape of the data?" -> YES.
                   - Example: "Number of rows and columns" == "Dataset shape" -> YES.
                   - Example: "Dimension == Summary of dataset structure" -> NO
                CRITICAL REJECTION RULES (Respond NO immediately if ANY apply):
                
                1. **Structural Mismatch (THE #1 RULE):**
                   - **Scalar vs List:** "Count/How many" (Single Number) != "List/Show/Get" (Table of Rows).
                   - **Graph vs Data:** "Plot/Chart" != "Show Data/Table".
                   - **Type Mismatch:** "Bar Chart" != "Pie Chart" != "Line Chart"!="Polar chart"!="Doughnut Chart".
                
                2. **Aggregation Logic:**
                   - Different Math: "Average" != "Sum" != "Max" != "Min".
                   - Example: "Total Salary" != "Average Salary" -> NO.
                
                3. **Target Variable (The "What"):**
                   - Measuring different things.
                   - Example: "Show Revenue" != "Show Profit" -> NO.
                   - Example: "List Names" != "List Emails" -> NO.
                
                4. **Filter Scope (The "Who"):**
                   - Different subsets.
                   - Example: "IT Dept" != "Sales Dept".
                   - Example: "Active Users" != "All Users".
                
                5. **Sorting & Limits:**
                   - Direction: "Highest/Top" != "Lowest/Bottom".
                   - Quantity: "Top 5" != "Top 10".
                
                6. **Time Context:**
                   - Relative: "Last Month" != "This Month".
                   - Specific: "2024" != "2025".
                7. **Implicit Counts (CRITICAL FOR PLOTS):** - If a query asks to "Plot [Category]" or is "[Category]-wise" without specifying a metric, assume it means "Count of records by [Category]".
                   - Example: "Plot Gender" == "Count of employees by Gender" -> YES.
                   - Example: "Department wise graph" == "Number of people in Department" -> YES.
                   
                Are they semantically identical? Respond ONLY with YES or NO.
                """
                try:
                    try:
                        lf_cb = langfuse_context.get_current_langchain_handler()
                        _eqv_cbs = [lf_cb] if lf_cb else None
                    except Exception:
                        _eqv_cbs = None
                    verdict_text = invoke_llm_with_retry(
                        self.llm, verification_prompt, max_retries=2,
                        context_name="Query equivalence check",
                        callbacks=_eqv_cbs,
                    )
                except Exception:
                    logger.warning("⚠️ Verification check failed, rejecting cache match")
                    verdict_text = "NO"
                
                if not verdict_text:
                    logger.warning(f"⚠️ LLM verification returned None (dist={distance:.4f}) - treating as cache miss")
                    _finalize_cache_trace(
                        status="miss",
                        decision="llm_verification_empty",
                        cache_hit=False,
                    )
                    langfuse_context.update_current_observation(
                        output=self.last_cache_trace,
                        tags=["cache-miss", "cache-verify-empty"],
                    )
                    return None
                
                verdict = verdict_text.strip().upper()
                cache_trace["verification"] = {
                    "verdict_raw": verdict_text[:120],
                    "verdict_normalized": verdict,
                }
                
                if "YES" in verdict:
                    logger.info(f"✅ Cache HIT (LLM Verified): dist={distance:.4f} | '{normalized_query}' == '{cached_query}'")
                    _finalize_cache_trace(
                        status="hit",
                        decision="llm_verified_equivalent",
                        tier="llm-verified",
                        cache_hit=True,
                    )
                    langfuse_context.update_current_observation(
                        output=self.last_cache_trace,
                        tags=["cache-hit"],
                    )
                    return result
                else:
                    logger.info(f"❌ Cache MISS (LLM Rejected): dist={distance:.4f} | '{normalized_query}' != '{cached_query}'")
                    _finalize_cache_trace(
                        status="miss",
                        decision="llm_rejected",
                        tier="llm-rejected",
                        cache_hit=False,
                    )
                    langfuse_context.update_current_observation(
                        output=self.last_cache_trace,
                        tags=["cache-miss"],
                    )
                    return None
            
            _finalize_cache_trace(
                status="miss",
                decision="above_loose_threshold",
                tier="above-loose-threshold",
                cache_hit=False,
            )
            langfuse_context.update_current_observation(
                output=self.last_cache_trace,
                tags=["cache-miss"],
            )
            return None

        except Exception as e:
            log_full_exception(e, "Semantic cache lookup failed")
            _finalize_cache_trace(
                status="miss",
                decision="lookup_exception",
                cache_hit=False,
                error=str(e)[:200],
            )
            langfuse_context.update_current_observation(
                output=self.last_cache_trace,
                tags=["cache-miss", "cache-error"],
            )
            return None

    @observe(name="redis.semantic_cache.save")
    def save_to_cache(self, query: str, query_type: str, data: Any) -> None:
        started_at = time.time()
        save_trace: Dict[str, Any] = {
            "file_uuid": self.file_uuid,
            "query_preview": (query or "")[:300],
            "query_type": query_type,
            "status": "started",
        }

        # Reuse the lookup canonical form when available to keep read/write cache vectors aligned.
        normalized_query = None
        if getattr(self, "_last_normalized_query_source", None) == query:
            normalized_query = getattr(self, "_last_normalized_query", None)
        if not normalized_query:
            normalized_query = self._normalize_query_with_llm(query)
        normalized_query = self._sanitize_canonical_query(normalized_query)
        self._last_normalized_query = normalized_query
        self._last_normalized_query_source = query
        save_trace["normalized_query_preview"] = (normalized_query or "")[:300]
        logger.info(f"💾 Cache save: '{query}' → canonical: '{normalized_query}'")
        langfuse_context.update_current_observation(
            input={"query": query, "query_type": query_type, "file_uuid": self.file_uuid},
            tags=["cache-save"],
        )
        
        query_embedding = self.embed_model.embed_query(normalized_query)
        save_trace["embedding_dim_actual"] = len(query_embedding)
        save_trace["embedding_dim_expected"] = self.embedding_dim
        if len(query_embedding) != self.embedding_dim:
            logger.warning("Semantic cache embedding size mismatch; skipping cache save")
            save_trace.update(
                {
                    "status": "skipped",
                    "decision": "embedding_dim_mismatch",
                    "saved": False,
                    "duration_ms": round((time.time() - started_at) * 1000, 2),
                }
            )
            self.last_cache_save_trace = dict(save_trace)
            langfuse_context.update_current_observation(
                output=self.last_cache_save_trace,
                tags=["cache-save", "cache-save-skipped"],
            )
            return
        try:
            # Store the normalized text so Tier 2 LLM judge compares canonical vs canonical
            self.semantic_cache.save_to_cache(self.file_uuid, normalized_query, query_type, data, query_embedding)
            save_trace.update(
                {
                    "status": "saved",
                    "decision": "persisted",
                    "saved": True,
                    "ttl_seconds": self.semantic_cache.ttl_seconds,
                    "index_name": self.semantic_cache.index_name,
                    "key_prefix": self.semantic_cache.key_prefix,
                    "duration_ms": round((time.time() - started_at) * 1000, 2),
                }
            )
            self.last_cache_save_trace = dict(save_trace)
            langfuse_context.update_current_observation(
                output=self.last_cache_save_trace,
                tags=["cache-save", "cache-saved"],
            )
        except Exception as e:
            log_full_exception(e, "Semantic cache save failed")
            save_trace.update(
                {
                    "status": "error",
                    "decision": "save_exception",
                    "saved": False,
                    "error": str(e)[:200],
                    "duration_ms": round((time.time() - started_at) * 1000, 2),
                }
            )
            self.last_cache_save_trace = dict(save_trace)
            langfuse_context.update_current_observation(
                output=self.last_cache_save_trace,
                tags=["cache-save", "cache-save-error"],
            )

    def delete_file_cache(self, file_uuid: Optional[str] = None) -> int:
        target_uuid = file_uuid or self.file_uuid
        try:
            return self.semantic_cache.delete_file_cache(target_uuid)
        except Exception as e:
            log_full_exception(e, "Semantic cache delete failed")
            return 0

    @observe(as_type="span", name="Decide Intent")
    def decide_intent(self, query: str) -> str:
        """
        Uses LLM to classify intent — handles typos, abbreviations, and natural language.
        No keyword short-circuit: always lets the LLM decide for maximum accuracy.
        """
        # Input is updated below after prompt is built so the full prompt is captured.
        prompt = f"""
    Act as a Query Router. Classify the user's query into EXACTLY ONE category using this strict decision hierarchy.
    The user may have spelling mistakes, abbreviations, or informal language — interpret their INTENT, not exact words.
    
    1. **PLOT** (Visualization):
       - DOES the query ask to visualize, plot, chart, graph, show trends, map, or show distribution?
       - Examples: "Bar chart of gender", "Plot salary trends", "Visualize the data", "Show me a graph", "pie chart of departments", "histogram of ages".
       - Even misspelled: "visulaize", "grpah", "chatrt" etc. still mean PLOT.
       - IF YES -> Return "PLOT".
       
    2. **METADATA** (File Structure & Schema):
       - DOES the query ask about the *file itself* (columns, types, size, nulls, structure) rather than the data inside?
       - Examples: "Describe the file", "Data types", "File summary", "Structure overview", "Summarize the dataset", "Describe a specific column".
       - IF YES -> Return "METADATA".
       
    3. **ANALYTICAL** (Structured Data Operations):
       - DOES the query involve retrieving, filtering, calculating, or listing specific row data?
       - Operations: Sorting, Grouping, Averaging, Filtering ("Where salary > 5000"), Counting, Sum, Total, Standard Deviation, Correlation, Regression, Pivot.
       - **Numerical Comparisons:** "Salary difference between X and Y", "Who earns more, A or B?".
       - **Data retrieval for specific entities:** "Details of John", "Show HR department", "Get ID 10".
       - Even misspelled: "calcuate", "averge", "filtr", "give me all" etc. still mean ANALYTICAL.
       - IF YES -> Return "ANALYTICAL".
       
    4. **SEMANTIC** (Conceptual Search, Profiles & Comparisons):
       - DOES the query ask for qualitative insights, themes, fuzzy matching, or **conceptual comparisons between entities**?
       - **CRITICAL:** If the query asks to "compare", "describe similarities", "describe dissimilarities", "find differences" or "find similarities" between two or more people/entities — this is SEMANTIC, NOT ANALYTICAL. These need vector-based record retrieval and LLM reasoning, not pandas math.
       - Examples: "Describe similarities and dissimilarities between A and B", "Compare the profiles of A and B", "Find complaints about service", "What is the general sentiment?", "Find anomalies", "Search for similar comments", "Find records similar to X".
       - Use SEMANTIC when the query requires understanding meaning/context rather than exact filtering or math.
       - IF YES -> Return "SEMANTIC".
    
    User Query: "{query}"
    
    Respond ONLY with one word: PLOT, METADATA, ANALYTICAL, or SEMANTIC.
    """

        # Log the full prompt so developers see exactly what was sent to the LLM.
        langfuse_context.update_current_observation(
            input={"query": query, "prompt": prompt.strip()},
            metadata={"file_uuid": self.file_uuid},
        )

        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                try:
                    lf_cb = langfuse_context.get_current_langchain_handler()
                    callbacks = [lf_cb] if lf_cb else None
                except Exception:
                    callbacks = None
                resp = self.llm.invoke(prompt, config={"callbacks": callbacks} if callbacks else {}).content.strip().upper()
                intent = None
                if "METADATA" in resp: intent = "METADATA"
                elif "ANALYTICAL" in resp: intent = "ANALYTICAL"
                elif "PLOT" in resp: intent = "PLOT"
                else: intent = "SEMANTIC"  # Default fallback
                
                logger.info(f"✅ Intent detection successful: {intent}")
                langfuse_context.update_current_observation(
                    output={"intent": intent},
                )
                return intent
            except Exception as e:
                error_str = str(e)
                if "10054" in error_str or "Connection" in error_str or "timeout" in error_str.lower():
                    logger.warning(f"⚠️ LLM connection lost during intent detection (Attempt {attempt+1}/{max_retries+1}): {error_str[:100]}")
                    if attempt < max_retries:
                        import time as _time
                        _time.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s, 4s...
                        continue
                log_full_exception(e, f"Intent detection failed (Attempt {attempt+1})")
                break
        
        logger.warning("Intent detection failed after retries, defaulting to SEMANTIC")
        return "SEMANTIC"
