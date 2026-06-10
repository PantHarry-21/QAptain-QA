"""
Dataset API — test data items (text values, uploaded files) used by the executor
when running validation and edge-case scenarios.

Predefined categories give teams a structured way to supply:
  - invalid_email, invalid_file, oversized_file, boundary_number,
    boundary_date, sql_injection, xss_payload, valid_file, etc.

The executor loads these items by application + category before starting a batch,
so scenarios tagged with "validation" or "boundary" automatically receive
the right test data without hard-coding values in the plan.
"""
from __future__ import annotations

import os
import re
import shutil
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import User, TestDataset
from app.core.dependencies import get_current_user, require_app_access
from config import settings

router = APIRouter()

# Uploaded test-data files are stored under artifacts/datasets/
# Allowed MIME types for uploaded test-data files (broad enough for QA use-cases)
ALLOWED_UPLOAD_MIMES = {
    "text/plain", "text/csv", "application/csv",
    "application/json",
    "application/pdf",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/zip", "application/x-zip-compressed",
    "image/png", "image/jpeg", "image/gif", "image/webp",
    "application/octet-stream",  # generic binary — many tools report this
}
DATASET_DIR = os.path.join(settings.ARTIFACTS_DIR, "datasets")


def _serialize(item: TestDataset) -> dict:
    return {
        "id": item.id,
        "application_id": item.application_id,
        "category": item.category,
        "label": item.label,
        "data_type": item.data_type,
        "text_value": item.text_value,
        "file_path": item.file_path,
        "file_name": item.file_name,
        "file_size": item.file_size,
        "description": item.description,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@router.get("/{application_id}")
async def list_dataset(
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all test dataset items for an application."""
    await require_app_access(application_id, current_user, db)
    result = await db.execute(
        select(TestDataset)
        .where(TestDataset.application_id == application_id)
        .order_by(TestDataset.category, TestDataset.created_at)
    )
    return [_serialize(item) for item in result.scalars().all()]


class DatasetItemCreate:
    def __init__(self, category: str, label: str, data_type: str = "text",
                 text_value: str | None = None, description: str | None = None):
        self.category = category
        self.label = label
        self.data_type = data_type
        self.text_value = text_value
        self.description = description


from pydantic import BaseModel

class DatasetItemPayload(BaseModel):
    category: str
    label: str
    data_type: str = "text"
    text_value: str | None = None
    description: str | None = None


@router.post("/{application_id}", status_code=201)
async def create_dataset_item(
    application_id: str,
    payload: DatasetItemPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a text/number/date/email/url dataset item."""
    await require_app_access(application_id, current_user, db)
    item = TestDataset(
        application_id=application_id,
        category=payload.category,
        label=payload.label,
        data_type=payload.data_type,
        text_value=payload.text_value,
        description=payload.description,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _serialize(item)


@router.post("/{application_id}/upload", status_code=201)
async def upload_dataset_file(
    application_id: str,
    category: str = Form(...),
    label: str = Form(...),
    description: str | None = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a file (e.g. 10 MB invalid file) as a dataset item."""
    await require_app_access(application_id, current_user, db)

    mime = (file.content_type or "").split(";")[0].strip().lower()
    if mime and mime not in ALLOWED_UPLOAD_MIMES:
        raise HTTPException(status_code=422, detail=f"File type '{mime}' is not allowed for test data uploads.")

    safe_filename = re.sub(r"[^\w.\-]", "_", os.path.basename(file.filename or "file"))[:255]

    os.makedirs(DATASET_DIR, exist_ok=True)

    ext = os.path.splitext(safe_filename)[-1]
    stored_name = f"{uuid.uuid4()}{ext}"
    dest = os.path.join(DATASET_DIR, stored_name)

    contents = await file.read()
    with open(dest, "wb") as f:
        f.write(contents)

    item = TestDataset(
        application_id=application_id,
        category=category,
        label=label,
        data_type="file",
        file_path=dest,
        file_name=safe_filename,
        file_size=len(contents),
        description=description,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _serialize(item)


class DatasetItemUpdate(BaseModel):
    label: str | None = None
    text_value: str | None = None
    description: str | None = None


@router.patch("/{application_id}/{item_id}")
async def update_dataset_item(
    application_id: str,
    item_id: str,
    payload: DatasetItemUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update label, value, or description of a text/number/date dataset item."""
    await require_app_access(application_id, current_user, db)
    result = await db.execute(
        select(TestDataset).where(
            TestDataset.id == item_id,
            TestDataset.application_id == application_id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Dataset item not found")

    if payload.label is not None:
        item.label = payload.label
    if payload.text_value is not None:
        item.text_value = payload.text_value
    if payload.description is not None:
        item.description = payload.description

    await db.commit()
    await db.refresh(item)
    return _serialize(item)


@router.delete("/{application_id}/{item_id}", status_code=204)
async def delete_dataset_item(
    application_id: str,
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a dataset item (and its file if applicable)."""
    await require_app_access(application_id, current_user, db)
    result = await db.execute(
        select(TestDataset).where(
            TestDataset.id == item_id,
            TestDataset.application_id == application_id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Dataset item not found")

    # Remove file from disk
    if item.file_path and os.path.exists(item.file_path):
        try:
            os.remove(item.file_path)
        except OSError:
            pass

    await db.delete(item)
    await db.commit()
