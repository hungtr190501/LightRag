"""Golden Questions Management System — Evaluation Platform for Legal RAG.

Provides benchmark management, failure tracking, and pipeline replay
for systematic quality measurement of the Legal RAG pipeline.
"""
from legal_rag.eval.database import EvalDatabase
from legal_rag.eval.eval_manager import EvalManager

__all__ = [
    "EvalDatabase",
    "EvalManager",
]
