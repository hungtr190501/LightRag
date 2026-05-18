"""
WorkspaceManager: manages multiple isolated LightRAG instances, one per workspace.

Each workspace gets its own knowledge graph and vector store, identified by the
'workspace' parameter passed to LightRAG. Metadata (name, description, color) is
persisted to {working_dir}/.workspaces.json. Instances are created lazily and
cached in memory for the server lifetime.
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from lightrag.utils import logger


class WorkspaceManager:
    def __init__(self, working_dir: str, rag_factory: Callable[[str], Any]):
        self._working_dir = Path(working_dir)
        self._factory = rag_factory
        self._instances: dict[str, Any] = {}
        self._meta_path = self._working_dir / ".workspaces.json"
        self._metadata: dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self._load_metadata()

    def _load_metadata(self) -> None:
        if self._meta_path.exists():
            try:
                self._metadata = json.loads(self._meta_path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Failed to load workspace metadata: %s", exc)
                self._metadata = {}

    def _save_metadata(self) -> None:
        try:
            self._working_dir.mkdir(parents=True, exist_ok=True)
            self._meta_path.write_text(
                json.dumps(self._metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.error("Failed to save workspace metadata: %s", exc)

    async def get_rag(self, name: str) -> Any:
        async with self._lock:
            if name not in self._instances:
                logger.info("WorkspaceManager: initializing workspace '%s'", name)
                instance = self._factory(name)
                await instance.initialize_storages()
                await instance.check_and_migrate_data()
                self._instances[name] = instance
                if name not in self._metadata:
                    self._metadata[name] = {
                        "name": name,
                        "description": "",
                        "color": "",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                    self._save_metadata()
            return self._instances[name]

    def get_doc_manager(self, name: str, input_dir: str):
        from lightrag.api.routers.document_routes import DocumentManager

        return DocumentManager(input_dir, workspace=name)

    async def create_workspace(
        self, name: str, description: str = "", color: str = ""
    ) -> dict:
        if name in self._metadata:
            raise ValueError(f"Workspace '{name}' already exists")
        entry = {
            "name": name,
            "description": description,
            "color": color,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._metadata[name] = entry
        self._save_metadata()
        await self.get_rag(name)
        return entry

    def update_workspace(
        self, name: str, description: Optional[str] = None, color: Optional[str] = None
    ) -> dict:
        if name not in self._metadata:
            raise KeyError(f"Workspace '{name}' not found")
        if description is not None:
            self._metadata[name]["description"] = description
        if color is not None:
            self._metadata[name]["color"] = color
        self._save_metadata()
        return self._metadata[name]

    def get_public_chat_config(self, name: str) -> dict:
        meta = self._metadata.get(name)
        if meta is None:
            return {}
        return meta.get("public_chat_config", {})

    def update_public_chat_config(self, name: str, config: dict) -> dict:
        if name not in self._metadata:
            raise KeyError(f"Workspace '{name}' not found")
        self._metadata[name]["public_chat_config"] = config
        self._save_metadata()
        return config

    async def delete_workspace(self, name: str) -> None:
        if name not in self._metadata:
            raise KeyError(f"Workspace '{name}' not found")
        if name in self._instances:
            try:
                await self._instances[name].finalize_storages()
            except Exception as exc:
                logger.warning("Error finalizing workspace '%s': %s", name, exc)
            del self._instances[name]
        del self._metadata[name]
        self._save_metadata()

    def list_workspaces(self) -> list[dict]:
        return list(self._metadata.values())

    def get_workspace_info(self, name: str) -> Optional[dict]:
        return self._metadata.get(name)

    async def initialize_default(self, default_name: str) -> None:
        if default_name not in self._metadata:
            self._metadata[default_name] = {
                "name": default_name,
                "description": "Workspace mặc định",
                "color": "#6366f1",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._save_metadata()
        await self.get_rag(default_name)

    async def finalize_all(self) -> None:
        for name, instance in list(self._instances.items()):
            try:
                await instance.finalize_storages()
                logger.debug("Finalized workspace '%s'", name)
            except Exception as exc:
                logger.warning("Error finalizing workspace '%s': %s", name, exc)
        self._instances.clear()
