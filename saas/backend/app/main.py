"""Point d'entrée FastAPI — voir ARCHITECTURE.md §2 pour la vue d'ensemble."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.routes import artists, chat, config, library

app = FastAPI(title="DJ Library Auto-Organizer", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(library.router)
app.include_router(artists.router)
app.include_router(chat.router)
app.include_router(config.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if _FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
