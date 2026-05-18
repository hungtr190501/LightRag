"""
Workspace CRUD endpoints. Each workspace is an isolated LightRAG instance with
its own knowledge graph and vector store. Documents uploaded to workspace A are
never retrieved by queries against workspace B.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from lightrag.api.utils_api import get_combined_auth_dependency
from lightrag.api.workspace_manager import WorkspaceManager


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, description="Unique workspace identifier")
    description: str = Field(default="", description="Human-readable description")
    color: str = Field(default="", description="Theme color hex (e.g. #6366f1)")


class WorkspaceUpdateRequest(BaseModel):
    description: Optional[str] = Field(default=None, description="New description")
    color: Optional[str] = Field(default=None, description="New theme color hex")


class WorkspaceInfo(BaseModel):
    name: str
    description: str = ""
    color: str = ""
    created_at: str = ""


class PublicChatConfig(BaseModel):
    title: str = ""
    description: str = ""
    mode: str = "hybrid"
    top_k: int = 40
    suggested_questions: List[str] = []
    accent_color: str = "#10b981"


def create_workspace_routes(workspace_manager: WorkspaceManager, api_key: Optional[str] = None):
    router = APIRouter(prefix="/workspaces", tags=["workspaces"])
    combined_auth = get_combined_auth_dependency(api_key)

    @router.get("", response_model=list[WorkspaceInfo], dependencies=[Depends(combined_auth)])
    async def list_workspaces():
        """List all registered workspaces."""
        return workspace_manager.list_workspaces()

    @router.post("", response_model=WorkspaceInfo, dependencies=[Depends(combined_auth)])
    async def create_workspace(req: WorkspaceCreateRequest):
        """Create a new isolated workspace and initialize its storage."""
        try:
            entry = await workspace_manager.create_workspace(
                name=req.name,
                description=req.description,
                color=req.color,
            )
            return entry
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @router.get("/{name}", response_model=WorkspaceInfo, dependencies=[Depends(combined_auth)])
    async def get_workspace(name: str):
        """Get metadata for a specific workspace."""
        info = workspace_manager.get_workspace_info(name)
        if info is None:
            raise HTTPException(status_code=404, detail=f"Workspace '{name}' not found")
        return info

    @router.patch("/{name}", response_model=WorkspaceInfo, dependencies=[Depends(combined_auth)])
    async def update_workspace(name: str, req: WorkspaceUpdateRequest):
        """Update workspace description or color."""
        try:
            updated = workspace_manager.update_workspace(
                name=name,
                description=req.description,
                color=req.color,
            )
            return updated
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @router.delete("/{name}", dependencies=[Depends(combined_auth)])
    async def delete_workspace(name: str):
        """Remove a workspace from the registry (files are kept on disk)."""
        try:
            await workspace_manager.delete_workspace(name)
            return {"status": "deleted", "name": name}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @router.get("/{name}/public-chat-config", response_model=PublicChatConfig)
    async def get_public_chat_config(name: str):
        """Get public chat configuration for a workspace. No auth required."""
        return workspace_manager.get_public_chat_config(name)

    @router.put("/{name}/public-chat-config", response_model=PublicChatConfig, dependencies=[Depends(combined_auth)])
    async def update_public_chat_config(name: str, config: PublicChatConfig):
        """Update public chat configuration for a workspace. Requires auth."""
        try:
            saved = workspace_manager.update_public_chat_config(name, config.model_dump())
            return saved
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    return router
