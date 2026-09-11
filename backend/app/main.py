"""CPM Ground Installation & Evidence — central backend entrypoint.

Run:   uvicorn app.main:app --reload
Docs:  http://127.0.0.1:8000/docs
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import settings
from .database import Base, SessionLocal, engine
from .errors import ApiError, api_error_handler, http_error_handler, validation_error_handler
from .routers import admin, auth, catalog, evidence, installations, issues, sync
from .seed import seed


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    if settings.seed_on_start:
        with SessionLocal() as db:
            seed(db)
    yield


app = FastAPI(
    title="CPM Ground Installation & Evidence API",
    version=__version__,
    description=(
        "Field-evidence backend for the CPM Ground App. Implements PRD sections 63-75 "
        "(auth, installations, evidence, issues, sync, audit), 88 (scale), 98 (integrity), "
        "99 (audit). Evidence binary lives in object storage; PostgreSQL holds metadata."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(HTTPException, http_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)

_p = settings.api_prefix
app.include_router(auth.router, prefix=_p)
app.include_router(catalog.router, prefix=_p)
app.include_router(installations.router, prefix=_p)
app.include_router(evidence.router, prefix=_p)
app.include_router(issues.router, prefix=_p)
app.include_router(sync.router, prefix=_p)
app.include_router(admin.router, prefix=_p)


@app.get("/", tags=["meta"])
def root():
    return {
        "service": "cpm-ground-backend",
        "version": __version__,
        "environment": settings.environment,
        "api": _p,
        "docs": "/docs",
        "health": "ok",
    }


@app.get(f"{_p}/health", tags=["meta"])
def health():
    return {"status": "ok"}
