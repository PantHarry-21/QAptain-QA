from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import User, Application, Environment, Credential, ApplicationModule
from app.core.dependencies import get_current_user
from app.core.security import encrypt_credential
from app.schemas.workspace import ApplicationResponse, EnvironmentResponse

router = APIRouter()


@router.get("/{application_id}", response_model=ApplicationResponse)
async def get_application(
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Application).where(Application.id == application_id))
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return ApplicationResponse.model_validate(app)


@router.get("/{application_id}/environments", response_model=list[EnvironmentResponse])
async def list_environments(
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Environment).where(Environment.application_id == application_id)
    )
    return [EnvironmentResponse.model_validate(e) for e in result.scalars().all()]


@router.get("/{application_id}/modules")
async def list_modules(
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ApplicationModule)
        .where(ApplicationModule.application_id == application_id)
        .where(ApplicationModule.parent_id == None)
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
            "semantic_tags": m.semantic_tags or [],
        }
        for m in modules
    ]


class ApplicationSettingsUpdate(BaseModel):
    description: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


@router.patch("/{application_id}/settings")
async def update_application_settings(
    application_id: str,
    payload: ApplicationSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Application).where(Application.id == application_id))
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    if payload.description is not None:
        app.description = payload.description

    if payload.username or payload.password:
        cred_result = await db.execute(
            select(Credential).where(Credential.application_id == application_id).limit(1)
        )
        cred = cred_result.scalar_one_or_none()
        if cred:
            if payload.username:
                cred.username = payload.username
            if payload.password:
                cred.password_encrypted = encrypt_credential(payload.password)
        else:
            if payload.username and payload.password:
                cred = Credential(
                    application_id=application_id,
                    username=payload.username,
                    password_encrypted=encrypt_credential(payload.password),
                )
                db.add(cred)

    await db.commit()
    return {"status": "ok"}
