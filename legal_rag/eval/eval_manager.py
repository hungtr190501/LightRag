"""Evaluation Manager — orchestrates benchmark runs, metrics, and failure tracking.

Reuses the existing Legal RAG pipeline directly (no duplication).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from legal_rag.eval.database import EvalDatabase

if TYPE_CHECKING:
    from legal_rag.graph.builder import LegalGraphBuilder
    from legal_rag.storage.qdrant_storage import QdrantLegalVectorStorage
    from lightrag import LightRAG

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvalManager:
    """Orchestrates benchmark runs, metrics computation, and failure tracking."""

    def __init__(
        self,
        db: EvalDatabase,
        qdrant: Optional["QdrantLegalVectorStorage"] = None,
        rag: Optional["LightRAG"] = None,
        graph_builder: Optional["LegalGraphBuilder"] = None,
    ):
        self._db = db
        self._qdrant = qdrant
        self._rag = rag
        self._graph_builder = graph_builder

    @property
    def db(self) -> EvalDatabase:
        return self._db

    # ── Benchmark Execution ──────────────────────────────────────────

    async def start_benchmark_run(self, run_id: str) -> None:
        """Execute all questions in a benchmark run against the pipeline.

        Runs sequentially to avoid overloading vLLM. Updates progress
        in DB after each question.
        """
        run = await self._db.get_run(run_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")
        if run["status"] not in ("pending", "failed"):
            raise ValueError(f"Run {run_id} status is '{run['status']}', expected 'pending' or 'failed'")

        # Determine which questions to run
        question_ids = await self._resolve_question_ids(run)
        if not question_ids:
            raise ValueError("No questions to run (dataset empty or all inactive)")

        # Build PipelineConfig from run's config_json
        from legal_rag.query.models import PipelineConfig

        config_data = run.get("config_json", {})
        if isinstance(config_data, str):
            config_data = json.loads(config_data)
        config = PipelineConfig(**{
            k: v for k, v in config_data.items()
            if k in PipelineConfig.__dataclass_fields__
        })

        # Update run status
        await self._db.update_run(run_id, {
            "status": "running",
            "started_at": _now_iso(),
            "total_questions": len(question_ids),
            "completed_questions": 0,
        })

        completed = 0
        errors = 0

        for qid in question_ids:
            question = await self._db.get_question(qid)
            if question is None:
                logger.warning("Question %s not found, skipping", qid)
                continue

            try:
                result = await self.execute_single_question(question, config)
                await self._db.create_result({
                    "run_id": run_id,
                    "question_id": qid,
                    **result,
                })
            except Exception as e:
                logger.error("Pipeline failed for question %s: %s", qid, e)
                await self._db.create_result({
                    "run_id": run_id,
                    "question_id": qid,
                    "error": str(e),
                })
                errors += 1

            completed += 1
            await self._db.update_run(run_id, {"completed_questions": completed})

        # Compute aggregate metrics
        metrics = await self.compute_run_metrics(run_id)

        await self._db.update_run(run_id, {
            "status": "completed" if errors < len(question_ids) else "failed",
            "completed_at": _now_iso(),
            "metrics_json": metrics,
            **{k: v for k, v in metrics.items()
               if k in ("accuracy", "citation_accuracy", "hallucination_rate",
                         "avg_latency_ms", "avg_confidence")},
        })

        logger.info(
            "Benchmark run %s completed: %d/%d questions, %d errors",
            run_id, completed, len(question_ids), errors,
        )

    async def execute_single_question(
        self,
        question: dict,
        config: "PipelineConfig",
    ) -> dict:
        """Run one question through the pipeline, capture full trace."""
        from legal_rag.query import legal_query

        start = time.time()
        result = await legal_query(
            question=question["question"],
            config=config,
            qdrant=self._qdrant,
            rag=self._rag,
            graph_builder=self._graph_builder,
        )
        latency_ms = (time.time() - start) * 1000

        result_dict = result.to_dict()

        # Extract chunk summaries (don't store full text for each chunk)
        chunk_summaries = []
        for c in result_dict.get("retrieved_chunks", []):
            chunk_summaries.append({
                "chunk_id": c.get("chunk_id", ""),
                "doc_number": c.get("doc_number", ""),
                "article": c.get("article"),
                "score": c.get("score", 0),
                "source": c.get("source", ""),
                "text_preview": c.get("text", "")[:200],
            })

        # Auto-evaluate using pipeline's own metrics
        has_hallucination = None
        citation_valid = None
        claim_verif = result_dict.get("metadata", {}).get("claim_verification")
        if claim_verif and isinstance(claim_verif, dict):
            overall_conf = claim_verif.get("overall_confidence", 0)
            has_hallucination = 1 if overall_conf < 0.7 else 0

        cit_valid = result_dict.get("metadata", {}).get("citation_validation")
        if cit_valid and isinstance(cit_valid, dict):
            invalid = cit_valid.get("invalid_count", 0)
            citation_valid = 1 if invalid == 0 else 0

        return {
            "answer": result_dict.get("answer", ""),
            "confidence": result_dict.get("confidence", 0),
            "latency_ms": latency_ms,
            "pipeline_trace": result_dict.get("audit_trail", []),
            "retrieved_chunks": chunk_summaries,
            "citations": result_dict.get("citations", []),
            "has_hallucination": has_hallucination,
            "citation_valid": citation_valid,
        }

    # ── Metrics Computation ──────────────────────────────────────────

    async def compute_run_metrics(self, run_id: str) -> dict:
        """Compute aggregate metrics for a completed run."""
        results = await self._db.get_results_for_run(run_id)

        if not results:
            return {
                "accuracy": 0.0,
                "citation_accuracy": 0.0,
                "hallucination_rate": 0.0,
                "avg_latency_ms": 0.0,
                "avg_confidence": 0.0,
            }

        total = len(results)
        evaluated = [r for r in results if r.get("is_correct") is not None]
        correct = sum(1 for r in evaluated if r.get("is_correct") == 1)
        errored = sum(1 for r in results if r.get("error"))

        # Citation accuracy
        cit_evaluated = [r for r in results if r.get("citation_valid") is not None]
        cit_valid = sum(1 for r in cit_evaluated if r.get("citation_valid") == 1)

        # Hallucination rate
        hall_evaluated = [r for r in results if r.get("has_hallucination") is not None]
        hall_count = sum(1 for r in hall_evaluated if r.get("has_hallucination") == 1)

        # Latency and confidence
        latencies = [r["latency_ms"] for r in results if r.get("latency_ms")]
        confidences = [r["confidence"] for r in results if r.get("confidence")]

        # Category breakdown
        category_stats: dict[str, dict] = {}
        for r in results:
            q = await self._db.get_question(r["question_id"])
            if q is None:
                continue
            cat = q.get("category", "unknown")
            if cat not in category_stats:
                category_stats[cat] = {
                    "total": 0, "correct": 0, "evaluated": 0,
                    "latencies": [], "confidences": [],
                }
            stats = category_stats[cat]
            stats["total"] += 1
            if r.get("is_correct") is not None:
                stats["evaluated"] += 1
                if r["is_correct"] == 1:
                    stats["correct"] += 1
            if r.get("latency_ms"):
                stats["latencies"].append(r["latency_ms"])
            if r.get("confidence"):
                stats["confidences"].append(r["confidence"])

        # Format category stats
        for cat, stats in category_stats.items():
            stats["accuracy"] = (
                stats["correct"] / stats["evaluated"]
                if stats["evaluated"] > 0 else None
            )
            stats["avg_latency_ms"] = (
                sum(stats["latencies"]) / len(stats["latencies"])
                if stats["latencies"] else None
            )
            stats["avg_confidence"] = (
                sum(stats["confidences"]) / len(stats["confidences"])
                if stats["confidences"] else None
            )
            # Remove raw lists from output
            del stats["latencies"]
            del stats["confidences"]

        return {
            "accuracy": correct / len(evaluated) if evaluated else None,
            "citation_accuracy": cit_valid / len(cit_evaluated) if cit_evaluated else None,
            "hallucination_rate": hall_count / len(hall_evaluated) if hall_evaluated else None,
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else None,
            "avg_confidence": sum(confidences) / len(confidences) if confidences else None,
            "total_questions": total,
            "evaluated_count": len(evaluated),
            "correct_count": correct,
            "error_count": errored,
            "by_category": category_stats,
        }

    # ── Failure Case Management ──────────────────────────────────────

    async def create_failure_from_result(
        self,
        result_id: str,
        failure_type: str,
        description: str,
        severity: str = "medium",
    ) -> str:
        """Convert a bad run result into a tracked failure case."""
        result = await self._db.get_result(result_id)
        if result is None:
            raise ValueError(f"Result {result_id} not found")

        question = await self._db.get_question(result["question_id"])
        question_text = question["question"] if question else ""

        return await self._db.create_failure({
            "source": "benchmark",
            "question": question_text,
            "answer": result.get("answer"),
            "failure_type": failure_type,
            "severity": severity,
            "description": description,
            "pipeline_trace": result.get("pipeline_trace"),
            "run_id": result.get("run_id"),
            "question_id": result.get("question_id"),
        })

    async def convert_failure_to_golden(self, failure_id: str) -> str:
        """Promote a failure case to a golden question for regression testing."""
        failure = await self._db.get_failure(failure_id)
        if failure is None:
            raise ValueError(f"Failure {failure_id} not found")

        # Map failure_type to appropriate category
        type_to_category = {
            "hallucination": "hallucination_defense",
            "wrong_citation": "citation_validation",
            "missing_context": "exact_retrieval",
            "wrong_law": "temporal_reasoning",
            "conflict_missed": "conflict_detection",
        }
        category = type_to_category.get(failure["failure_type"], "general")

        qid = await self._db.create_question({
            "question": failure["question"],
            "category": category,
            "difficulty": "hard",  # failures are typically hard cases
            "notes": f"Converted from failure case {failure_id}. "
                     f"Type: {failure['failure_type']}. "
                     f"Description: {failure.get('description', '')}",
            "created_by": "system:failure_conversion",
        })

        await self._db.update_failure(failure_id, {
            "converted_to_golden": 1,
            "status": "resolved",
            "resolution": f"Converted to golden question {qid}",
        })

        return qid

    # ── Run Comparison ───────────────────────────────────────────────

    async def compare_runs(self, run_id_a: str, run_id_b: str) -> dict:
        """Side-by-side comparison of two benchmark runs."""
        run_a = await self._db.get_run(run_id_a)
        run_b = await self._db.get_run(run_id_b)
        if run_a is None or run_b is None:
            raise ValueError("One or both runs not found")

        results_a = await self._db.get_results_for_run(run_id_a)
        results_b = await self._db.get_results_for_run(run_id_b)

        # Index by question_id
        a_by_q = {r["question_id"]: r for r in results_a}
        b_by_q = {r["question_id"]: r for r in results_b}

        all_qids = set(a_by_q.keys()) | set(b_by_q.keys())

        per_question: list[dict] = []
        improved = 0
        degraded = 0
        unchanged = 0

        for qid in all_qids:
            ra = a_by_q.get(qid)
            rb = b_by_q.get(qid)

            question = await self._db.get_question(qid)
            q_text = question["question"][:100] if question else "?"

            entry: dict[str, Any] = {
                "question_id": qid,
                "question_preview": q_text,
            }

            if ra and rb:
                conf_a = ra.get("confidence", 0) or 0
                conf_b = rb.get("confidence", 0) or 0
                entry["confidence_a"] = conf_a
                entry["confidence_b"] = conf_b
                entry["latency_a"] = ra.get("latency_ms")
                entry["latency_b"] = rb.get("latency_ms")
                entry["correct_a"] = ra.get("is_correct")
                entry["correct_b"] = rb.get("is_correct")

                if conf_b > conf_a + 0.05:
                    entry["change"] = "improved"
                    improved += 1
                elif conf_a > conf_b + 0.05:
                    entry["change"] = "degraded"
                    degraded += 1
                else:
                    entry["change"] = "unchanged"
                    unchanged += 1
            elif ra and not rb:
                entry["change"] = "only_in_a"
            else:
                entry["change"] = "only_in_b"

            per_question.append(entry)

        # Aggregate comparison
        metrics_a = await self.compute_run_metrics(run_id_a)
        metrics_b = await self.compute_run_metrics(run_id_b)

        return {
            "run_a": {"id": run_id_a, "name": run_a.get("name", ""), "metrics": metrics_a},
            "run_b": {"id": run_id_b, "name": run_b.get("name", ""), "metrics": metrics_b},
            "summary": {
                "total_questions": len(all_qids),
                "improved": improved,
                "degraded": degraded,
                "unchanged": unchanged,
            },
            "per_question": per_question,
        }

    # ── Private helpers ──────────────────────────────────────────────

    async def _resolve_question_ids(self, run: dict) -> list[str]:
        """Resolve which question IDs to use for a benchmark run."""
        dataset_version_id = run.get("dataset_version")

        if dataset_version_id:
            ds = await self._db.get_dataset_version(dataset_version_id)
            if ds and ds.get("question_ids"):
                return ds["question_ids"]

        # No dataset version — use all active questions
        questions, _ = await self._db.list_questions(is_active=True, limit=10000)
        return [q["id"] for q in questions]
