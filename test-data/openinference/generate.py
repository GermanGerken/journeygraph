"""Emit deterministic offline OpenInference scenarios through standard OTLP/HTTP."""

from __future__ import annotations

import argparse
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass

from openinference.instrumentation import OITracer, TraceConfig
from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import IdGenerator, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode

BASE_TIME_NS = 1_767_225_600_000_000_000


class DeterministicIdGenerator(IdGenerator):
    """Generate valid stable IDs; fixtures are demo data, never production identifiers."""

    def __init__(self) -> None:
        self._trace_id = 0x10000000000000000000000000000000
        self._span_id = 0x1000000000000000

    def generate_trace_id(self) -> int:
        self._trace_id += 1
        return self._trace_id

    def generate_span_id(self) -> int:
        self._span_id += 1
        return self._span_id


@dataclass(frozen=True)
class Clock:
    scenario_offset_ms: int

    def ns(self, offset_ms: int) -> int:
        return BASE_TIME_NS + (self.scenario_offset_ms + offset_ms) * 1_000_000


@contextmanager
def active_span(
    tracer: OITracer,
    clock: Clock,
    name: str,
    oi_kind: OpenInferenceSpanKindValues,
    start_ms: int,
    end_ms: int,
    attributes: Mapping[str, str | int] | None = None,
    *,
    error: bool = False,
) -> Iterator[object]:
    span = tracer.start_span(
        name,
        kind=SpanKind.INTERNAL,
        attributes=attributes,
        start_time=clock.ns(start_ms),
        openinference_span_kind=oi_kind,
    )
    with trace.use_span(span, end_on_exit=False):
        if error:
            span.set_status(Status(StatusCode.ERROR))
        yield span
    span.end(end_time=clock.ns(end_ms))


def _agent_attributes(name: str, scenario: str) -> dict[str, str]:
    return {
        SpanAttributes.AGENT_NAME: name,
        "journeygraph.scenario": scenario,
    }


def simple_llm(tracer: OITracer, clock: Clock) -> None:
    with active_span(
        tracer,
        clock,
        "simple-llm-workflow",
        OpenInferenceSpanKindValues.AGENT,
        0,
        100,
        _agent_attributes("planner", "simple-llm"),
    ) as root:
        root.set_input({"private": "removed-at-source"})
        root.set_attribute("journeygraph.outcome", "success")
        with active_span(
            tracer,
            clock,
            "offline-model",
            OpenInferenceSpanKindValues.LLM,
            10,
            70,
            {
                SpanAttributes.LLM_MODEL_NAME: "offline-model-v1",
                SpanAttributes.LLM_TOKEN_COUNT_PROMPT: 11,
                SpanAttributes.LLM_TOKEN_COUNT_COMPLETION: 5,
            },
        ) as llm:
            llm.set_output({"private": "removed-at-source"})


def one_tool(tracer: OITracer, clock: Clock) -> None:
    with active_span(
        tracer,
        clock,
        "single-tool-workflow",
        OpenInferenceSpanKindValues.AGENT,
        0,
        140,
        _agent_attributes("operator", "single-tool"),
    ) as root:
        root.set_attribute("journeygraph.outcome", "success")
        with active_span(
            tracer,
            clock,
            "select-route",
            OpenInferenceSpanKindValues.LLM,
            10,
            45,
            {SpanAttributes.LLM_MODEL_NAME: "offline-model-v1"},
        ):
            pass
        with active_span(
            tracer,
            clock,
            "lookup-tool",
            OpenInferenceSpanKindValues.TOOL,
            55,
            110,
            {SpanAttributes.TOOL_NAME: "catalog-lookup"},
        ) as tool:
            tool.set_tool(name="catalog-lookup", parameters={"private": "removed-later"})


def multiple_tools(tracer: OITracer, clock: Clock) -> None:
    with active_span(
        tracer,
        clock,
        "parallel-tools-workflow",
        OpenInferenceSpanKindValues.AGENT,
        0,
        180,
        _agent_attributes("coordinator", "multiple-tools"),
    ) as root:
        root.set_attribute("journeygraph.outcome", "success")
        # These are siblings with overlapping lifetimes. Timestamp sorting may make them
        # adjacent, but they do not form a parent-child control-flow edge.
        with active_span(
            tracer,
            clock,
            "inventory-tool",
            OpenInferenceSpanKindValues.TOOL,
            30,
            120,
            {SpanAttributes.TOOL_NAME: "inventory-check"},
        ):
            pass
        with active_span(
            tracer,
            clock,
            "policy-tool",
            OpenInferenceSpanKindValues.TOOL,
            40,
            95,
            {SpanAttributes.TOOL_NAME: "policy-check"},
        ):
            pass


