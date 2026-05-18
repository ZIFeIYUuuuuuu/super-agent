"""Local portfolio eval harness for Super Agent.

The harness uses the deterministic planner/retrieval reviewer so it can run
without external model, database, Redis, or vector-store credentials.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from langchain_core.messages import HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm import DeterministicToolCallingLLM


@dataclass(frozen=True)
class EvalCase:
    name: str
    question: str
    chunks: list[dict[str, object]]
    expected_answer_terms: list[str]


@dataclass(frozen=True)
class EvalResult:
    case: str
    latency_ms: float
    rag_hit: bool
    agent_success: bool


CASES = [
    EvalCase(
        name="exact_private_fact",
        question="From the private knowledge base, what is the launch date?",
        chunks=[
            {
                "chunk_text": "Launch date: 2031-09-17",
                "rerank_score": 0.91,
                "filename": "private-brief.md",
                "chunk_index": 0,
            }
        ],
        expected_answer_terms=["2031-09-17", "private-brief.md#chunk-0"],
    ),
    EvalCase(
        name="multi_fact_answer",
        question="From the private knowledge base, what are the launch date and security phrase?",
        chunks=[
            {
                "chunk_text": "Program code: ORBIT-ABC123\nLaunch date: 2031-09-17",
                "rerank_score": 0.91,
                "filename": "brief-a.md",
                "chunk_index": 0,
            },
            {
                "chunk_text": "Security phrase: cobalt-harbor-1a2b3c4d",
                "rerank_score": 0.88,
                "filename": "brief-b.md",
                "chunk_index": 1,
            },
        ],
        expected_answer_terms=["2031-09-17", "cobalt-harbor-1a2b3c4d", "brief-a.md#chunk-0", "brief-b.md#chunk-1"],
    ),
    EvalCase(
        name="partial_evidence_gap",
        question="From the private knowledge base, what are the launch date and security phrase?",
        chunks=[
            {
                "chunk_text": "Launch date: 2031-09-17",
                "rerank_score": 0.91,
                "filename": "brief-a.md",
                "chunk_index": 0,
            }
        ],
        expected_answer_terms=["2031-09-17", "Missing reliable evidence for: security phrase"],
    ),
]


def run_eval() -> dict[str, object]:
    llm = DeterministicToolCallingLLM(available_tool_names={"mcp_web_search"}, tool_definitions=[])
    results: list[EvalResult] = []

    for case in CASES:
        start = time.perf_counter()
        decision = llm.invoke([HumanMessage(content=case.question)], retrieved_chunks=case.chunks)
        latency_ms = (time.perf_counter() - start) * 1000
        answer = decision.answer or ""
        rag_hit = any(float(chunk.get("rerank_score", 0)) >= 0.80 for chunk in case.chunks)
        agent_success = decision.next_step == "emit_answer" and all(term in answer for term in case.expected_answer_terms)
        results.append(
            EvalResult(
                case=case.name,
                latency_ms=round(latency_ms, 2),
                rag_hit=rag_hit,
                agent_success=agent_success,
            )
        )

    latencies = [result.latency_ms for result in results]
    summary = {
        "case_count": len(results),
        "latency_p50_ms": round(statistics.median(latencies), 2),
        "latency_p95_ms": round(max(latencies), 2),
        "rag_hit_rate": round(sum(result.rag_hit for result in results) / len(results), 4),
        "agent_success_rate": round(sum(result.agent_success for result in results) / len(results), 4),
        "report_generation_time_s": None,
        "estimated_eval_cost_usd": 0.0,
        "results": [asdict(result) for result in results],
    }
    return summary


if __name__ == "__main__":
    print(json.dumps(run_eval(), indent=2, ensure_ascii=False))
