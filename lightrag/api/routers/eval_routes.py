"""Evaluation endpoints — Golden Questions, Benchmark Runs, Failure Cases.

Follows the same router factory pattern as legal_routes.py.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from lightrag.api.utils_api import get_combined_auth_dependency


# ── Request/Response models ──────────────────────────────────────────


class GoldenQuestionCreate(BaseModel):
    question: str = Field(..., description="Vietnamese legal question")
    category: str = Field(default="general", description="Question category")
    difficulty: str = Field(default="medium", description="easy|medium|hard|expert")
    expected_answer: Optional[str] = None
    expected_citations: Optional[list[dict]] = None
    tags: Optional[list[str]] = None
    notes: Optional[str] = None


class GoldenQuestionUpdate(BaseModel):
    question: Optional[str] = None
    category: Optional[str] = None
    difficulty: Optional[str] = None
    expected_answer: Optional[str] = None
    expected_citations: Optional[list[dict]] = None
    tags: Optional[list[str]] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class BenchmarkRunCreate(BaseModel):
    name: str = Field(..., description="Run name, e.g. 'Qwen3-14B baseline v1'")
    description: Optional[str] = None
    config: dict = Field(default_factory=dict, description="PipelineConfig overrides")
    model_info: Optional[dict] = None
    dataset_version: Optional[str] = None


class EvaluateResult(BaseModel):
    is_correct: Optional[int] = Field(None, description="1=correct, 0=wrong")
    citation_valid: Optional[int] = None
    has_hallucination: Optional[int] = None
    evaluator_notes: Optional[str] = None
    evaluated_by: Optional[str] = None


class FailureCaseCreate(BaseModel):
    question: str
    answer: Optional[str] = None
    failure_type: str = Field(..., description="hallucination|wrong_citation|missing_context|wrong_law|...")
    severity: str = Field(default="medium")
    description: Optional[str] = None
    root_cause: Optional[str] = None
    source: str = Field(default="manual")
    run_id: Optional[str] = None
    question_id: Optional[str] = None


class FailureCaseUpdate(BaseModel):
    status: Optional[str] = None
    severity: Optional[str] = None
    description: Optional[str] = None
    root_cause: Optional[str] = None
    resolution: Optional[str] = None


class DatasetVersionCreate(BaseModel):
    name: str
    description: Optional[str] = None
    question_ids: Optional[list[str]] = Field(
        default=None,
        description="Specific question IDs. If empty, snapshots all active questions.",
    )


class GoldenQuestionsImport(BaseModel):
    questions: list[dict] = Field(..., description="Array of question objects")


# ── Router factory ───────────────────────────────────────────────────


def create_eval_routes(api_key: Optional[str] = None):
    router = APIRouter(prefix="/eval", tags=["evaluation"])
    combined_auth = get_combined_auth_dependency(api_key)

    # === Golden Questions ===

    @router.post("/golden-questions", dependencies=[Depends(combined_auth)])
    async def create_golden_question(req: GoldenQuestionCreate):
        manager = _get_eval_manager()
        qid = await manager.db.create_question(req.model_dump(exclude_none=True))
        question = await manager.db.get_question(qid)
        return question

    @router.get("/golden-questions", dependencies=[Depends(combined_auth)])
    async def list_golden_questions(
        category: Optional[str] = None,
        difficulty: Optional[str] = None,
        is_active: Optional[bool] = True,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
    ):
        manager = _get_eval_manager()
        questions, total = await manager.db.list_questions(
            category=category, difficulty=difficulty,
            is_active=is_active, offset=offset, limit=limit,
        )
        return {"items": questions, "total": total, "offset": offset, "limit": limit}

    @router.get("/golden-questions/export", dependencies=[Depends(combined_auth)])
    async def export_golden_questions():
        manager = _get_eval_manager()
        questions, _ = await manager.db.list_questions(is_active=None, limit=100000)
        return {"questions": questions, "count": len(questions)}

    @router.post("/golden-questions/import", dependencies=[Depends(combined_auth)])
    async def import_golden_questions(req: GoldenQuestionsImport):
        manager = _get_eval_manager()
        imported = 0
        errors: list[str] = []
        for q in req.questions:
            try:
                if "question" not in q:
                    errors.append(f"Missing 'question' field in entry")
                    continue
                await manager.db.create_question(q)
                imported += 1
            except Exception as e:
                errors.append(str(e))
        return {"imported": imported, "errors": errors}

    @router.get("/golden-questions/{qid}", dependencies=[Depends(combined_auth)])
    async def get_golden_question(qid: str):
        manager = _get_eval_manager()
        question = await manager.db.get_question(qid)
        if question is None:
            raise HTTPException(status_code=404, detail="Question not found")
        return question

    @router.put("/golden-questions/{qid}", dependencies=[Depends(combined_auth)])
    async def update_golden_question(qid: str, req: GoldenQuestionUpdate):
        manager = _get_eval_manager()
        existing = await manager.db.get_question(qid)
        if existing is None:
            raise HTTPException(status_code=404, detail="Question not found")
        await manager.db.update_question(qid, req.model_dump(exclude_none=True))
        return await manager.db.get_question(qid)

    @router.delete("/golden-questions/{qid}", dependencies=[Depends(combined_auth)])
    async def delete_golden_question(qid: str):
        manager = _get_eval_manager()
        existing = await manager.db.get_question(qid)
        if existing is None:
            raise HTTPException(status_code=404, detail="Question not found")
        await manager.db.delete_question(qid)
        return {"message": "Question deactivated", "id": qid}

    # === Benchmark Runs ===

    @router.post("/benchmark-runs", dependencies=[Depends(combined_auth)])
    async def create_benchmark_run(req: BenchmarkRunCreate):
        manager = _get_eval_manager()
        run_id = await manager.db.create_run(req.model_dump(exclude_none=True))
        return await manager.db.get_run(run_id)

    @router.get("/benchmark-runs", dependencies=[Depends(combined_auth)])
    async def list_benchmark_runs(
        status: Optional[str] = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(20, ge=1, le=100),
    ):
        manager = _get_eval_manager()
        runs, total = await manager.db.list_runs(
            status=status, offset=offset, limit=limit,
        )
        return {"items": runs, "total": total, "offset": offset, "limit": limit}

    @router.get("/benchmark-runs/compare", dependencies=[Depends(combined_auth)])
    async def compare_benchmark_runs(
        a: str = Query(..., description="Run ID A"),
        b: str = Query(..., description="Run ID B"),
    ):
        manager = _get_eval_manager()
        try:
            return await manager.compare_runs(a, b)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @router.get("/benchmark-runs/{run_id}", dependencies=[Depends(combined_auth)])
    async def get_benchmark_run(run_id: str):
        manager = _get_eval_manager()
        run = await manager.db.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    @router.get("/benchmark-runs/{run_id}/results", dependencies=[Depends(combined_auth)])
    async def get_run_results(run_id: str):
        manager = _get_eval_manager()
        run = await manager.db.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        results = await manager.db.get_results_for_run(run_id)
        return {"run": run, "results": results}

    @router.post("/benchmark-runs/{run_id}/start", dependencies=[Depends(combined_auth)])
    async def start_benchmark_run(run_id: str, background_tasks: BackgroundTasks):
        """Start a benchmark run (runs in background)."""
        manager = _get_eval_manager()
        run = await manager.db.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        if run["status"] == "running":
            raise HTTPException(status_code=409, detail="Run is already running")

        background_tasks.add_task(manager.start_benchmark_run, run_id)
        return {"message": "Benchmark run started", "run_id": run_id}

    # === Run Results ===

    @router.put("/run-results/{result_id}/evaluate", dependencies=[Depends(combined_auth)])
    async def evaluate_run_result(result_id: str, req: EvaluateResult):
        manager = _get_eval_manager()
        existing = await manager.db.get_result(result_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Result not found")
        data = req.model_dump(exclude_none=True)
        if data:
            from datetime import datetime, timezone
            data["evaluated_at"] = datetime.now(timezone.utc).isoformat()
        await manager.db.update_result(result_id, data)
        return await manager.db.get_result(result_id)

    # === Failure Cases ===

    @router.post("/failure-cases", dependencies=[Depends(combined_auth)])
    async def create_failure_case(req: FailureCaseCreate):
        manager = _get_eval_manager()
        fid = await manager.db.create_failure(req.model_dump(exclude_none=True))
        return await manager.db.get_failure(fid)

    @router.get("/failure-cases", dependencies=[Depends(combined_auth)])
    async def list_failure_cases(
        status: Optional[str] = None,
        failure_type: Optional[str] = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(20, ge=1, le=100),
    ):
        manager = _get_eval_manager()
        cases, total = await manager.db.list_failures(
            status=status, failure_type=failure_type,
            offset=offset, limit=limit,
        )
        return {"items": cases, "total": total, "offset": offset, "limit": limit}

    @router.get("/failure-cases/{fid}", dependencies=[Depends(combined_auth)])
    async def get_failure_case(fid: str):
        manager = _get_eval_manager()
        case = await manager.db.get_failure(fid)
        if case is None:
            raise HTTPException(status_code=404, detail="Failure case not found")
        return case

    @router.put("/failure-cases/{fid}", dependencies=[Depends(combined_auth)])
    async def update_failure_case(fid: str, req: FailureCaseUpdate):
        manager = _get_eval_manager()
        existing = await manager.db.get_failure(fid)
        if existing is None:
            raise HTTPException(status_code=404, detail="Failure case not found")
        await manager.db.update_failure(fid, req.model_dump(exclude_none=True))
        return await manager.db.get_failure(fid)

    @router.post("/failure-cases/{fid}/convert-to-golden", dependencies=[Depends(combined_auth)])
    async def convert_failure_to_golden(fid: str):
        manager = _get_eval_manager()
        try:
            qid = await manager.convert_failure_to_golden(fid)
            return {"message": "Converted to golden question", "question_id": qid}
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    # === Dataset Versions ===

    @router.post("/dataset-versions", dependencies=[Depends(combined_auth)])
    async def create_dataset_version(req: DatasetVersionCreate):
        manager = _get_eval_manager()
        data = req.model_dump(exclude_none=True)

        # If no question_ids specified, snapshot all active questions
        if not data.get("question_ids"):
            questions, _ = await manager.db.list_questions(is_active=True, limit=100000)
            data["question_ids"] = [q["id"] for q in questions]

        vid = await manager.db.create_dataset_version(data)
        return await manager.db.get_dataset_version(vid)

    @router.get("/dataset-versions", dependencies=[Depends(combined_auth)])
    async def list_dataset_versions():
        manager = _get_eval_manager()
        versions = await manager.db.list_dataset_versions()
        return {"items": versions}

    # === Pipeline Replay ===

    @router.get("/replay/{result_id}", dependencies=[Depends(combined_auth)])
    async def get_pipeline_replay(result_id: str):
        """Return the full pipeline trace for a specific run result.

        The trace is the 14-step audit trail with timings, inputs, and outputs.
        """
        manager = _get_eval_manager()
        result = await manager.db.get_result(result_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Result not found")

        # Load associated question
        question = await manager.db.get_question(result["question_id"])

        return {
            "result_id": result_id,
            "question": question.get("question", "") if question else "",
            "answer": result.get("answer", ""),
            "confidence": result.get("confidence"),
            "latency_ms": result.get("latency_ms"),
            "pipeline_trace": result.get("pipeline_trace", []),
            "retrieved_chunks": result.get("retrieved_chunks", []),
            "citations": result.get("citations", []),
            "error": result.get("error"),
        }

    return router


# ── Lazy singletons ─────────────────────────────────────────────────

_eval_db = None
_eval_manager = None


def set_eval_singletons(eval_db=None, eval_manager=None):
    global _eval_db, _eval_manager
    if eval_db is not None:
        _eval_db = eval_db
    if eval_manager is not None:
        _eval_manager = eval_manager


def _get_eval_manager():
    if _eval_manager is None:
        raise HTTPException(
            status_code=503,
            detail="Evaluation system not initialized. Restart the server.",
        )
    return _eval_manager
