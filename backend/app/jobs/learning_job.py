"""
Learning Job — Improves application memory after each execution.
Runs after a completed execution run to persist learnings.
"""
from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import (
    ExecutionRun, ExecutionStep, ExecutionReport, StepStatus,
    AIMemoryChunk, MemoryKind,
)
from app.memory.chroma_store import get_memory_store

log = structlog.get_logger()


async def process_learning_job(run_id: str):
    """Extract learnings from a completed run and update memory."""
    from app.db.session import AsyncSessionFactory

    async with AsyncSessionFactory() as db:
        learner = ExecutionLearner(db)
        await learner.learn(run_id)


class ExecutionLearner:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.memory = get_memory_store()

    async def learn(self, run_id: str):
        """Extract and persist learnings from a completed run."""
        # Load run data
        run_result = await self.db.execute(select(ExecutionRun).where(ExecutionRun.id == run_id))
        run = run_result.scalar_one_or_none()
        if not run:
            return

        steps_result = await self.db.execute(
            select(ExecutionStep).where(ExecutionStep.run_id == run_id)
        )
        steps = steps_result.scalars().all()

        report_result = await self.db.execute(
            select(ExecutionReport).where(ExecutionReport.run_id == run_id)
        )
        report = report_result.scalar_one_or_none()

        # Build learning content
        passed = [s for s in steps if s.status == StepStatus.PASSED]
        failed = [s for s in steps if s.status == StepStatus.FAILED]
        healed = [s for s in steps if s.status == StepStatus.HEALED]

        learning_lines = [
            f"Run outcome: {run.status.value}",
            f"Steps: {len(steps)} total, {len(passed)} passed, {len(failed)} failed, {len(healed)} healed",
        ]

        if failed:
            learning_lines.append("Failed steps:")
            for step in failed[:10]:
                learning_lines.append(f"  - [{step.action_type}] {step.description}: {step.error_message or 'No error'}")

        if healed:
            learning_lines.append("Self-healed steps (selector recovery):")
            for step in healed[:5]:
                learning_lines.append(f"  - [{step.action_type}] {step.description}")

        if report and report.rca_analysis:
            rca = report.rca_analysis
            if rca.get("overall_health"):
                learning_lines.append(f"Health assessment: {rca['overall_health']}")

        # Get application ID
        from app.db.models import Scenario
        scenario_result = await self.db.execute(select(Scenario).where(Scenario.id == run.scenario_id))
        scenario = scenario_result.scalar_one_or_none()
        if not scenario:
            return

        learning_content = "\n".join(learning_lines)

        # Store in ChromaDB
        self.memory.store_execution_learning(
            application_id=scenario.application_id,
            run_id=run_id,
            scenario_title=scenario.title,
            outcome=run.status.value,
            key_learnings=learning_content,
        )

        # Store in Postgres memory
        chunk = AIMemoryChunk(
            application_id=scenario.application_id,
            kind=MemoryKind.EXECUTION_LEARNING,
            content=learning_content,
            extra={
                "run_id": run_id,
                "scenario_id": scenario.id,
                "passed": len(passed),
                "failed": len(failed),
                "healed": len(healed),
            },
            confidence=0.9,
        )
        self.db.add(chunk)
        await self.db.commit()

        log.info("Learning persisted", run_id=run_id, application_id=scenario.application_id)
