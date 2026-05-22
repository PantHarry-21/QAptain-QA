from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import User, ExecutionReport, ExecutionRun, Scenario
from app.core.dependencies import get_current_user
from app.schemas.scenario import ReportResponse

router = APIRouter()


@router.get("/applications/{application_id}")
async def list_reports(
    application_id: str,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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
    result = await db.execute(select(ExecutionReport).where(ExecutionReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return ReportResponse.model_validate(report)
