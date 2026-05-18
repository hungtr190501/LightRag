"""Async SQLite database layer for the evaluation platform.

Manages golden questions, benchmark runs, run results,
failure cases, and dataset versions.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import aiosqlite

logger = logging.getLogger(__name__)

# ── Schema ──────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS golden_questions (
    id              TEXT PRIMARY KEY,
    question        TEXT NOT NULL,
    category        TEXT NOT NULL,
    difficulty      TEXT NOT NULL DEFAULT 'medium',
    expected_answer TEXT,
    expected_citations TEXT,
    tags            TEXT,
    notes           TEXT,
    created_by      TEXT DEFAULT 'system',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS benchmark_runs (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    description         TEXT,
    config_json         TEXT NOT NULL,
    model_info          TEXT,
    dataset_version     TEXT,
    status              TEXT NOT NULL DEFAULT 'pending',
    started_at          TEXT,
    completed_at        TEXT,
    total_questions     INTEGER DEFAULT 0,
    completed_questions INTEGER DEFAULT 0,
    accuracy            REAL,
    citation_accuracy   REAL,
    hallucination_rate  REAL,
    avg_latency_ms      REAL,
    avg_confidence      REAL,
    metrics_json        TEXT,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_results (
    id                TEXT PRIMARY KEY,
    run_id            TEXT NOT NULL REFERENCES benchmark_runs(id),
    question_id       TEXT NOT NULL REFERENCES golden_questions(id),
    answer            TEXT,
    confidence        REAL,
    latency_ms        REAL,
    pipeline_trace    TEXT,
    retrieved_chunks  TEXT,
    citations         TEXT,
    is_correct        INTEGER,
    citation_valid    INTEGER,
    has_hallucination INTEGER,
    evaluator_notes   TEXT,
    evaluated_by      TEXT,
    evaluated_at      TEXT,
    error             TEXT,
    created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_run_results_run ON run_results(run_id);
CREATE INDEX IF NOT EXISTS idx_run_results_question ON run_results(question_id);

CREATE TABLE IF NOT EXISTS failure_cases (
    id                  TEXT PRIMARY KEY,
    source              TEXT NOT NULL,
    question            TEXT NOT NULL,
    answer              TEXT,
    failure_type        TEXT NOT NULL,
    severity            TEXT DEFAULT 'medium',
    description         TEXT,
    root_cause          TEXT,
    pipeline_trace      TEXT,
    run_id              TEXT,
    question_id         TEXT,
    status              TEXT DEFAULT 'open',
    resolution          TEXT,
    converted_to_golden INTEGER DEFAULT 0,
    created_by          TEXT DEFAULT 'system',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dataset_versions (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    question_ids    TEXT NOT NULL,
    question_count  INTEGER NOT NULL,
    created_by      TEXT DEFAULT 'system',
    created_at      TEXT NOT NULL
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


def _row_to_dict(row: aiosqlite.Row, columns: list[str]) -> dict[str, Any]:
    """Convert an aiosqlite Row to a dict, decoding JSON fields."""
    d = dict(zip(columns, row))
    # Decode JSON fields
    for key in ("expected_citations", "tags", "config_json", "model_info",
                "metrics_json", "pipeline_trace", "retrieved_chunks",
                "citations", "question_ids"):
        if key in d and d[key] is not None:
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


class EvalDatabase:
    """Async SQLite database for evaluation data."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def initialize(self):
        """Create DB file + tables if not exist."""
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA_SQL)
        await self._db.commit()
        logger.info("EvalDatabase initialized at %s", self._db_path)

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None

    # ── Golden Questions CRUD ────────────────────────────────────────

    async def create_question(self, data: dict) -> str:
        qid = data.get("id") or _new_id()
        now = _now_iso()
        await self._db.execute(
            """INSERT INTO golden_questions
               (id, question, category, difficulty, expected_answer,
                expected_citations, tags, notes, created_by, created_at, updated_at, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                qid,
                data["question"],
                data.get("category", "general"),
                data.get("difficulty", "medium"),
                data.get("expected_answer"),
                json.dumps(data.get("expected_citations"), ensure_ascii=False)
                if data.get("expected_citations") else None,
                json.dumps(data.get("tags"), ensure_ascii=False)
                if data.get("tags") else None,
                data.get("notes"),
                data.get("created_by", "system"),
                now,
                now,
                1 if data.get("is_active", True) else 0,
            ),
        )
        await self._db.commit()
        return qid

    async def get_question(self, qid: str) -> Optional[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM golden_questions WHERE id = ?", (qid,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        cols = [desc[0] for desc in cursor.description]
        return _row_to_dict(row, cols)

    async def list_questions(
        self,
        category: Optional[str] = None,
        difficulty: Optional[str] = None,
        is_active: Optional[bool] = True,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict], int]:
        conditions: list[str] = []
        params: list[Any] = []

        if is_active is not None:
            conditions.append("is_active = ?")
            params.append(1 if is_active else 0)
        if category:
            conditions.append("category = ?")
            params.append(category)
        if difficulty:
            conditions.append("difficulty = ?")
            params.append(difficulty)

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        # Count
        cursor = await self._db.execute(
            f"SELECT COUNT(*) FROM golden_questions{where}", params
        )
        total = (await cursor.fetchone())[0]

        # Fetch page
        cursor = await self._db.execute(
            f"SELECT * FROM golden_questions{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        )
        cols = [desc[0] for desc in cursor.description]
        rows = await cursor.fetchall()
        return [_row_to_dict(r, cols) for r in rows], total

    async def update_question(self, qid: str, data: dict) -> bool:
        fields: list[str] = []
        params: list[Any] = []

        for key in ("question", "category", "difficulty", "expected_answer",
                     "notes", "created_by"):
            if key in data:
                fields.append(f"{key} = ?")
                params.append(data[key])

        for key in ("expected_citations", "tags"):
            if key in data:
                fields.append(f"{key} = ?")
                params.append(json.dumps(data[key], ensure_ascii=False) if data[key] else None)

        if "is_active" in data:
            fields.append("is_active = ?")
            params.append(1 if data["is_active"] else 0)

        if not fields:
            return False

        fields.append("updated_at = ?")
        params.append(_now_iso())
        params.append(qid)

        await self._db.execute(
            f"UPDATE golden_questions SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        await self._db.commit()
        return True

    async def delete_question(self, qid: str) -> bool:
        """Soft-delete a golden question."""
        await self._db.execute(
            "UPDATE golden_questions SET is_active = 0, updated_at = ? WHERE id = ?",
            (_now_iso(), qid),
        )
        await self._db.commit()
        return True

    # ── Benchmark Runs ──────────────────────────────────────────────

    async def create_run(self, data: dict) -> str:
        run_id = data.get("id") or _new_id()
        now = _now_iso()
        await self._db.execute(
            """INSERT INTO benchmark_runs
               (id, name, description, config_json, model_info,
                dataset_version, status, total_questions, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                data["name"],
                data.get("description"),
                json.dumps(data.get("config", {}), ensure_ascii=False),
                json.dumps(data.get("model_info"), ensure_ascii=False)
                if data.get("model_info") else None,
                data.get("dataset_version"),
                data.get("status", "pending"),
                data.get("total_questions", 0),
                now,
            ),
        )
        await self._db.commit()
        return run_id

    async def get_run(self, run_id: str) -> Optional[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM benchmark_runs WHERE id = ?", (run_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        cols = [desc[0] for desc in cursor.description]
        return _row_to_dict(row, cols)

    async def list_runs(
        self,
        status: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[dict], int]:
        conditions: list[str] = []
        params: list[Any] = []

        if status:
            conditions.append("status = ?")
            params.append(status)

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        cursor = await self._db.execute(
            f"SELECT COUNT(*) FROM benchmark_runs{where}", params
        )
        total = (await cursor.fetchone())[0]

        cursor = await self._db.execute(
            f"SELECT * FROM benchmark_runs{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        )
        cols = [desc[0] for desc in cursor.description]
        rows = await cursor.fetchall()
        return [_row_to_dict(r, cols) for r in rows], total

    async def update_run(self, run_id: str, data: dict) -> bool:
        fields: list[str] = []
        params: list[Any] = []

        for key in ("name", "description", "status", "started_at", "completed_at",
                     "total_questions", "completed_questions",
                     "accuracy", "citation_accuracy", "hallucination_rate",
                     "avg_latency_ms", "avg_confidence"):
            if key in data:
                fields.append(f"{key} = ?")
                params.append(data[key])

        for key in ("config_json", "model_info", "metrics_json"):
            if key in data:
                fields.append(f"{key} = ?")
                params.append(json.dumps(data[key], ensure_ascii=False) if data[key] else None)

        if not fields:
            return False

        params.append(run_id)
        await self._db.execute(
            f"UPDATE benchmark_runs SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        await self._db.commit()
        return True

    # ── Run Results ─────────────────────────────────────────────────

    async def create_result(self, data: dict) -> str:
        result_id = data.get("id") or _new_id()
        now = _now_iso()
        await self._db.execute(
            """INSERT INTO run_results
               (id, run_id, question_id, answer, confidence, latency_ms,
                pipeline_trace, retrieved_chunks, citations, error, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                result_id,
                data["run_id"],
                data["question_id"],
                data.get("answer"),
                data.get("confidence"),
                data.get("latency_ms"),
                json.dumps(data.get("pipeline_trace"), ensure_ascii=False)
                if data.get("pipeline_trace") else None,
                json.dumps(data.get("retrieved_chunks"), ensure_ascii=False)
                if data.get("retrieved_chunks") else None,
                json.dumps(data.get("citations"), ensure_ascii=False)
                if data.get("citations") else None,
                data.get("error"),
                now,
            ),
        )
        await self._db.commit()
        return result_id

    async def get_result(self, result_id: str) -> Optional[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM run_results WHERE id = ?", (result_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        cols = [desc[0] for desc in cursor.description]
        return _row_to_dict(row, cols)

    async def get_results_for_run(self, run_id: str) -> list[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM run_results WHERE run_id = ? ORDER BY created_at",
            (run_id,),
        )
        cols = [desc[0] for desc in cursor.description]
        rows = await cursor.fetchall()
        return [_row_to_dict(r, cols) for r in rows]

    async def get_results_for_question(self, question_id: str) -> list[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM run_results WHERE question_id = ? ORDER BY created_at DESC",
            (question_id,),
        )
        cols = [desc[0] for desc in cursor.description]
        rows = await cursor.fetchall()
        return [_row_to_dict(r, cols) for r in rows]

    async def update_result(self, result_id: str, data: dict) -> bool:
        fields: list[str] = []
        params: list[Any] = []

        for key in ("is_correct", "citation_valid", "has_hallucination",
                     "evaluator_notes", "evaluated_by", "evaluated_at"):
            if key in data:
                fields.append(f"{key} = ?")
                params.append(data[key])

        if not fields:
            return False

        params.append(result_id)
        await self._db.execute(
            f"UPDATE run_results SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        await self._db.commit()
        return True

    # ── Failure Cases ───────────────────────────────────────────────

    async def create_failure(self, data: dict) -> str:
        fid = data.get("id") or _new_id()
        now = _now_iso()
        await self._db.execute(
            """INSERT INTO failure_cases
               (id, source, question, answer, failure_type, severity,
                description, root_cause, pipeline_trace, run_id, question_id,
                status, created_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                fid,
                data.get("source", "manual"),
                data["question"],
                data.get("answer"),
                data["failure_type"],
                data.get("severity", "medium"),
                data.get("description"),
                data.get("root_cause"),
                json.dumps(data.get("pipeline_trace"), ensure_ascii=False)
                if data.get("pipeline_trace") else None,
                data.get("run_id"),
                data.get("question_id"),
                data.get("status", "open"),
                data.get("created_by", "system"),
                now,
                now,
            ),
        )
        await self._db.commit()
        return fid

    async def get_failure(self, fid: str) -> Optional[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM failure_cases WHERE id = ?", (fid,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        cols = [desc[0] for desc in cursor.description]
        return _row_to_dict(row, cols)

    async def list_failures(
        self,
        status: Optional[str] = None,
        failure_type: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[dict], int]:
        conditions: list[str] = []
        params: list[Any] = []

        if status:
            conditions.append("status = ?")
            params.append(status)
        if failure_type:
            conditions.append("failure_type = ?")
            params.append(failure_type)

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        cursor = await self._db.execute(
            f"SELECT COUNT(*) FROM failure_cases{where}", params
        )
        total = (await cursor.fetchone())[0]

        cursor = await self._db.execute(
            f"SELECT * FROM failure_cases{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        )
        cols = [desc[0] for desc in cursor.description]
        rows = await cursor.fetchall()
        return [_row_to_dict(r, cols) for r in rows], total

    async def update_failure(self, fid: str, data: dict) -> bool:
        fields: list[str] = []
        params: list[Any] = []

        for key in ("status", "severity", "description", "root_cause",
                     "resolution", "converted_to_golden"):
            if key in data:
                fields.append(f"{key} = ?")
                params.append(data[key])

        if not fields:
            return False

        fields.append("updated_at = ?")
        params.append(_now_iso())
        params.append(fid)

        await self._db.execute(
            f"UPDATE failure_cases SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        await self._db.commit()
        return True

    # ── Dataset Versions ────────────────────────────────────────────

    async def create_dataset_version(self, data: dict) -> str:
        vid = data.get("id") or _new_id()
        now = _now_iso()
        question_ids = data.get("question_ids", [])
        await self._db.execute(
            """INSERT INTO dataset_versions
               (id, name, description, question_ids, question_count, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                vid,
                data["name"],
                data.get("description"),
                json.dumps(question_ids, ensure_ascii=False),
                len(question_ids),
                data.get("created_by", "system"),
                now,
            ),
        )
        await self._db.commit()
        return vid

    async def list_dataset_versions(self) -> list[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM dataset_versions ORDER BY created_at DESC"
        )
        cols = [desc[0] for desc in cursor.description]
        rows = await cursor.fetchall()
        return [_row_to_dict(r, cols) for r in rows]

    async def get_dataset_version(self, vid: str) -> Optional[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM dataset_versions WHERE id = ?", (vid,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        cols = [desc[0] for desc in cursor.description]
        return _row_to_dict(row, cols)
