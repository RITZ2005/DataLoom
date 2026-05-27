"""
File operations mixin for HybridAgent.

Extracted from agent.py — handles soft delete, restore, and hard delete of files.
"""
from __future__ import annotations

from app.utils.logging import logger


class FileOpsMixin:
    """Mixin providing file lifecycle management methods."""

    def soft_delete_file(self):
        """Temporarily delete the file (Move to Recycle Bin)"""
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                logger.info(f"🗑️ Soft deleting file: {self.filename} ({self.file_uuid})")
                cur.execute(
                    "UPDATE file_registry SET is_deleted = TRUE, deleted_at = CURRENT_TIMESTAMP WHERE file_uuid = %s",
                    (self.file_uuid,)
                )
            conn.commit()
        logger.info("✅ File moved to recycle bin.")

    def restore_file(self):
        """Restore a file from the Recycle Bin"""
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                logger.info(f"♻️ Restoring file: {self.filename} ({self.file_uuid})")
                cur.execute(
                    "UPDATE file_registry SET is_deleted = FALSE, deleted_at = NULL WHERE file_uuid = %s",
                    (self.file_uuid,)
                )
            conn.commit()
        logger.info("✅ File restored successfully.")

    def hard_delete_file(self):
        """Permanently delete the file and drop its table"""
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                logger.info(f"🔥 Permanently deleting file: {self.filename} ({self.table_name})")
                # Drop the actual data table
                cur.execute(f"DROP TABLE IF EXISTS {self.table_name}")
                # Soft delete chat history tied to this file
                cur.execute(
                    """UPDATE chat_history
                       SET is_deleted = TRUE, deleted_at = CURRENT_TIMESTAMP
                       WHERE file_uuid = %s AND is_deleted = FALSE""",
                    (self.file_uuid,)
                )
                # Remove record from registry
                cur.execute("DELETE FROM file_registry WHERE file_uuid = %s", (self.file_uuid,))
            conn.commit()
        logger.info("✅ File permanently deleted.")
