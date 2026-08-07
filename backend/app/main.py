from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import CORS_ORIGINS, DEFAULT_QUARTER, FRONTEND_DIST
from .db import init_db
from .routers import audit, reports, snapshots, users


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


@app.get("/api/health")
def health():
    return {"status": "ok", "default_quarter": DEFAULT_QUARTER, "ui_bundled": _ui_ready}


# Mounted last so it never shadows /api. Absent during frontend development, where
# Vite serves the UI on 5173 and proxies API calls here.
_ui_ready = (FRONTEND_DIST / "index.html").is_file()
if _ui_ready:
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="ui")
