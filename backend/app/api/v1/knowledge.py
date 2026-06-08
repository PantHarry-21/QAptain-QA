from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import User, ApplicationModule, ApplicationPage, ApplicationWorkflow, SemanticElement
from app.core.dependencies import get_current_user

router = APIRouter()


@router.get("/applications/{application_id}/modules")
async def get_modules(
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ApplicationModule)
        .where(ApplicationModule.application_id == application_id)
        .order_by(ApplicationModule.order_index)
    )
    modules = result.scalars().all()
    return [
        {
            "id": m.id,
            "name": m.name,
            "description": m.description,
            "url_pattern": m.url_pattern,
            "icon": m.icon,
            "semantic_tags": m.semantic_tags,
        }
        for m in modules
    ]


@router.get("/modules/{module_id}/pages")
async def get_pages(
    module_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ApplicationPage).where(ApplicationPage.module_id == module_id)
    )
    pages = result.scalars().all()
    return [
        {
            "id": p.id,
            "title": p.title,
            "url": p.url,
            "page_type": p.page_type,
            "semantic_map": p.semantic_map,
            "forms": p.forms,
            "tables": p.tables,
            "dynamic_behaviors": p.dynamic_behaviors,
        }
        for p in pages
    ]


@router.get("/modules/{module_id}/workflows")
async def get_workflows(
    module_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ApplicationWorkflow).where(ApplicationWorkflow.module_id == module_id)
    )
    workflows = result.scalars().all()
    return [
        {
            "id": w.id,
            "name": w.name,
            "description": w.description,
            "workflow_type": w.workflow_type,
            "stages": w.stages,
            "entry_point": w.entry_point,
            "success_indicators": w.success_indicators,
        }
        for w in workflows
    ]
