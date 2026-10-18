from fastapi import FastAPI
from pydantic import BaseModel

from alexia_api import __version__


class Health(BaseModel):
    status: str
    version: str


def create_app() -> FastAPI:
    app = FastAPI(title="alexia-familia-api", version=__version__)

    @app.get("/healthz", tags=["health"], summary="Report that the process is alive")
    async def healthz() -> Health:
        return Health(status="ok", version=__version__)

    return app
