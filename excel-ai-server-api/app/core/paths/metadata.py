"""
Metadata path mixin for HybridAgent.

Extracted from agent.py — handles metadata/schema queries.
"""
from __future__ import annotations

import json
import time

from app.utils.logging import logger, log_full_exception
from app.config import observe, langfuse_context


class MetadataPathMixin:
    """Mixin providing the metadata query execution path."""

    @observe(as_type="span", name="Metadata Path")
    def run_metadata_path(self, query):
        """
        Generates either a rich overview OR a specific answer based on the user's query.
        """
        langfuse_context.update_current_observation(
            input={"query": query},
            metadata={"file_uuid": self.file_uuid, "filename": self.filename},
            tags=["metadata-path"],
        )
        max_retries = 2
        last_error = ""
        
        for attempt in range(max_retries + 1):
            try:
                logger.info(f"🗂️ METADATA PATH (Attempt {attempt+1}): {query}")
                
                # 1. Prepare Inputs
                stats_str = json.dumps(self.column_stats, indent=2)
                try:
                    data_preview = self.df.head(10).to_markdown(index=False)
                except:
                    data_preview = str(self.df.head(10).to_dict(orient='records'))

                prompt = f"""c
                You are a Senior Data Analyst. Your goal is to answer the user's question using the provided metadata.

                ### INPUT DATA:
                **Dataset Shape:** {len(self.df)} Rows × {len(self.df.columns)} Columns
                **Column Statistics:** {stats_str}
                **Data Preview:**
                {data_preview}

                ### USER QUERY: 
                "{query}"

               ### INSTRUCTIONS:
                First, determine the user's intent:

                **SCENARIO A: User asks for a Summary, Overview, or "What is this file?"**
                -> Provide a "Rich Data Story" using this structure:
                   1. **📊 Executive Summary**: What the dataset represents (infer from columns).
                   2. **🧐 Data Quality Health**: Assessment of missing values/cleanliness.
                   3. **📂 Structural Breakdown**: Group key columns logically (e.g., "Financials", "Dates") and describe them using the stats (ranges, unique counts).
                   4. **💡 Analyst Notes**: One interesting pattern or observation.

                **SCENARIO B: User asks about a specific Column, Statistic, or Detail (e.g., "Describe the Age column", "How many rows?")**
                -> Provide a **Direct, Focused Answer**.
                   - Do NOT give the full executive summary.
                   - Focus ONLY on the requested field/metric.
                   - Use the stats (min/max/unique/nulls) to provide a complete answer for that specific target.
                   - Example: "The **Age** column is a numeric field ranging from 18 to 65. It has 0 missing values and an average of 35."

                ### TONE:
                - dont use senerio names in the answer.dont interpret the user query, just answer it.
                - Professional, human, and data-driven.
                - Always cite numbers from the metadata as proof.
                - Use Markdown (bolding) for key terms.
                """

                # Update observation with the full prompt AFTER it is built.
                langfuse_context.update_current_observation(
                    input={"query": query, "prompt": prompt.strip()},
                    metadata={
                        "file_uuid": self.file_uuid,
                        "filename": self.filename,
                        "dataset_rows": len(self.df),
                        "dataset_cols": len(self.df.columns),
                    },
                )
                
                # 3. Invoke LLM with timeout handling
                try:
                    try:
                        lf_cb = langfuse_context.get_current_langchain_handler()
                        callbacks = [lf_cb] if lf_cb else None
                    except Exception:
                        callbacks = None
                    response = self.llm.invoke(
                        prompt,
                        config={"callbacks": callbacks} if callbacks else {},
                    ).content
                    logger.info(f"✅ Metadata analysis successful")
                    self._trace_path_output(
                        path_name="Metadata Path",
                        query=query,
                        output_value=response or "",
                        exit_point="metadata_response",
                        extra={"response_preview": (response or "")[:300]},
                    )
                    return response
                except Exception as llm_error:
                    last_error = str(llm_error)
                    if "10054" in str(llm_error) or "Connection" in str(llm_error):
                        logger.warning(f"⚠️ LLM connection lost (Attempt {attempt+1}/{max_retries+1}): {type(llm_error).__name__}")
                        if attempt < max_retries:
                            time.sleep(2 ** attempt)  # Exponential backoff
                            continue
                    raise
                
            except Exception as e:
                log_full_exception(e, f"Metadata path error (Attempt {attempt+1}/{max_retries+1})")
                if attempt == max_retries:
                    # All retries exhausted
                    if "Connection" in str(e) or "10054" in str(e):
                        _err_msg = "The AI service is temporarily unavailable. Please check your network connection and try again."
                    else:
                        _err_msg = "I couldn't analyze the dataset metadata due to an internal error. Please try again later."
                    self._trace_path_output(
                        path_name="Metadata Path",
                        query=query,
                        output_value=_err_msg,
                        exit_point="metadata_error",
                        status="error",
                        extra={"error": str(e)[:200]},
                    )
                    return _err_msg
                # Continue to next retry
