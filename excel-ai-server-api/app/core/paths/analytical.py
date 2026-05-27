"""
Analytical path mixin for HybridAgent.

Extracted from agent.py — handles pandas agent initialization and
the analytical query execution path with self-correction loop.
"""
from __future__ import annotations

import os
import json
from langchain_experimental.agents import create_pandas_dataframe_agent
from langchain_core.callbacks.base import BaseCallbackHandler

from app.utils.logging import logger, log_full_exception
from app.core.llm import create_workspace_llm, invoke_llm_with_retry
from app.core.callbacks import LongListInterceptor
from app.config import observe, langfuse_context


class AnalyticalPathMixin:
    """Mixin providing pandas agent setup and the analytical query execution path."""

    def _ensure_llm(self) -> None:
        """Ensure the LLM is available for agent/fallback usage."""
        if getattr(self, "llm", None) is not None:
            return

        self.llm, _ = create_workspace_llm(temperature=0, streaming=False)

    def _init_pandas_agent(self):
        self._ensure_llm()
        # Build column information string
        column_info = "\n        ".join([f"- `{col}`: {self.column_stats['columns'][col].get('type', 'unknown')} ({self.column_stats['columns'][col].get('unique_count', 0)} unique values)" 
                                         for col in self.columns[:20]])  # Show first 20 columns
        
        # UPDATED: Include actual column names so agent knows what exists
        prefix = f"""
        You are an expert Data Analyst working with a pandas DataFrame `df`.
        
        **AVAILABLE COLUMNS IN THIS DATASET:**
        {column_info}
        
        IMPERATIVE FORMATTING RULES:
        1. **NO MARKDOWN / NO BACKTICKS:** NEVER wrap your code in backtick fences of ANY length.
           - CORRECT: Write the Python code DIRECTLY after "Action Input:" with NO surrounding backticks.
        2. **WRITE CLEAN CODE:** In Action Input, write Python code naturally across multiple lines.
           Just write the code as you would in a Python file - each statement on a new line.
        3. **ONE PRINT STATEMENT ONLY:** Your code block MUST contain exactly ONE print() call, placed at the very end.
           - FORBIDDEN: two or more print() calls anywhere in the code block.
             WRONG EXAMPLE:
               print(highest_salary_employee)
               print(lowest_salary_employee)
           - CORRECT: combine all results into a single structure, then print once at the end.
             CORRECT EXAMPLE:
               result = [highest_salary_employee, lowest_salary_employee]
               print(result)
           - You may have as many computation lines and intermediate variables as needed — but ONLY ONE final print().
        4. **SINGLE RECORD OUTPUT:** When returning details for ONE person/record:
           - Use .to_dict('records')[0] to convert to dictionary
           - Output the dictionary directly (no tables, no markdown)
        5. **LISTING/TABULAR OUTPUT:** When user asks for multiple records with conditions:
           - Filter data first, then convert to dictionary format
           - IMPORTANT: Convert datetime columns to strings first using .astype(str)
           - Then use filtered_df.to_dict('records') - this returns list of dictionaries
           - Example: result = df[df['ethnicity'] == 'Latino']; result.astype(str).to_dict('records')
           - CRITICAL: Just output the raw list/dictionary. Do NOT add explanations, descriptions, or analysis.
           - Do NOT say "Here's the data" or "This represents..." - just output the data structure directly.
           - Your Final Answer should be ONLY the list of dictionaries, nothing else.
        6. **GROUPBY/AGGREGATION OUTPUT:** When grouping data or counting (value_counts, groupby):
           - CRITICAL: .to_dict('records') ONLY works on DataFrames, NOT Series
           - Use .reset_index() to convert Series to DataFrame first
           - Example for value_counts: df['column'].value_counts().reset_index().to_dict('records')
           - Example for groupby: df.groupby('col')['another_col'].count().reset_index().to_dict('records')
           - After reset_index(), columns will be: [original_column_name, 'count'] or [group_column, agg_column]
           - Then convert to dict: result.astype(str).to_dict('records')
        
        CRITICAL DATA RULES:
        1. **COLUMN NAMES:** ALWAYS check the available columns list above. Use EXACT names (case-sensitive).
           - For HUMAN NAMES → search in NAME columns (certificatename, name, full_name, etc.)
           - For ID/CODE numbers → search in ID columns (learner_code, id, employee_id, etc.)
           - NEVER search for human names in ID columns
           - NEVER assume column names - use what exists in the list above
        2. **Nulls:** Use `.isna()` or `.notna()`. NEVER use `== 'NaN'`.
        3. **Strings:** Use `df['col'].str.contains('val', case=False, na=False)`.
        4. **QUOTED IDS:** Some ID columns store values with a leading single quote (e.g. `'12345`). 
           - If a search for `12345` returns empty, YOU MUST retry searching for `'12345` (including the quote).
           - Code Example: `df[df['learner_code'] == "'12345"]`
        5. **LONG LISTS:** If the user asks for a list and the result is long (e.g. > 10 names):
           - Do NOT describe the list (e.g. "Okay, here is the list...").
           - Do NOT analyze the list in the Final Answer.
           - Just output "Final Answer:" followed immediately by the list or comma-separated values.
        6. **HIERARCHY & RANKING:** If asked for "highest" or "lowest" of a CATEGORICAL column (e.g., "highest qualification", "lowest designation"):
           - Do NOT just sort alphabetically.
           - FIRST: Retrieve `df['col'].unique()`.
           - SECOND: Output the unique values in your thought process.
           - THIRD: Use your own knowledge to decide which value is highest/lowest (e.g., Ph.D > Masters > Bachelors).
           - FOURTH: Return that specific value.
        7. **SERIES to DICT ERROR FIX:** If you get "TypeError: unsupported type: <class 'str'>" when using .to_dict('records'):
           - This means you're trying to use .to_dict('records') on a Series (from value_counts() or groupby().count())
           - SOLUTION: Use .reset_index() first to convert Series to DataFrame
           - Example: df['col'].value_counts().reset_index().astype(str).to_dict('records')
           - Example: df.groupby('col1')['col2'].count().reset_index().astype(str).to_dict('records')
        

        """
        
        # ================================================================
        # ROBUST FIX: Code Fixer Callback
        # ================================================================
        class CodeFixerCallback(BaseCallbackHandler):
            """Intercepts and fixes code with \\n escape sequences before execution."""
            def on_agent_action(self, action, **kwargs):
                """Called when agent decides to use a tool."""
                # If this is a python_repl_ast action, fix the code
                if hasattr(action, 'tool_input'):
                    tool_input = action.tool_input
                    if isinstance(tool_input, str) and '\\\\n' in tool_input:
                        # Convert \\\\n escape sequences to actual newlines
                        fixed_input = tool_input.replace('\\\\n', '\\n')
                        logger.info(f"🔧 CODE FIX: Converted \\\\n escape sequences to actual newlines")
                        action.tool_input = fixed_input
        
        # We pass a specific error handler instruction
        def parsing_error_fix(error: str) -> str:
            error_str = str(error)
            # Detect backtick-wrapped code (3, 4, or more backticks) - LLM loophole
            # Check for ANY backtick fences, not just those with 'python'
            if "`" in error_str and ("python" in error_str.lower() or "Could not parse LLM output: `" in error_str):
                return (
                    "FORMAT ERROR: You wrapped your output in backtick fences. "
                    "This is STRICTLY FORBIDDEN. "
                    "You MUST use the ReAct format. "
                    "If you have computed the final answer, respond EXACTLY like this:\n"
                    "Final Answer: <your answer here>\n\n"
                    "If you need to run more code, respond EXACTLY like this:\n"
                    "Action: python_repl_ast\n"
                    "Action Input:\n"
                    "result = df['col'].max()\n"
                    "print(result)\n\n"
                    "NEVER wrap anything in backticks (``` or ````). Just write the text directly."
                )
            # Check if this is the \n syntax error
            if "unexpected character after line continuation character" in error_str:
                return "Retry with proper code formatting: write each statement on its own line without backslash escapes."
            # Generic fallback with clear ReAct format instructions
            return (
                f"Parsing Error: {error_str}\n\n"
                "You MUST respond in the ReAct format. Either:\n"
                "1) Final Answer: <answer>\n"
                "2) Action: python_repl_ast\nAction Input:\n<code>\n\n"
                "Do NOT use backticks or any other format."
            )
        
        # Store code fixer for use during agent execution
        self.code_fixer_callback = CodeFixerCallback()
        
        self.pandas_agent = create_pandas_dataframe_agent(
            self.llm,
            self.df,
            verbose=True,
            allow_dangerous_code=True,
            agent_type="zero-shot-react-description",
            prefix=prefix,
            max_iterations=10,
            # IMPORTANT: handle_parsing_errors MUST go through agent_executor_kwargs
            # because create_pandas_dataframe_agent silently ignores **kwargs
            agent_executor_kwargs={"handle_parsing_errors": parsing_error_fix}
        )

    def _ensure_pandas_agent(self) -> bool:
        """Ensure pandas agent is available for agent-driven computations."""
        if getattr(self, "pandas_agent", None) is not None:
            return True

        try:
            logger.info("[pandas_agent] Not initialized, creating lazily for this request")
            self._init_pandas_agent()
            return getattr(self, "pandas_agent", None) is not None
        except Exception as e:
            log_full_exception(e, "Failed to initialize pandas agent lazily")
            return False

    @observe(as_type="span", name="Analytical Path")
    def run_analytical_path(self, query):
        langfuse_context.update_current_observation(
            input={"query": query},
            metadata={
                "file_uuid": self.file_uuid,
                "filename": self.filename,
                "dataset_rows": len(self.df) if hasattr(self, 'df') and self.df is not None else None,
                "dataset_cols": len(self.df.columns) if hasattr(self, 'df') and self.df is not None else None,
            },
            tags=["analytical-path", "pandas-agent"],
        )
        # NEW: Self-Correction Loop for Pandas Agent
        max_retries = 2
        last_error = ""

        if not self._ensure_pandas_agent():
            _err_msg = "Analytical agent is not ready for this file. Please retry in a moment."
            self._trace_path_output(
                path_name="Analytical Path",
                query=query,
                output_value=_err_msg,
                exit_point="pandas_agent_missing",
                status="error",
            )
            return _err_msg
        
        for attempt in range(max_retries + 1):
            try:
                logger.info(f"🐼 ANALYTICAL PATH (Attempt {attempt+1}): {query}")
                
                # If this is a retry, append the feedback to the query
                current_query = query
                if last_error:
                     current_query = f"User Query: {query}\n\nPREVIOUS ATTEMPT FAILED. Feedback: {last_error}\n\nINSTRUCTION: Try a different approach or fix the syntax."

                # Create callback handler to intercept long list outputs
                interceptor = LongListInterceptor()

                # Compose all callbacks: observability first, then tool-level handlers.
                try:
                    lf_cb = langfuse_context.get_current_langchain_handler()
                    callbacks = [lf_cb] if lf_cb else None
                except Exception:
                    callbacks = None
                _agent_callbacks = [interceptor, self.code_fixer_callback]
                if callbacks:
                    _agent_callbacks.extend(callbacks)

                # Invoke agent with callback and return intermediate steps
                try:
                    response = self.pandas_agent.invoke(
                        {"input": current_query, "return_intermediate_steps": True},
                        config={"callbacks": _agent_callbacks}
                    )
                except Exception as agent_error:
                    # If agent fails BUT interceptor caught output, IGNORE THE ERROR and use intercepted data!
                    if interceptor.intercepted_output:
                        logger.info("⚡ Agent parsing failed but interceptor saved the output - using it directly!")
                        
                        # Convert to CSV (primary and only method)
                        csv_result = self._convert_dict_to_csv_preview(query, interceptor.intercepted_output)
                        if csv_result:
                            logger.info("✅ CSV conversion successful - returning immediately!")
                            self._trace_path_output(
                                path_name="Analytical Path",
                                query=query,
                                output_value=csv_result,
                                exit_point="interceptor_csv_agent_error",
                            )
                            return csv_result
                        
                        logger.warning("⚠️ Interceptor caught data but CSV conversion failed")
                    
                    # If no intercepted output OR conversion failed, re-raise the error
                    raise agent_error
                
                # CHECK IF INTERCEPTOR CAUGHT A LONG LIST - Convert to CSV preview!
                if interceptor.intercepted_output:
                    logger.info("🚀 Agent succeeded AND interceptor caught output - converting to CSV preview")
                    
                    # Convert to CSV or profile (single-entry lists handled inside)
                    csv_result = self._convert_dict_to_csv_preview(query, interceptor.intercepted_output)
                    if csv_result:
                        logger.info("✅ Successfully converted intercepted output")
                        self._trace_path_output(
                            path_name="Analytical Path",
                            query=query,
                            output_value=csv_result,
                            exit_point="interceptor_csv_normal",
                        )
                        return csv_result
                    
                    logger.warning("⚠️ Failed to convert intercepted output")
                
                # ================================================================
                # Process Final Answer from agent (Standard Pipeline)
                # ================================================================
                raw_answer = response['output']
                logger.info(f"📝 Processing Final Answer: {len(str(raw_answer))} chars")
                
                # CHECK: If raw_answer is a stringified list of dicts, try CSV conversion.
                
                _stripped_answer = raw_answer.strip() if isinstance(raw_answer, str) else ''
                _estimated_records = _stripped_answer.count('}, {') + 1  # e.g. 2 records → 1 separator
                _is_csv_candidate = (
                    _stripped_answer.startswith('[') and
                    _stripped_answer.endswith(']') and
                    '\n[' not in _stripped_answer and   # not a multi-print output
                    _estimated_records > 3              # only CSV-export genuinely long lists
                )
                if isinstance(raw_answer, str) and _is_csv_candidate:
                     logger.info(f"💡 Agent returned a long list ({_estimated_records} records) - trying CSV/profile conversion")
                     csv_result = self._convert_dict_to_csv_preview(query, raw_answer)
                     if csv_result:
                         self._trace_path_output(
                             path_name="Analytical Path",
                             query=query,
                             output_value=csv_result,
                             exit_point="final_answer_csv",
                         )
                         return csv_result
                     logger.warning("⚠️ CSV/profile conversion failed for final answer list")

                # VALIDATION STEP: Ask LLM if the result looks valid
                validation_prompt = f"""
                You are a Quality Assurance Auditor for a Data Agent.
                
                User Query: "{query}"
                Agent Result: "{raw_answer}"
                
                Task: Determine if the result is valid.
                - If the result looks like a python error, syntax error, or "I don't know", return INVALID.
                - If the result is a list, number, or clear text answer, return VALID.
                - If the answer is "Final Answer: ...", return VALID.
                
                Respond ONLY with: VALID or INVALID.
                """
                try:
                    try:
                        lf_cb = langfuse_context.get_current_langchain_handler()
                        _val_cbs = [lf_cb] if lf_cb else None
                    except Exception:
                        _val_cbs = None
                    check = invoke_llm_with_retry(self.llm, validation_prompt, max_retries=2, context_name="Result validation", callbacks=_val_cbs).upper()
                except Exception:
                    # If validation fails, assume result is VALID and proceed
                    logger.warning("⚠️ Validation check failed due to LLM error, assuming VALID and proceeding")
                    check = "VALID"
                
                if "VALID" in check:
                    # SELF-EVALUATION: Cross-check the pandas query logic twice
                    logger.info("🔍 Self-evaluation: Cross-checking pandas query logic")
                    
                    # Get intermediate steps for cross-check
                    intermediate_steps = response.get('intermediate_steps', [])
                    agent_actions = []
                    if intermediate_steps:
                        for step in intermediate_steps:
                            if len(step) >= 2:
                                action, observation = step[0], step[1]
                                if hasattr(action, 'tool_input'):
                                    agent_actions.append(str(action.tool_input))
                    
                    # First cross-check
                    if agent_actions:
                        cross_check_prompt1 = f"""
                        Review this pandas query for correctness:
                        
                        User Query: "{query}"
                        Agent's Code: {agent_actions[-1] if agent_actions else 'N/A'}
                        Result: {raw_answer}
                        
                        Does the code correctly answer the user's question?
                        Respond ONLY with: CORRECT or INCORRECT
                        """
                        try:
                            try:
                                lf_cb = langfuse_context.get_current_langchain_handler()
                                _cc1_cbs = [lf_cb] if lf_cb else None
                            except Exception:
                                _cc1_cbs = None
                            check1 = invoke_llm_with_retry(self.llm, cross_check_prompt1, max_retries=2, context_name="Cross-check 1", callbacks=_cc1_cbs).upper()
                        except Exception:
                            logger.warning("⚠️ Cross-check 1 failed due to LLM error, assuming CORRECT")
                            check1 = "CORRECT"
                        
                        logger.info(f"📊 First cross-check: {check1}")
                        
                        # Second cross-check (double validation)
                        cross_check_prompt2 = f"""
                        Second review - verify the logic:
                        
                        User Query: "{query}"
                        Result: {raw_answer}
                        
                        Is this result appropriate for the user's question?
                        Respond ONLY with: YES or NO
                        """
                        try:
                            try:
                                lf_cb = langfuse_context.get_current_langchain_handler()
                                _cc2_cbs = [lf_cb] if lf_cb else None
                            except Exception:
                                _cc2_cbs = None
                            check2 = invoke_llm_with_retry(self.llm, cross_check_prompt2, max_retries=2, context_name="Cross-check 2", callbacks=_cc2_cbs).upper()
                        except Exception:
                            logger.warning("⚠️ Cross-check 2 failed due to LLM error, assuming YES")
                            check2 = "YES"
                        
                        logger.info(f"📊 Second cross-check: {check2}")
                        
                        if "INCORRECT" in check1 or "NO" in check2:
                            last_error = f"Self-evaluation detected issue: First check={check1}, Second check={check2}"
                            logger.warning(f"⚠️ Self-evaluation failed - retrying with feedback")
                            continue
                    
                    # All checks passed - humanize and return
                    logger.info("✅ All validation checks passed - proceeding to humanization")
                    _humanized = self._humanize_response(query, raw_answer, intermediate_steps)
                    self._trace_path_output(
                        path_name="Analytical Path",
                        query=query,
                        output_value=_humanized,
                        exit_point="humanized_response",
                    )
                    return _humanized
                else:
                    last_error = "The previous result was rejected by QA because it looked like an error or incomplete answer."
                    logger.warning(f"❌ Attempt {attempt+1} Rejected: {raw_answer}")
                    continue

            except Exception as e:
                last_error = str(e)
                log_full_exception(e, f"Pandas Agent Error (Attempt {attempt+1})")
                
        _final_fail_msg = "I tried to analyze the data multiple times but couldn't generate a valid answer."
        self._trace_path_output(
            path_name="Analytical Path",
            query=query,
            output_value=_final_fail_msg,
            exit_point="exhausted_retries",
            status="error",
        )
        return _final_fail_msg
