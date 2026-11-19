from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from . import admin
from .storage import ROOT, Store, data_directory


def create_app(folder=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(folder or data_directory())
        try:
            yield
        finally:
            app.state.store.engine.dispose()

    app = FastAPI(title="Smart Door", lifespan=lifespan)
    app.include_router(admin.router)
    assets = ROOT / "smartdoor" / "web"
    app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(assets / "index.html", headers={"Cache-Control": "no-store"})
    return app


app = create_app()
