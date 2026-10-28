"""HTTP uploads and document tasks. Owner is the session user, not a body field."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from orca.auth.middleware import get_current_user
from orca.auth.store import User
from orca.docs.authorized_task import DocumentTaskError, remove, run
from orca.serve.uploads import MAX_BYTES, UploadError, read_for, store_for

router = APIRouter(prefix="/api/documents", tags=["documents"])

_STATUS = {
    "unauthenticated": 401,
    "access_denied": 403,
    "not_found": 404,
}


def _raise(exc: Exception):
    code = getattr(exc, "code", "conflict")
    raise HTTPException(status_code=_STATUS.get(code, 409), detail={"error": code, "code": code}) from exc


@router.post("")
async def upload_document(upload: UploadFile = File(...), user: User = Depends(get_current_user)):
    data = await upload.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail={"error": "size_refused", "code": "size_refused"})
    try:
        return store_for(user, upload.filename or "upload.txt", data)
    except UploadError as exc:
        _raise(exc)


@router.post("/tasks")
async def document_task(
    upload: UploadFile = File(...),
    question: str | None = Query(None),
    form_question: str | None = Form(None),
    user: User = Depends(get_current_user),
):
    asked = (question or form_question or "").strip()
    if not asked:
        raise HTTPException(status_code=422, detail={"error": "query_refused", "code": "query_refused"})
    data = await upload.read()
    try:
        return run(user=user, filename=upload.filename or "upload.txt", data=data, question=asked)
    except (DocumentTaskError, UploadError) as exc:
        _raise(exc)


@router.get("/{filename}")
async def read_document(filename: str, user: User = Depends(get_current_user)):
    try:
        body = read_for(user, filename)
    except UploadError as exc:
        _raise(exc)
    return {"filename": filename, "nbytes": len(body), "sha256": __import__("hashlib").sha256(body).hexdigest()}


@router.delete("/{filename}")
async def delete_document(filename: str, user: User = Depends(get_current_user)):
    try:
        return remove(user=user, filename=filename)
    except (DocumentTaskError, UploadError) as exc:
        _raise(exc)
