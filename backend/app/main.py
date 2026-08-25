from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import CORS_ORIGINS, DEFAULT_QUARTER, FRONTEND_DIST
from .db import init_db
from .routers import analyzer, audit, reports, snapshots, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Backlog Report Platform", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(reports.router)
app.include_router(snapshots.router)
app.include_router(users.router)
app.include_router(audit.router)
app.include_router(analyzer.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "default_quarter": DEFAULT_QUARTER, "ui_bundled": _ui_ready}


@app.middleware("http")
async def ui_cache_headers(request: Request, call_next):
    """Stop browsers serving a stale index.html after the UI is rebuilt.

    StaticFiles sends an ETag but no Cache-Control, so browsers fall back to
    heuristic freshness and reuse index.html without revalidating. That HTML names
    the previous hashed bundle, which is also cached, so a rebuilt UI never reaches
    anyone. The entry point must always be revalidated; the hashed assets carry
    their content in their name and can be cached forever.
    """
    response = await call_next(request)
    path = request.url.path
    if not path.startswith("/api"):
        if path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


# Mounted last so it never shadows /api. Absent during frontend development, where
# Vite serves the UI on 5173 and proxies API calls here.
_ui_ready = (FRONTEND_DIST / "index.html").is_file()
if _ui_ready:
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="ui")
