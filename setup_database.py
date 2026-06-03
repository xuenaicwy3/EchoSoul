# setup_database.py
import asyncio
from app.database import init_db, close_db
from app.config import Settings

async def main():
    settings = Settings()
    await init_db(settings)
    await close_db()

if __name__ == "__main__":
    asyncio.run(main())