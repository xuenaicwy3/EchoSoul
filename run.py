"""
应用启动入口
使用 uvicorn 运行 FastAPI 工厂函数
"""
import uvicorn
from app.config import Settings

if __name__ == "__main__":
    settings = Settings()
    uvicorn.run(
        "app.main:create_app",
        factory=True,               # 使用工厂模式创建 app
        host=settings.HOST,
        port=settings.PORT,
        reload=True                 # 开发模式热重载
    )