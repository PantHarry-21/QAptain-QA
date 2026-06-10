from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import User, ExecutionReport, ExecutionRun, Scenario
from app.core.dependencies import get_current_user, require_app_access, require_run_access
from app.schemas.scenario import ReportResponse

router = APIRouter()


@router.get("/applications/{application_id}")
async def list_reports(
    application_id: str,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_app_access(application_id, current_user, db)
    result = await db.execute(
        select(ExecutionReport, ExecutionRun, Scenario)
        .join(ExecutionRun, ExecutionReport.run_id == ExecutionRun.id)
        .join(Scenario, ExecutionRun.scenario_id == Scenario.id)
        .where(Scenario.application_id == application_id)
        .order_by(ExecutionReport.created_at.desc())
        .limit(limit)
    )
    rows = result.all()
    return [
        {
            "id": report.id,
            "run_id": report.run_id,
            "scenario_title": scenario.title,
            "scenario_id": scenario.id,
            "risk_level": report.risk_level.value if report.risk_level else None,
            "quality_score": report.quality_score,
            "summary": report.summary,
            "created_at": report.created_at,
            "run_status": run.status.value if run.status else None,
        }
        for report, run, scenario in rows
    ]


@router.get("/{report_id}", response_model=ReportResponse)
async def get_report(
    report_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ExecutionReport, ExecutionRun.scenario_id)
        .join(ExecutionRun, ExecutionReport.run_id == ExecutionRun.id)
        .where(ExecutionReport.id == report_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    report, scenario_id = row
    scenario_row = await db.execute(select(Scenario).where(Scenario.id == scenario_id))
    scenario = scenario_row.scalar_one_or_none()
    if scenario:
        await require_app_access(scenario.application_id, current_user, db)
    return ReportResponse.model_validate(report)
