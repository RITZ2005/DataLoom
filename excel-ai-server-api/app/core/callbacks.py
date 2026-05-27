"""
Custom LangChain callback handler — extracted from hybrid_chat_system.py.

Intercepts long list outputs from the pandas agent to avoid
overwhelming the LLM with huge tool results.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.callbacks.base import BaseCallbackHandler

logger = logging.getLogger("HybridSystem")


class LongListInterceptor(BaseCallbackHandler):
    """
    Custom callback handler that intercepts tool outputs and detects long lists.
    Intercepts both simple lists AND list of dicts from .to_dict('records').
    """
    def __init__(self):
        self.intercepted_output = None
        self.should_stop = False

    def on_tool_end(self, output: str, **kwargs: Any) -> None:
        """Called when a tool (like python_repl_ast) finishes execution."""
        output_str = str(output)

        # Check 1: Must start with [ and have multiple items
        if not (output_str.strip().startswith('[') and output_str.count(',') > 10):
            return

        # Check 2: Skip pandas Series and DataFrame representations (they have dtype, index markers)
        if any(indicator in output_str[:200] for indicator in ['dtype:', '0   ', '1   ', 'Name:', '\n0 ']):
            logger.info(f"⏭️ Skipping interception - detected Series/DataFrame, not list")
            return

        # Check 3: Intercept both simple lists AND list of dicts
        # List of dicts: [{'key': 'value', ...}, {...}]
        # Simple list: ['value1', 'value2', ...]
        is_list_of_dicts = ('{' in output_str[:500] and ':' in output_str[:500])
        is_simple_list = (output_str.count("'") > 10 or output_str.count('"') > 10)

        if is_list_of_dicts or is_simple_list:
            list_type = "list of dicts" if is_list_of_dicts else "simple list"
            logger.info(f"🎯 INTERCEPTED {list_type} output ({output_str.count(',')+1} items)")
            self.intercepted_output = output_str
            self.should_stop = True
        else:
            logger.info(f"⏭️ Skipping interception - unrecognized format")
