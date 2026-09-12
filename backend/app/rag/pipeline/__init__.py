"""Composable RAG pipeline: shared context, ordered steps, one executor."""
from app.rag.pipeline.base import Pipeline, PipelineStep
from app.rag.pipeline.context import RagContext
from app.rag.pipeline.factory import (
    build_rag_pipeline,
    build_retrieval_pipeline,
    get_rag_pipeline,
    get_retrieval_pipeline,
)

__all__ = [
    "Pipeline",
    "PipelineStep",
    "RagContext",
    "build_rag_pipeline",
    "build_retrieval_pipeline",
    "get_rag_pipeline",
    "get_retrieval_pipeline",
]
