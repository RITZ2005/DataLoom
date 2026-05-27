from fastapi import APIRouter, Depends, HTTPException
from typing import List, Any

from app.dependencies import get_db
from app.schemas import (
    CategoryItem, CategoryRenameRequest, SaveQuestionRequest, SavedQuestionResponse
)
from app.core import DatabaseManager
from app.utils.logging import log_full_exception, user_facing_error_message
from app.core.auth import get_current_user
from app.utils.audit import log_audit_event

from app.config import observe, langfuse_context


router = APIRouter(tags=["categories"])

DEFAULT_CATEGORIES = ["Generic"]


def resolve_file_scope(file_uuid: str, db: DatabaseManager) -> tuple:
    """
    Determine the scope of a file: ROOT, PROJECT, or SUBPROJECT.
    Returns (scope_level, scope_id).
    """
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT project_id, subproject_id FROM file_registry WHERE file_uuid = %s",
                (file_uuid,)
            )
            row = cur.fetchone()
            if not row:
                return ("ROOT", None)
            project_id, subproject_id = row
            if subproject_id:
                return ("SUBPROJECT", subproject_id)
            elif project_id:
                return ("PROJECT", project_id)
            else:
                return ("ROOT", None)


@router.get("/api/categories", response_model=List[CategoryItem])
@observe(name="categories.list")
async def list_categories(
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    List all categories derived from saved_questions.question_category
    plus default categories (Generic, Specific) which are always shown.
    """
    try:
        user_id = current_user.get("id")
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT question_category, COUNT(*) as cnt
                    FROM saved_questions
                    WHERE created_by = %s
                    GROUP BY question_category
                    ORDER BY question_category ASC
                """, (user_id,))
                rows = cur.fetchall()

        # Build map of category -> count
        cat_counts = {row[0]: row[1] for row in rows}

        # Ensure defaults are always present
        result = []
        seen = set()
        for default_cat in DEFAULT_CATEGORIES:
            result.append(CategoryItem(
                name=default_cat,
                question_count=cat_counts.get(default_cat, 0),
                is_default=True
            ))
            seen.add(default_cat)

        # Add user-created categories (any category not in defaults)
        for cat_name, count in sorted(cat_counts.items()):
            if cat_name not in seen:
                result.append(CategoryItem(
                    name=cat_name,
                    question_count=count,
                    is_default=False
                ))

        return result
    except Exception as e:
        log_full_exception(e, "Failed to list categories")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))


