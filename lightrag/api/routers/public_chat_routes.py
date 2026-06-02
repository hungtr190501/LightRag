"""
Public Chat session management.

Sessions are stored per-workspace in {working_dir}/.pcsessions_{workspace}.json.
Read/write/feedback endpoints are unauthenticated (public users).
Delete requires auth (admin only).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from lightrag.api.utils_api import get_combined_auth_dependency
from lightrag.utils import logger


# ── Data models ───────────────────────────────────────────────────────────────

class MessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    references: Optional[List[Dict[str, Any]]] = None


class FeedbackIn(BaseModel):
    feedback: Optional[Literal["like", "dislike"]] = None


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    timestamp: str
    feedback: Optional[str] = None
    references: Optional[List[Dict[str, Any]]] = None


class SessionSummary(BaseModel):
    id: str
    workspace: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    like_count: int
    dislike_count: int


class SessionDetail(SessionSummary):
    messages: List[MessageOut]


class SessionCreateResponse(BaseModel):
    id: str
    title: str
    created_at: str


# ── File-based store ──────────────────────────────────────────────────────────

def _sessions_path(working_dir: str, workspace: str) -> Path:
    safe = workspace.replace("/", "_").replace("..", "_")
    return Path(working_dir) / f".pcsessions_{safe}.json"


def _load(path: Path) -> Dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load sessions from %s: %s", path, exc)
    return {}


def _save(path: Path, data: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.error("Failed to save sessions to %s: %s", path, exc)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _auto_title(messages: List[Dict[str, Any]]) -> str:
    for m in messages:
        if m.get("role") == "user" and m.get("content"):
            text = m["content"].strip()
            return (text[:60] + "…") if len(text) > 60 else text
    return "Cuộc trò chuyện mới"


def _summary(session: Dict[str, Any]) -> SessionSummary:
    msgs = session.get("messages", [])
    likes = sum(1 for m in msgs if m.get("feedback") == "like")
    dislikes = sum(1 for m in msgs if m.get("feedback") == "dislike")
    return SessionSummary(
        id=session["id"],
        workspace=session["workspace"],
        title=session["title"],
        created_at=session["created_at"],
        updated_at=session["updated_at"],
        message_count=len(msgs),
        like_count=likes,
        dislike_count=dislikes,
    )


# ── Document helpers ──────────────────────────────────────────────────────────

class PublicDocumentItem(BaseModel):
    id: str
    file_path: str
    status: str
    chunks_count: Optional[int] = None
    created_at: str
    content_summary: str


class PublicWorkspaceItem(BaseModel):
    name: str
    title: str
    description: str
    accent_color: str


def _doc_status_path(working_dir: str, workspace: str) -> Path:
    return Path(working_dir) / workspace / "kv_store_doc_status.json"


def _workspaces_path(working_dir: str) -> Path:
    return Path(working_dir) / ".workspaces.json"


# ── Router factory ────────────────────────────────────────────────────────────

def create_public_chat_routes(working_dir: str, api_key: Optional[str] = None, workspace_manager=None) -> APIRouter:
    router = APIRouter(prefix="/public-chat", tags=["public-chat"])
    combined_auth = get_combined_auth_dependency(api_key)

    # ── Public workspace list ─────────────────────────────────────────────────

    @router.get("/workspaces", response_model=List[PublicWorkspaceItem])
    async def list_public_workspaces():
        """List workspaces that have a public chat config set up."""
        ws_file = _workspaces_path(working_dir)
        if not ws_file.exists():
            return []
        try:
            data: Dict[str, Any] = json.loads(ws_file.read_text(encoding="utf-8"))
        except Exception:
            return []
        result = []
        for ws_name, ws_data in data.items():
            cfg = ws_data.get("public_chat_config", {})
            if cfg:
                result.append(PublicWorkspaceItem(
                    name=ws_name,
                    title=cfg.get("title") or ws_name,
                    description=cfg.get("description", ""),
                    accent_color=cfg.get("accent_color", "#10b981"),
                ))
        return result

    # ── Public document list ──────────────────────────────────────────────────

    @router.get("/{workspace}/documents", response_model=List[PublicDocumentItem])
    async def list_workspace_documents(workspace: str):
        """List indexed documents for a workspace (public, read-only)."""
        doc_file = _doc_status_path(working_dir, workspace)
        if not doc_file.exists():
            return []
        try:
            data: Dict[str, Any] = json.loads(doc_file.read_text(encoding="utf-8"))
        except Exception:
            return []
        items = []
        for doc_id, doc in data.items():
            summary = doc.get("content_summary", "") or ""
            items.append(PublicDocumentItem(
                id=doc_id,
                file_path=doc.get("file_path", ""),
                status=doc.get("status", ""),
                chunks_count=doc.get("chunks_count"),
                created_at=doc.get("created_at", ""),
                content_summary=summary,
            ))
        return sorted(items, key=lambda x: x.created_at, reverse=True)

    # ── Public knowledge graph ─────────────────────────────────────────────────

    @router.get("/{workspace}/graph")
    async def get_workspace_graph(
        workspace: str,
        max_nodes: int = Query(300, ge=1, le=3000),
        max_depth: int = Query(3, ge=1, le=5),
    ):
        """Return knowledge graph data for a workspace (public, read-only)."""
        if workspace_manager is None:
            raise HTTPException(status_code=503, detail="Graph not available")
        try:
            rag = await workspace_manager.get_rag(workspace)
            graph = await rag.get_knowledge_graph(
                node_label="*", max_depth=max_depth, max_nodes=max_nodes
            )
            return graph
        except Exception as exc:
            logger.error("Error getting graph for workspace '%s': %s", workspace, exc)
            raise HTTPException(status_code=500, detail=str(exc))

    # ── List sessions ─────────────────────────────────────────────────────────

    @router.get("/{workspace}/sessions", response_model=List[SessionSummary])
    async def list_sessions(workspace: str):
        path = _sessions_path(working_dir, workspace)
        data = _load(path)
        summaries = [_summary(s) for s in data.values()]
        summaries.sort(key=lambda s: s.updated_at, reverse=True)
        return summaries

    # ── Create session ────────────────────────────────────────────────────────

    @router.post("/{workspace}/sessions", response_model=SessionCreateResponse)
    async def create_session(workspace: str):
        path = _sessions_path(working_dir, workspace)
        data = _load(path)
        sid = str(uuid.uuid4())
        now = _now()
        session: Dict[str, Any] = {
            "id": sid,
            "workspace": workspace,
            "title": "Cuộc trò chuyện mới",
            "created_at": now,
            "updated_at": now,
            "messages": [],
        }
        data[sid] = session
        _save(path, data)
        return SessionCreateResponse(id=sid, title=session["title"], created_at=now)

    # ── Get session ───────────────────────────────────────────────────────────

    @router.get("/{workspace}/sessions/{session_id}", response_model=SessionDetail)
    async def get_session(workspace: str, session_id: str):
        path = _sessions_path(working_dir, workspace)
        data = _load(path)
        session = data.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        s = _summary(session)
        return SessionDetail(
            **s.model_dump(),
            messages=[MessageOut(**m) for m in session.get("messages", [])],
        )

    # ── Delete session (auth required) ────────────────────────────────────────

    @router.delete("/{workspace}/sessions/{session_id}", dependencies=[Depends(combined_auth)])
    async def delete_session(workspace: str, session_id: str):
        path = _sessions_path(working_dir, workspace)
        data = _load(path)
        if session_id not in data:
            raise HTTPException(status_code=404, detail="Session not found")
        del data[session_id]
        _save(path, data)
        return {"status": "deleted", "id": session_id}

    # ── Append message ────────────────────────────────────────────────────────

    @router.post("/{workspace}/sessions/{session_id}/messages", response_model=MessageOut)
    async def add_message(workspace: str, session_id: str, msg: MessageIn):
        path = _sessions_path(working_dir, workspace)
        data = _load(path)
        session = data.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        mid = str(uuid.uuid4())
        now = _now()
        message: Dict[str, Any] = {
            "id": mid,
            "role": msg.role,
            "content": msg.content,
            "timestamp": now,
            "feedback": None,
            "references": msg.references,
        }
        session["messages"].append(message)
        session["updated_at"] = now

        # Auto-title from first user message
        if session["title"] == "Cuộc trò chuyện mới":
            session["title"] = _auto_title(session["messages"])

        _save(path, data)
        return MessageOut(**message)

    # ── Feedback ──────────────────────────────────────────────────────────────

    @router.patch("/{workspace}/sessions/{session_id}/messages/{message_id}/feedback",
                  response_model=MessageOut)
    async def set_feedback(workspace: str, session_id: str, message_id: str, body: FeedbackIn):
        path = _sessions_path(working_dir, workspace)
        data = _load(path)
        session = data.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        for m in session["messages"]:
            if m["id"] == message_id:
                # Toggle: same value clears the feedback
                m["feedback"] = None if m.get("feedback") == body.feedback else body.feedback
                session["updated_at"] = _now()
                _save(path, data)
                return MessageOut(**m)

        raise HTTPException(status_code=404, detail="Message not found")

    return router
