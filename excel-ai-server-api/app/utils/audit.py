"""
Audit logging utility — extracted from main.py.

Provides a single helper to write audit events to the database.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger("HybridSystem")


def log_audit_event(
    db,
    user_id: Optional[str],
    action: str,
    entity_type: str,
    entity_id: Optional[str] = None,
    details: Optional[dict] = None
):
    """Write an audit event to the database."""
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO audit_log (user_id, action, entity_type, entity_id, details) VALUES (%s, %s, %s, %s, %s)",
                    (user_id, action, entity_type, entity_id, json.dumps(details) if details else None)
                )
            conn.commit()
    except Exception as e:
        logger.warning(f"Audit log failed: {e}")
