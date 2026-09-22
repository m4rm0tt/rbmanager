"""Chat -> édition de config -> nouveau plan (PROJECT_CONTEXT.md §13-14). Ne
touche jamais la bibliothèque directement."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import state
from app.chat.rules import interpret
from app.library.service import analyze_library

router = APIRouter(prefix="/api/library", tags=["chat"])


class ChatMessage(BaseModel):
    message: str


@router.post("/{library_id}/chat")
def chat(library_id: str, body: ChatMessage):
    try:
        adapter = state.get_adapter(library_id)
    except state.LibraryNotFoundError as exc:
        raise HTTPException(404, "Bibliothèque introuvable.") from exc

    config = state.get_config(library_id)
    resultat = interpret(body.message, config)
    state.set_config(library_id, resultat.config)

    analyse = analyze_library(adapter, state.classification_repo, state.researcher, resultat.config)
    return {
        "understood": resultat.understood,
        "action": resultat.action,
        "explanation": resultat.explanation,
        "plan": analyse.plan.to_dict(),
    }
