"""
workflow_service.py
--------------------
Workflow persistence & execution engine for THE NEXUS.

A Workflow is a named, ordered sequence of steps. Each step is assigned to an
agent and has an optional prompt template. Workflows can be:
  - created / read / updated / deleted (CRUD via SQLAlchemy)
  - run manually   → run_workflow(workflow_id, user_id, input_text)
  - scheduled      → stored cron expression, evaluated at execution time

The engine executes steps in order, passing each step's result as context
to the next step (the same "prior context" chaining used by the multi-agent
engine). A WorkflowRun record is created for each execution and each step's
output is stored in WorkflowStepResult.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, Integer, String, Text, ForeignKey
from sqlalchemy.orm import Session

from model import Base
from database import SessionLocal
from ollama_service import generate_response
from chat_fallback import fallback_response

# ─────────────────────────────────────────────────────────────────────────────
#  DB Models
# ─────────────────────────────────────────────────────────────────────────────

class Workflow(Base):
    __tablename__ = "workflows"

    id          = Column(Integer, primary_key=True)
    user_id     = Column(Integer, nullable=False)
    name        = Column(String, nullable=False)
    description = Column(String, default="")
    steps       = Column(Text, default="[]")   # JSON: [{agent, prompt_template, label}]
    trigger     = Column(String, default="manual")  # manual | schedule
    schedule    = Column(String, nullable=True)      # cron expression if scheduled
    status      = Column(String, default="Draft")    # Draft | Active | Paused
    run_count   = Column(Integer, default=0)
    last_run    = Column(String, nullable=True)
    created_at  = Column(String, nullable=False)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id          = Column(Integer, primary_key=True)
    workflow_id = Column(Integer, nullable=False)
    user_id     = Column(Integer, nullable=False)
    status      = Column(String, default="running")  # running | success | failed
    input_text  = Column(Text, default="")
    final_output= Column(Text, default="")
    step_results= Column(Text, default="[]")  # JSON list of step outputs
    started_at  = Column(String, nullable=False)
    finished_at = Column(String, nullable=True)


# ─────────────────────────────────────────────────────────────────────────────
#  CRUD helpers
# ─────────────────────────────────────────────────────────────────────────────

def create_workflow(user_id: int, name: str, description: str,
                    steps: list[dict], trigger: str = "manual",
                    schedule: str | None = None) -> Workflow:
    db = SessionLocal()
    wf = Workflow(
        user_id=user_id,
        name=name,
        description=description,
        steps=json.dumps(steps),
        trigger=trigger,
        schedule=schedule,
        status="Draft",
        run_count=0,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


def get_workflows(user_id: int) -> list[Workflow]:
    db = SessionLocal()
    return (
        db.query(Workflow)
        .filter(Workflow.user_id == user_id)
        .order_by(Workflow.id.desc())
        .all()
    )


def get_workflow(workflow_id: int, user_id: int) -> Optional[Workflow]:
    db = SessionLocal()
    return (
        db.query(Workflow)
        .filter(Workflow.id == workflow_id, Workflow.user_id == user_id)
        .first()
    )


def update_workflow(workflow_id: int, user_id: int, **fields) -> Optional[Workflow]:
    db = SessionLocal()
    wf = db.query(Workflow).filter(
        Workflow.id == workflow_id, Workflow.user_id == user_id
    ).first()
    if not wf:
        return None
    allowed = {"name", "description", "steps", "trigger", "schedule", "status"}
    for k, v in fields.items():
        if k in allowed:
            setattr(wf, k, json.dumps(v) if k == "steps" else v)
    db.commit()
    db.refresh(wf)
    return wf


def delete_workflow(workflow_id: int, user_id: int) -> bool:
    db = SessionLocal()
    wf = db.query(Workflow).filter(
        Workflow.id == workflow_id, Workflow.user_id == user_id
    ).first()
    if not wf:
        return False
    db.delete(wf)
    db.commit()
    return True


def get_workflow_runs(workflow_id: int, user_id: int) -> list[WorkflowRun]:
    db = SessionLocal()
    return (
        db.query(WorkflowRun)
        .filter(WorkflowRun.workflow_id == workflow_id, WorkflowRun.user_id == user_id)
        .order_by(WorkflowRun.id.desc())
        .limit(20)
        .all()
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Execution engine
# ─────────────────────────────────────────────────────────────────────────────

def run_workflow(workflow_id: int, user_id: int, input_text: str = "") -> dict:
    """
    Execute a workflow and return a result dict.
    Each step's result is passed as context to the next step.
    """
    db = SessionLocal()
    wf = db.query(Workflow).filter(
        Workflow.id == workflow_id, Workflow.user_id == user_id
    ).first()

    if not wf:
        return {"success": False, "message": "Workflow not found"}

    steps = json.loads(wf.steps or "[]")
    if not steps:
        return {"success": False, "message": "Workflow has no steps"}

    run = WorkflowRun(
        workflow_id=workflow_id,
        user_id=user_id,
        status="running",
        input_text=input_text,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    step_results = []
    prior_context = ""
    final_output = ""

    try:
        for i, step in enumerate(steps):
            agent = step.get("agent", "research")
            label = step.get("label", f"Step {i+1}")
            template = step.get("prompt_template", "")

            # Build the prompt for this step
            if template:
                prompt = template.replace("{{input}}", input_text).replace("{{context}}", prior_context)
            else:
                prompt = input_text if not prior_context else f"{prior_context}\n\nNow handle the {label} phase."

            try:
                result = generate_response(agent, prompt, []) or fallback_response(agent, prompt)
            except Exception:
                result = fallback_response(agent, prompt)

            step_results.append({
                "step": i + 1,
                "label": label,
                "agent": agent,
                "result": result,
            })
            prior_context += f"\n\n**{label}** ({agent}):\n{result}"
            final_output = result  # last step output is the default final

        # If multiple steps, summarise
        if len(steps) > 1:
            summary_prompt = (
                f"Summarise the following workflow results into a clear, actionable final output "
                f"for the user.\n\nOriginal input: {input_text}\n\n{prior_context}"
            )
            try:
                final_output = generate_response("research", summary_prompt, []) or prior_context
            except Exception:
                final_output = prior_context

        # Persist result
        run.status = "success"
        run.final_output = final_output
        run.step_results = json.dumps(step_results)
        run.finished_at = datetime.now(timezone.utc).isoformat()

        wf.run_count = (wf.run_count or 0) + 1
        wf.last_run = run.finished_at
        if wf.status == "Draft":
            wf.status = "Active"

        db.commit()

        return {
            "success": True,
            "run_id": run.id,
            "workflow_name": wf.name,
            "steps": step_results,
            "final_output": final_output,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
        }

    except Exception as e:
        run.status = "failed"
        run.finished_at = datetime.now(timezone.utc).isoformat()
        db.commit()
        return {"success": False, "message": f"Execution error: {e}"}