@router.put("/api/categories/rename")
@observe(name="categories.rename")
async def rename_category(
    request: CategoryRenameRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Rename a category by updating all saved_questions with old_name to new_name."""
    try:
        old_name = request.old_name.strip()
        new_name = request.new_name.strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="New category name is required")
        if old_name.lower() in [c.lower() for c in DEFAULT_CATEGORIES]:
            raise HTTPException(status_code=403, detail="Cannot rename default categories")

        user_id = current_user.get("id")
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                # Check if new name already in use
                cur.execute("""
                    SELECT COUNT(*) FROM saved_questions
                    WHERE LOWER(question_category) = LOWER(%s) AND created_by = %s
                """, (new_name, user_id))
                if cur.fetchone()[0] > 0 and old_name.lower() != new_name.lower():
                    raise HTTPException(status_code=409, detail=f"Category '{new_name}' already exists")

                cur.execute("""
                    UPDATE saved_questions
                    SET question_category = %s
                    WHERE question_category = %s AND created_by = %s
                """, (new_name, old_name, user_id))
                updated = cur.rowcount
            conn.commit()

        log_audit_event(
            db=db, user_id=user_id, action="rename_category",
            entity_type="category", entity_id=old_name,
            details={"old_name": old_name, "new_name": new_name, "updated_count": updated}
        )

        return {"status": "success", "old_name": old_name, "new_name": new_name, "updated_count": updated}
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Failed to rename category")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))


@router.delete("/api/categories/{category_name}")
@observe(name="categories.delete")
async def delete_category(
    category_name: str,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Delete a category by resetting all its questions to 'Uncategorized'."""
    try:
        if category_name.lower() in [c.lower() for c in DEFAULT_CATEGORIES]:
            raise HTTPException(status_code=403, detail="Cannot delete default categories")

        user_id = current_user.get("id")
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE saved_questions
                    SET question_category = 'Generic'
                    WHERE question_category = %s AND created_by = %s
                """, (category_name, user_id))
                updated = cur.rowcount
            conn.commit()

        return {"status": "success", "category": category_name, "questions_recategorized": updated}
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Failed to delete category")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))


@router.post("/api/questions/save", response_model=SavedQuestionResponse)
@observe(name="questions.save")
async def save_question(
    request: SaveQuestionRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Save/bookmark a question from a chat session.
    Automatically determines scope (ROOT/PROJECT/SUBPROJECT) from the file's location.
    """
    try:
        # Resolve file scope
        scope_level, scope_id = resolve_file_scope(request.file_uuid, db)
        user_id = current_user.get("id")
        category = request.category.strip() or "Generic"

        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO saved_questions (question_text, question_category, scope_level, scope_id, created_by)
                       VALUES (%s, %s, %s, %s, %s)
                       RETURNING id, created_at""",
                    (request.question_text, category, scope_level, scope_id, user_id)
                )
                result = cur.fetchone()
            conn.commit()

        log_audit_event(
            db=db,
            user_id=user_id,
            action="save_question",
            entity_type="saved_question",
            entity_id=str(result[0]),
            details={
                "question_text": request.question_text[:100],
                "category": category,
                "scope_level": scope_level,
                "scope_id": scope_id,
                "file_uuid": request.file_uuid
            }
        )

        return SavedQuestionResponse(
            id=result[0],
            question_text=request.question_text,
            question_category=category,
            scope_level=scope_level,
            scope_id=scope_id,
            created_at=result[1].isoformat() if result[1] else ""
        )
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Failed to save question")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))


@router.get("/api/questions/list", response_model=List[SavedQuestionResponse])
@observe(name="questions.list_all")
async def list_saved_questions(
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Fetch ALL saved questions for the current user across all scopes.
    Questions are globally accessible regardless of which project they were saved from.
    Deduplicates by question_text (keeps the most recently created).
    """
    try:
        user_id = current_user.get("id")

        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, question_text, question_category,
                              scope_level, scope_id, created_at
                       FROM saved_questions
                       WHERE created_by = %s
                       ORDER BY created_at DESC""",
                    (user_id,)
                )
                all_rows = cur.fetchall()

        # # Deduplicate by question_text (keep the first/newest occurrence)
        # seen_texts = set()
        # unique_rows = []
        # for row in all_rows:
        #     q_text = row[1].strip().lower()
        #     if q_text not in seen_texts:
        #         seen_texts.add(q_text)
        #         unique_rows.append(row)

        return [
            SavedQuestionResponse(
                id=row[0],
                question_text=row[1],
                question_category=row[2],
                scope_level=row[3],
                scope_id=row[4],
                created_at=row[5].isoformat() if row[5] else ""
            )
            for row in all_rows
        ]
    except Exception as e:
        log_full_exception(e, "Failed to list saved questions")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))


@router.get("/api/questions/list/{file_uuid}", response_model=List[SavedQuestionResponse])
@observe(name="questions.list_by_file")
async def list_saved_questions_for_file(
    file_uuid: str,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Fetch saved questions applicable to a target file scope.
    Includes ROOT + PROJECT + SUBPROJECT scopes relevant to the file.
    """
    try:
        user_id = current_user.get("id")

        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT project_id, subproject_id FROM file_registry WHERE file_uuid = %s",
                    (file_uuid,)
                )
                row = cur.fetchone()

                if not row:
                    project_id = None
                    subproject_id = None
                else:
                    project_id, subproject_id = row

                scope_clauses = ["(scope_level = 'ROOT' AND scope_id IS NULL)"]
                params: List[Any] = [user_id]

                if project_id:
                    scope_clauses.append("(scope_level = 'PROJECT' AND scope_id = %s)")
                    params.append(project_id)

                if subproject_id:
                    scope_clauses.append("(scope_level = 'SUBPROJECT' AND scope_id = %s)")
                    params.append(subproject_id)

                where_scope = " OR ".join(scope_clauses)
                query = (
                    "SELECT id, question_text, question_category, scope_level, scope_id, created_at "
                    "FROM saved_questions "
                    "WHERE created_by = %s AND (" + where_scope + ") "
                    "ORDER BY created_at DESC"
                )
                cur.execute(query, tuple(params))
                rows = cur.fetchall()

        return [
            SavedQuestionResponse(
                id=row[0],
                question_text=row[1],
                question_category=row[2],
                scope_level=row[3],
                scope_id=row[4],
                created_at=row[5].isoformat() if row[5] else ""
            )
            for row in rows
        ]
    except Exception as e:
        log_full_exception(e, "Failed to list saved questions for file scope")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))


@router.put("/api/questions/{question_id}")
@observe(name="questions.update")
async def update_saved_question(
    question_id: int,
    body: dict,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Update a saved question's text and/or category (only if owned by caller).
    """
    try:
        user_id = current_user.get("id")
        new_text = (body.get("question_text") or "").strip()
        new_category = (body.get("question_category") or "").strip()

        if not new_text and not new_category:
            raise HTTPException(status_code=400, detail="No fields to update")

        with db.get_connection() as conn:
            with conn.cursor() as cur:
                # Fetch existing row first
                cur.execute(
                    "SELECT question_text, question_category FROM saved_questions WHERE id = %s AND created_by = %s",
                    (question_id, user_id)
                )
                existing = cur.fetchone()
                if not existing:
                    raise HTTPException(status_code=404, detail="Question not found")

                updated_text = new_text if new_text else existing[0]
                updated_category = new_category if new_category else existing[1]

                cur.execute(
                    "UPDATE saved_questions SET question_text = %s, question_category = %s WHERE id = %s AND created_by = %s RETURNING id",
                    (updated_text, updated_category, question_id, user_id)
                )
                updated = cur.fetchone()
            conn.commit()

        if not updated:
            raise HTTPException(status_code=404, detail="Question not found")

        return {"status": "success", "id": question_id, "question_text": updated_text, "question_category": updated_category}
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Failed to update question")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))


@router.delete("/api/questions/{question_id}")
@observe(name="questions.delete")
async def delete_saved_question(
    question_id: int,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Delete a saved question by ID (only if owned by caller).
    """
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM saved_questions WHERE id = %s AND created_by = %s RETURNING id",
                    (question_id, current_user.get("id"))
                )
                deleted = cur.fetchone()
            conn.commit()

        if not deleted:
            raise HTTPException(status_code=404, detail="Question not found")

        return {"status": "success", "deleted_id": question_id}
    except HTTPException:
        raise
    except Exception as e:
        log_full_exception(e, "Failed to delete saved question")
        raise HTTPException(status_code=500, detail=user_facing_error_message(e))
