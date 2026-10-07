import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.api.openapi import build_openapi
from app.api.ws.spring_session import LinkState, run_spring_session
from app.core.config import get_settings

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    state = LinkState()
    task = asyncio.create_task(run_spring_session(settings, state))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Bori 2Layer",
    lifespan=lifespan,
    swagger_ui_parameters={"tryItOutEnabled": False},
)


def custom_openapi() -> dict:
    if app.openapi_schema:
        return app.openapi_schema
    app.openapi_schema = build_openapi()
    return app.openapi_schema


app.openapi = custom_openapi

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
