from fastapi import FastAPI

from backend.app.api import router
from backend.app.iot_door import router as door_router
from backend.app.config import get_settings
from backend.app.database import create_all


def create_app() -> FastAPI:
    settings = get_settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(
        title="FaceID Demo - Attendance + Experimental IoT Door",
        version="1.0.0-demo",
        description="Điểm danh kế thừa, khóa cửa IoT demo mặc định vô hiệu hóa.",
    )
    app.include_router(router)
    app.include_router(door_router)

    @app.on_event("startup")
    def on_startup() -> None:
        create_all()

    return app


app = create_app()