def tool_failure(tracer: OITracer, clock: Clock) -> None:
    with active_span(
        tracer,
        clock,
        "failed-tool-workflow",
        OpenInferenceSpanKindValues.AGENT,
        0,
        120,
        _agent_attributes("operator", "tool-error"),
    ) as root:
        root.set_attribute("journeygraph.outcome", "failure")
        with active_span(
            tracer,
            clock,
            "unstable-tool",
            OpenInferenceSpanKindValues.TOOL,
            25,
            80,
            {SpanAttributes.TOOL_NAME: "unstable-service"},
            error=True,
        ):
            pass


def retry_then_success(tracer: OITracer, clock: Clock) -> None:
    with active_span(
        tracer,
        clock,
        "retry-workflow",
        OpenInferenceSpanKindValues.AGENT,
        0,
        180,
        _agent_attributes("operator", "retry"),
    ) as root:
        root.set_attribute("journeygraph.outcome", "success")
        with active_span(
            tracer,
            clock,
            "retryable-tool",
            OpenInferenceSpanKindValues.TOOL,
            20,
            70,
            {SpanAttributes.TOOL_NAME: "retryable-service"},
            error=True,
        ):
            pass
        with active_span(
            tracer,
            clock,
            "retryable-tool",
            OpenInferenceSpanKindValues.TOOL,
            90,
            140,
            {SpanAttributes.TOOL_NAME: "retryable-service"},
        ):
            pass


def agent_handoff(tracer: OITracer, clock: Clock) -> None:
    with active_span(
        tracer,
        clock,
        "handoff-workflow",
        OpenInferenceSpanKindValues.AGENT,
        0,
        160,
        _agent_attributes("triage-agent", "handoff"),
    ) as root:
        root.set_attribute("journeygraph.outcome", "handoff")
        with active_span(
            tracer,
            clock,
            "specialist-agent",
            OpenInferenceSpanKindValues.AGENT,
            50,
            130,
            _agent_attributes("specialist-agent", "handoff"),
        ):
            pass


def incomplete_workflow(tracer: OITracer, clock: Clock) -> None:
    # Exporters cannot emit a span that was never ended. This trace models a captured workflow
    # that stopped after its last observed step and deliberately has no business outcome.
    with (
        active_span(
            tracer,
            clock,
            "incomplete-workflow",
            OpenInferenceSpanKindValues.AGENT,
            0,
            100,
            _agent_attributes("planner", "incomplete"),
        ),
        active_span(
            tracer,
            clock,
            "last-observed-step",
            OpenInferenceSpanKindValues.CHAIN,
            20,
            65,
        ),
    ):
        pass


SCENARIOS = (
    simple_llm,
    one_tool,
    multiple_tools,
    tool_failure,
    retry_then_success,
    agent_handoff,
    incomplete_workflow,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--endpoint",
        default="http://127.0.0.1:4318/v1/traces",
        help="local OTLP/HTTP traces endpoint",
    )
    args = parser.parse_args()

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "journeygraph-openinference-demo",
                "service.version": "1.0.0",
                "deployment.environment.name": "fixture",
            }
        ),
        id_generator=DeterministicIdGenerator(),
    )
    provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint=args.endpoint)))
    trace.set_tracer_provider(provider)
    tracer = OITracer(
        trace.get_tracer("journeygraph.openinference.fixture", "1.0.0"),
        TraceConfig(
            hide_llm_invocation_parameters=True,
            hide_llm_tools=True,
            hide_inputs=True,
            hide_outputs=True,
            hide_input_messages=True,
            hide_output_messages=True,
            hide_input_text=True,
            hide_output_text=True,
            hide_prompts=True,
            hide_choices=True,
        ),
    )
    for index, scenario in enumerate(SCENARIOS):
        scenario(tracer, Clock(index * 1_000))
    provider.shutdown()
    print(f"exported {len(SCENARIOS)} offline instrumented scenarios")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
