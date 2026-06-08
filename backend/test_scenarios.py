import asyncio
import logging
from app.db.session import AsyncSessionFactory
from app.explore.explore_engine import ExploreEngine
from app.db.models import Application
from sqlalchemy import select

logging.basicConfig(level=logging.INFO)

async def main():
    async with AsyncSessionFactory() as db:
        engine = ExploreEngine(db)
        app_id = "12a75ad4-a30f-4470-88da-6bb44be3b504"
        session_id = "aa3e59a8-cd3e-471d-8163-5f850b53c71c"
        engine._session_id = session_id
        engine._app = await db.scalar(select(Application).where(Application.id == app_id))
        print("Starting test scenario generation...")
        try:
            res = await engine._generate_test_scenarios(app_id, session_id)
            print(f"Result: {res}")
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()

asyncio.run(main())
