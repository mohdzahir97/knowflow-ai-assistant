"""Pipeline executor and the step contract.

Corrective RAG and the guardrail chain are the same shape: an ordered
sequence of operations over shared state, any of which may end the run
early. Implementing that once means each later phase contributes steps
rather than restructuring control flow, and gives one place for timing,
tracing and error handling.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import List, Sequence

from app.core.logging import get_logger, log_extra
from app.core.tracing import get_tracing_client
from app.rag.pipeline.context import RagContext

logger = get_logger("app.rag.pipeline")


class PipelineStep(ABC):
    """One unit of work in a RAG run.

    Steps mutate the context in place and return nothing. They should be
    cheap to construct and hold no per-request state, so a single instance
    can serve concurrent requests.
    """

    #: Stable identifier used for timings, logs and trace span names.
    name: str = "step"

    @abstractmethod
    async def run(self, context: RagContext) -> None:  # pragma: no cover - interface
        ...

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} name={self.name!r}>"


class Pipeline:
    """Runs steps in order, stopping early if one halts the context.

    Timing is recorded per step regardless of outcome, so a failure still
    shows how long it took to fail.
    """

    def __init__(self, steps: Sequence[PipelineStep]) -> None:
        self._steps: List[PipelineStep] = list(steps)

    @property
    def steps(self) -> List[PipelineStep]:
        return list(self._steps)

    async def run(self, context: RagContext) -> RagContext:
        for step in self._steps:
            if context.halted:
                logger.info(
                    "Pipeline halted before step",
                    extra=log_extra(step=step.name, reason=context.halt_reason),
                )
                break

            started = time.perf_counter()
            try:
                await self._run_step(step, context)
            finally:
                context.record_timing(step.name, (time.perf_counter() - started) * 1000)

        return context

    async def _run_step(self, step: PipelineStep, context: RagContext) -> None:
        """Execute one step, wrapped in a trace span when tracing is on.

        The span is created here rather than by decorating each step so that
        every step - including ones added later - is traced automatically,
        and so a step author cannot forget to add it.
        """
        client = get_tracing_client()
        if client is None:
            await step.run(context)
            return

        from langsmith import traceable

        from app.core.config import get_settings

        traced_step = traceable(
            name=f"rag.{step.name}",
            run_type="chain",
            client=client,
            project_name=get_settings().langsmith_project,
        )(step.run)
        await traced_step(context)
