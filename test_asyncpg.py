import asyncio
import asyncpg

async def test():
    try:
        conn = await asyncpg.connect(
            user='echosoul',
            password='123456',
            database='echosoul',
            host='127.0.0.1',
            port=5432,
            ssl=False
        )
        print("连接成功！")
        await conn.close()
    except Exception as e:
        print(f"连接失败: {e}")

asyncio.run(test())