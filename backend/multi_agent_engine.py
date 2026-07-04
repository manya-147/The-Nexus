"""
multi_agent_engine.py
----------------------
Multi-Agent Engine for THE NEXUS.

Orchestrates a pipeline where a user task is decomposed and routed to
multiple specialised agents in sequence.  Each agent produces an
intermediate output that the next agent can build on, and a Supervisor
synthesises the final result.

Architecture
────────────
  User Task
     │
     ▼
  Supervisor  ──► decomposes task into sub-tasks with agent assignments
     │
     ├──► Agent-1 (e.g. Research)  ──► sub-result-1
     ├──► Agent-2 (e.g. Coding)    ──► sub-result-2  (can see sub-result-1)
     └──► Agent-N  …
     │
     ▼
  Supervisor  ──► synthesises all sub-results into final response

The engine works with Ollama when available, and falls back to the
rule-based responder so it always produces *something* useful.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from chat_fallback import fallback_response
from ollama_service import generate_response

# ─────────────────────────────────────────────────────────────────────────────
#  Available agent roster
# ─────────────────────────────────────────────────────────────────────────────

AGENT_ROSTER = {
    "research": {
        "name": "Research Agent",
        "icon": "🔍",
        "description": "Deep research, summarisation and fact-finding",
        "color": "#CCFBF1",
    },
    "coding": {
        "name": "Coding Agent",
        "icon": "💻",
        "description": "Code generation, debugging and architecture",
        "color": "#EDE9FE",
    },
    "marketing": {
        "name": "Marketing Agent",
        "icon": "📈",
        "description": "Campaign copy, growth tactics and messaging",
        "color": "#DCFCE7",
    },
    "support": {
        "name": "Support Agent",
        "icon": "🎧",
        "description": "Customer support, triage and escalation",
        "color": "#FEF3C7",
    },
    "analytics": {
        "name": "Analytics Agent",
        "icon": "📊",
        "description": "Data analysis, metrics and reporting",
        "color": "#FEE2E2",
    },
    "writer": {
        "name": "Writer Agent",
        "icon": "✍️",
        "description": "Long-form content, docs and summaries",
        "color": "#E0F2FE",
    },
}

SUPERVISOR_PERSONA = (
    "You are the Supervisor inside THE NEXUS multi-agent engine. "
    "Your role is to: (1) break a user task into focused sub-tasks and assign each "
    "to the best specialist agent, or (2) synthesise sub-results from multiple agents "
    "into a clear, actionable final answer. "
    "Be concise, structured and direct."
)

# ─────────────────────────────────────────────────────────────────────────────
#  Task decomposition helpers
# ─────────────────────────────────────────────────────────────────────────────

TASK_KEYWORDS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(research|find\s+info|look\s+up|background)\b", re.I), "research"),
    (re.compile(r"\b(code|build|implement|program|debug|script)\b", re.I), "coding"),
    (re.compile(r"\b(market|campaign|ad\s*copy|outreach|audience)\b", re.I), "marketing"),
    (re.compile(r"\b(support|ticket|issue|troubleshoot|customer)\b", re.I), "support"),
    (re.compile(r"\b(analyti\w*|metrics|data|report|dashboard)\b", re.I), "analytics"),
    (re.compile(r"\b(write|draft|document|summary|blog|article)\b", re.I), "writer"),
]


def _detect_agents(task: str) -> list[str]:
    """Return an ordered list of agent keys that best match the task (≥1, ≤3)."""
    found: list[str] = []
    for pattern, key in TASK_KEYWORDS:
        if pattern.search(task) and key not in found:
            found.append(key)
        if len(found) == 3:
            break
    # Always have at least one agent
    return found or ["research"]


def _supervisor_decompose(task: str) -> list[dict]:
    """
    Ask the Supervisor (via Ollama) to decompose the task.
    Returns a list of {"agent": key, "sub_task": str}.
    Falls back to keyword detection + the original task if Ollama fails.
    """
    prompt = (
        f"{SUPERVISOR_PERSONA}\n\n"
        f"User task: {task}\n\n"
        "Decompose this into 2-4 focused sub-tasks. "
        "Assign each to one of: research, coding, marketing, support, analytics, writer. "
        "Reply ONLY with a JSON array like: "
        '[{"agent":"research","sub_task":"..."},{"agent":"coding","sub_task":"..."}]'
    )

    try:
        raw = generate_response("research", prompt, [])
        if raw:
            # Strip markdown fences if present
            clean = re.sub(r"```(?:json)?|```", "", raw).strip()
            # Extract first JSON array
            m = re.search(r"\[.*\]", clean, re.DOTALL)
            if m:
                data = json.loads(m.group())
                valid = [
                    d for d in data
                    if isinstance(d, dict) and d.get("agent") in AGENT_ROSTER and d.get("sub_task")
                ]
                if valid:
                    return valid
    except Exception:
        pass

    # Fallback: keyword-based decomposition
    agents = _detect_agents(task)
    if len(agents) == 1:
        return [{"agent": agents[0], "sub_task": task}]
    # Split task roughly between detected agents
    return [{"agent": a, "sub_task": f"{task} — focus on the {AGENT_ROSTER[a]['name'].replace(' Agent','')} aspects"} for a in agents]


# ─────────────────────────────────────────────────────────────────────────────
#  Per-agent execution
# ─────────────────────────────────────────────────────────────────────────────

def _run_agent(agent: str, sub_task: str, prior_context: str = "") -> str:
    """Run a single agent on its sub-task, optionally aware of prior context."""
    ctx = f"\nContext from previous agents:\n{prior_context}\n\n" if prior_context else ""
    full_prompt = f"{ctx}Task: {sub_task}"

    history = [{"role": "user", "content": full_prompt}] if prior_context else []

    try:
        reply = generate_response(agent, sub_task if not prior_context else full_prompt, history)
        if reply:
            return reply
    except Exception:
        pass

    return fallback_response(agent, sub_task)


# ─────────────────────────────────────────────────────────────────────────────
#  Final synthesis
# ─────────────────────────────────────────────────────────────────────────────

def _supervisor_synthesise(task: str, steps: list[dict]) -> str:
    """Synthesise sub-results into a final answer."""
    if len(steps) == 1:
        return steps[0]["result"]

    context_parts = []
    for s in steps:
        agent_label = AGENT_ROSTER.get(s["agent"], {}).get("name", s["agent"])
        context_parts.append(f"### {agent_label}\n{s['result']}")
    context = "\n\n".join(context_parts)

    prompt = (
        f"{SUPERVISOR_PERSONA}\n\n"
        f"Original user task: {task}\n\n"
        f"Sub-results from specialist agents:\n{context}\n\n"
        "Synthesise these into a single, well-structured final response for the user. "
        "Be concise and actionable."
    )

    try:
        reply = generate_response("research", prompt, [])
        if reply:
            return reply
    except Exception:
        pass

    # Fallback: combine results manually
    lines = [f"**{AGENT_ROSTER.get(s['agent'],{}).get('name', s['agent'])}**\n{s['result']}" for s in steps]
    return "\n\n---\n\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────────────────────

def run_multi_agent_task(task: str) -> dict:
    """
    Orchestrate a full multi-agent run for `task`.

    Returns:
        {
          "task": str,
          "steps": [{"agent": str, "agent_name": str, "icon": str, "sub_task": str, "result": str}],
          "final_answer": str,
          "agents_used": [str],
          "created_at": str (ISO),
        }
    """
    task = (task or "").strip()
    if not task:
        return {"error": "Task cannot be empty"}

    # 1. Decompose
    sub_tasks = _supervisor_decompose(task)

    # 2. Execute agents sequentially, passing prior context forward
    steps: list[dict] = []
    prior_context = ""

    for st in sub_tasks:
        agent_key = st["agent"]
        sub_task_text = st["sub_task"]

        result = _run_agent(agent_key, sub_task_text, prior_context)
        step = {
            "agent": agent_key,
            "agent_name": AGENT_ROSTER.get(agent_key, {}).get("name", agent_key),
            "icon": AGENT_ROSTER.get(agent_key, {}).get("icon", "🤖"),
            "sub_task": sub_task_text,
            "result": result,
        }
        steps.append(step)
        prior_context += f"\n{step['agent_name']}: {result}\n"

    # 3. Synthesise
    final_answer = _supervisor_synthesise(task, steps)

    return {
        "task": task,
        "steps": steps,
        "final_answer": final_answer,
        "agents_used": [s["agent"] for s in steps],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
