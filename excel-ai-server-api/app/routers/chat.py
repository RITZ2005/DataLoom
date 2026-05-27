import json
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_db
from app.schemas.chat import (
    ChatMessageResponse,
    ChatMessageSave,
    ChatMessageSoftDelete,
    SessionCloseRequest,
)
from app.utils.logging import log_full_exception, logger, user_facing_error_message
from app.core.auth import UserManager, get_current_user, verify_token

try:
    from app.config import observe
except ImportError:
    def observe(_func=None, *, name: str = "", **kwargs):
        def decorator(func):
            return func
        return _func if _func else decorator

router = APIRouter(prefix="/api", tags=["chat"])


@router.get("/chat/{file_uuid}", response_model=List[ChatMessageResponse])
@observe(name="chat.history")
async def get_chat_history(
    file_uuid: str,
    limit: int = 10,
    offset: int = 0,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        user_id = current_user.get("id")
        safe_limit = max(1, min(limit, 100))
        safe_offset = max(0, offset)
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, file_uuid, role, content, query_type, cache_hit, response_time, metadata, created_at
                       FROM chat_history
                       WHERE user_id = %s AND file_uuid = %s
                         AND is_deleted = FALSE
                       ORDER BY id DESC
                       LIMIT %s OFFSET %s""",
                    (user_id, file_uuid, safe_limit, safe_offset),
                )
                rows = cur.fetchall()

        results = []
        for row in reversed(rows):
            meta = row[7]
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = None
            results.append(
                ChatMessageResponse(
                    id=row[0],
                    file_uuid=row[1],
                    role=row[2],
                    content=row[3],
                    query_type=row[4],
                    cache_hit=row[5] or False,
                    response_time=row[6],
                    metadata=meta,
                    created_at=row[8].isoformat() if row[8] else "",
                )
            )
        return results
    except Exception as e:
        log_full_exception(e, "Failed to load chat history")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))


@router.post("/chat/{file_uuid}", response_model=ChatMessageResponse)
@observe(name="chat.save_message")
async def save_chat_message(
    file_uuid: str,
    message: ChatMessageSave,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        user_id = current_user.get("id")
        metadata_json = json.dumps(message.metadata) if message.metadata else None
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO chat_history (user_id, file_uuid, role, content, query_type, cache_hit, response_time, metadata)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                       RETURNING id, created_at""",
                    (
                        user_id,
                        file_uuid,
                        message.role,
                        message.content,
                        message.query_type,
                        message.cache_hit,
                        message.response_time,
                        metadata_json,
                    ),
                )
                result = cur.fetchone()
            conn.commit()

        return ChatMessageResponse(
            id=result[0],
            file_uuid=file_uuid,
            role=message.role,
            content=message.content,
            query_type=message.query_type,
            cache_hit=message.cache_hit,
            response_time=message.response_time,
            metadata=message.metadata,
            created_at=result[1].isoformat() if result[1] else "",
        )
    except Exception as e:
        log_full_exception(e, "Failed to save chat message")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))


@router.delete("/chat/{file_uuid}")
@observe(name="chat.clear_history")
async def clear_chat_history(
    file_uuid: str,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        user_id = current_user.get("id")
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE chat_history
                       SET is_deleted = TRUE, deleted_at = CURRENT_TIMESTAMP
                       WHERE user_id = %s AND file_uuid = %s AND is_deleted = FALSE""",
                    (user_id, file_uuid),
                )
                deleted = cur.rowcount
            conn.commit()

        return {"status": "success", "message": f"Soft deleted {deleted} messages", "deleted": deleted}
    except Exception as e:
        log_full_exception(e, "Failed to clear chat history")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))


@router.post("/session/close")
@observe(name="chat.close_session")
async def close_session_beacon(
    request: SessionCloseRequest,
    db=Depends(get_db),
):
    try:
        payload = verify_token(request.token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        email = payload.get("email")
        if not email:
            raise HTTPException(status_code=401, detail="Token missing email claim")

        user_manager = UserManager()
        user = user_manager.get_user(email)
        if not user or not user.get("is_active"):
            raise HTTPException(status_code=401, detail="User not found or inactive")

        user_id = user.get("id")
        session_id = request.session_id.strip()
        file_uuid = request.file_uuid.strip()

        if not session_id or not file_uuid:
            return {"status": "ignored", "reason": "empty session_id or file_uuid"}

        leave_content = "Session ended (browser closed)\nLangfuse Session ID: " + session_id
        metadata_json = json.dumps(
            {
                "isSessionEvent": True,
                "sessionEvent": "leave",
                "langfuseSessionId": session_id,
                "closedBy": "sendBeacon",
            }
        )

        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT 1 FROM chat_history
                       WHERE file_uuid = %s AND metadata::jsonb->>'langfuseSessionId' = %s
                         AND metadata::jsonb->>'sessionEvent' = 'leave'
                       LIMIT 1""",
                    (file_uuid, session_id),
                )
                if cur.fetchone():
                    logger.info("Session already closed, skipping duplicate: session=%s", session_id)
                    return {"status": "already_closed"}
                cur.execute(
                    """INSERT INTO chat_history (user_id, file_uuid, role, content, metadata)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (user_id, file_uuid, "assistant", leave_content, metadata_json),
                )
            conn.commit()

        logger.info("Session closed via sendBeacon: session=%s, file=%s, user=%s", session_id, file_uuid, email)
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Session close (beacon) failed: %s", e)
        return {"status": "error", "detail": str(e)[:200]}


@router.post("/chat/{file_uuid}/soft_delete")
@observe(name="chat.soft_delete")
async def soft_delete_chat_message(
    file_uuid: str,
    payload: ChatMessageSoftDelete,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        user_id = current_user.get("id")
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, role, created_at
                       FROM chat_history
                       WHERE id = %s AND user_id = %s AND file_uuid = %s""",
                    (payload.message_id, user_id, file_uuid),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Message not found")

                target_id, role, created_at = row
                delete_ids = [target_id]

                if role == "assistant":
                    cur.execute(
                        """SELECT id
                           FROM chat_history
                           WHERE user_id = %s AND file_uuid = %s AND role = 'user'
                             AND created_at <= %s AND is_deleted = FALSE
                           ORDER BY created_at DESC
                           LIMIT 1""",
                        (user_id, file_uuid, created_at),
                    )
                    user_row = cur.fetchone()
                    if user_row:
                        delete_ids.append(user_row[0])

                cur.execute(
                    """UPDATE chat_history
                       SET is_deleted = TRUE, deleted_at = CURRENT_TIMESTAMP
                       WHERE id = ANY(%s)""",
                    (delete_ids,),
                )
            conn.commit()

        return {"status": "success", "deleted_ids": delete_ids}
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Failed to soft delete chat message")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))
