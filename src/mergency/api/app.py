from fastapi import FastAPI

from mergency.api.internal import router as internal_router
from mergency.api.webhooks import router as webhooks_router


def create_app() -> FastAPI:
    app = FastAPI(title="mergency")
    app.include_router(webhooks_router)
    app.include_router(internal_router)
    return app


app = create_app()
