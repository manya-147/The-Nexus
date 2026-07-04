from fastapi import FastAPI, Header

from database import SessionLocal
from database import engine

from auth import verify_token

from model import Base
from model import User
from model import SignupRequest
from model import LoginRequest
from model import Payment
from model import PaymentRequest
from model import Agent
from model import AgentRequest
from model import ChatMessage
from model import ChatRequest
from fastapi.middleware.cors import CORSMiddleware

from auth import create_access_token

from ollama_service import generate_response
from chat_fallback import fallback_response

import bcrypt
import uuid
from datetime import datetime



app = FastAPI(
    title="The Nexus API"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():

    return {
        "message":"Backend Running"
    }



Base.metadata.create_all(bind=engine)


@app.post("/signup")
def signup(user: SignupRequest):

    db = SessionLocal()

    existing_user = db.query(User).filter(
        User.email == user.email
    ).first()

    if existing_user:
        return {
            "success": False,
            "message": "Email already exists"
        }

    hashed_password = bcrypt.hashpw(
        user.password.encode(),
        bcrypt.gensalt()
    ).decode()

    new_user = User(
        full_name=user.full_name,
        email=user.email,
        phone=user.phone,
        dob=user.dob,
        password=hashed_password
    )

    db.add(new_user)
    db.commit()

    return {
        "success": True,
        "message": "Account created"
    }




@app.post("/login")
def login(user: LoginRequest):

    db = SessionLocal()

    db_user = db.query(User).filter(
        User.email == user.email
    ).first()

    if not db_user:
        return {
            "success": False,
            "message": "User not found"
        }

    password_valid = bcrypt.checkpw(
        user.password.encode("utf-8"),
        db_user.password.encode("utf-8")
    )

    if not password_valid:
        return {
            "success": False,
            "message": "Invalid password"
        }

    token = create_access_token(
        {
            "user_id": db_user.id,
            "email": db_user.email
        }
    )

    return {
        "success": True,
        "message": "Login Successful",
        "token": token,
        "user_id": db_user.id,
        "full_name": db_user.full_name,
        "email": db_user.email
    }






@app.get("/profile")
def get_profile(
    authorization: str = Header(None)):

    if not authorization:
        return {
            "success": False,
            "message": "Token Missing"
        }

    token = authorization.replace(
        "Bearer ",
        ""
    )

    payload = verify_token(token)

    if not payload:
        return {
            "success": False,
            "message": "Invalid Token"
        }

    db = SessionLocal()

    user = db.query(User).filter(
        User.id == payload["user_id"]
    ).first()

    return {
        "id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "phone": user.phone,
        "dob": user.dob,
        "plan": user.plan,
        "plan_started": user.plan_started
    }

from pydantic import BaseModel

class ProfileUpdateRequest(BaseModel):
    full_name: str
    email: str
    phone: str
    dob: str

@app.put("/profile")
def update_profile(
    profile: ProfileUpdateRequest,
    authorization: str = Header(None)
):
    if not authorization:
        return {"success": False, "message": "Token Missing"}

    token = authorization.replace("Bearer ", "")
    payload = verify_token(token)

    if not payload:
        return {"success": False, "message": "Invalid Token"}

    db = SessionLocal()
    user = db.query(User).filter(User.id == payload["user_id"]).first()

    user.full_name = profile.full_name
    user.email = profile.email
    user.phone = profile.phone
    user.dob = profile.dob

    db.commit()

    return {"success": True, "message": "Profile updated"}


@app.post("/payment")
def make_payment(
    payment: PaymentRequest,
    authorization: str = Header(None)
):
    if not authorization:
        return {"success": False, "message": "Token Missing"}

    token = authorization.replace("Bearer ", "")
    payload = verify_token(token)

    if not payload:
        return {"success": False, "message": "Invalid Token"}

    db = SessionLocal()
    user = db.query(User).filter(User.id == payload["user_id"]).first()

    if not user:
        return {"success": False, "message": "User not found"}

    method = payment.method.upper()

    if method not in ["COD", "UPI", "CARD"]:
        return {"success": False, "message": "Unsupported payment method"}

    card_last4 = None

    if method == "UPI":
        if payment.scanned:
            # Paid by scanning the QR in their UPI app — trust the
            # client-side confirmation, there's no typed UPI ID to check.
            pass
        elif not payment.upi_id or "@" not in payment.upi_id:
            return {"success": False, "message": "Enter a valid UPI ID"}

    if method == "CARD":
        digits = (payment.card_number or "").replace(" ", "")

        if not digits.isdigit() or len(digits) < 12:
            return {"success": False, "message": "Enter a valid card number"}

        if not payment.pin or len(payment.pin) < 4:
            return {"success": False, "message": "Enter a valid PIN"}

        # Security: only the last 4 digits are ever persisted.
        # The full card number, expiry and PIN are used to process
        # the charge and are never written to the database.
        card_last4 = digits[-4:]

    reference = "NXP-" + uuid.uuid4().hex[:10].upper()

    new_payment = Payment(
        user_id=user.id,
        plan=payment.plan,
        amount=payment.amount,
        method=method,
        status="SUCCESS",
        reference=reference,
        upi_id=(payment.upi_id if method == "UPI" and not payment.scanned else ("Scanned via QR" if method == "UPI" else None)),
        card_last4=card_last4,
        card_holder=payment.card_holder if method == "CARD" else None,
        created_at=datetime.utcnow().isoformat()
    )

    db.add(new_payment)

    user.plan = payment.plan
    user.plan_started = datetime.utcnow().isoformat()

    db.commit()

    return {
        "success": True,
        "message": "Payment successful",
        "reference": reference,
        "plan": user.plan,
        "plan_started": user.plan_started,
        "amount": payment.amount,
        "method": method
    }


@app.get("/payments")
def list_payments(authorization: str = Header(None)):
    if not authorization:
        return {"success": False, "message": "Token Missing"}

    token = authorization.replace("Bearer ", "")
    payload = verify_token(token)

    if not payload:
        return {"success": False, "message": "Invalid Token"}

    db = SessionLocal()

    payments = db.query(Payment).filter(
        Payment.user_id == payload["user_id"]
    ).order_by(Payment.id.desc()).all()

    return {
        "success": True,
        "payments": [
            {
                "reference": p.reference,
                "plan": p.plan,
                "amount": p.amount,
                "method": p.method,
                "status": p.status,
                "created_at": p.created_at
            }
            for p in payments
        ]
    }


# ─────────────────────────────────────────────
#  AGENTS CRUD
# ─────────────────────────────────────────────

def _auth(authorization):
    """Helper: verify bearer token, return payload or None."""
    if not authorization:
        return None
    token = authorization.replace("Bearer ", "")
    return verify_token(token)


@app.get("/agents")
def list_agents(authorization: str = Header(None)):
    payload = _auth(authorization)
    if not payload:
        return {"success": False, "message": "Unauthorized"}

    db = SessionLocal()
    agents = (
        db.query(Agent)
        .filter(Agent.user_id == payload["user_id"])
        .order_by(Agent.id.desc())
        .all()
    )
    return {
        "success": True,
        "agents": [
            {
                "id": a.id,
                "name": a.name,
                "role": a.role,
                "type": a.type,
                "description": a.description,
                "status": a.status,
                "icon": a.icon,
                "created_at": a.created_at,
            }
            for a in agents
        ],
    }


@app.post("/agents")
def create_agent(agent: AgentRequest, authorization: str = Header(None)):
    payload = _auth(authorization)
    if not payload:
        return {"success": False, "message": "Unauthorized"}

    db = SessionLocal()
    new_agent = Agent(
        user_id=payload["user_id"],
        name=agent.name,
        role=agent.role,
        type=agent.type,
        description=agent.description,
        status=agent.status,
        icon=agent.icon,
        created_at=datetime.utcnow().isoformat(),
    )
    db.add(new_agent)
    db.commit()
    db.refresh(new_agent)
    return {
        "success": True,
        "message": "Agent created",
        "agent": {
            "id": new_agent.id,
            "name": new_agent.name,
            "role": new_agent.role,
            "type": new_agent.type,
            "description": new_agent.description,
            "status": new_agent.status,
            "icon": new_agent.icon,
            "created_at": new_agent.created_at,
        },
    }


@app.get("/agents/{agent_id}")
def get_agent(agent_id: int, authorization: str = Header(None)):
    payload = _auth(authorization)
    if not payload:
        return {"success": False, "message": "Unauthorized"}

    db = SessionLocal()
    agent = (
        db.query(Agent)
        .filter(Agent.id == agent_id, Agent.user_id == payload["user_id"])
        .first()
    )
    if not agent:
        return {"success": False, "message": "Agent not found"}

    return {
        "success": True,
        "agent": {
            "id": agent.id,
            "name": agent.name,
            "role": agent.role,
            "type": agent.type,
            "description": agent.description,
            "status": agent.status,
            "icon": agent.icon,
            "created_at": agent.created_at,
        },
    }


@app.put("/agents/{agent_id}")
def update_agent(
    agent_id: int,
    agent: AgentRequest,
    authorization: str = Header(None),
):
    payload = _auth(authorization)
    if not payload:
        return {"success": False, "message": "Unauthorized"}

    db = SessionLocal()
    existing = (
        db.query(Agent)
        .filter(Agent.id == agent_id, Agent.user_id == payload["user_id"])
        .first()
    )
    if not existing:
        return {"success": False, "message": "Agent not found"}

    existing.name = agent.name
    existing.role = agent.role
    existing.type = agent.type
    existing.description = agent.description
    existing.status = agent.status
    existing.icon = agent.icon

    db.commit()
    return {"success": True, "message": "Agent updated"}


@app.delete("/agents/{agent_id}")
def delete_agent(agent_id: int, authorization: str = Header(None)):
    payload = _auth(authorization)
    if not payload:
        return {"success": False, "message": "Unauthorized"}

    db = SessionLocal()
    agent = (
        db.query(Agent)
        .filter(Agent.id == agent_id, Agent.user_id == payload["user_id"])
        .first()
    )
    if not agent:
        return {"success": False, "message": "Agent not found"}

    db.delete(agent)
    db.commit()
    return {"success": True, "message": "Agent deleted"}


@app.patch("/agents/{agent_id}/status")
def toggle_agent_status(agent_id: int, authorization: str = Header(None)):
    payload = _auth(authorization)
    if not payload:
        return {"success": False, "message": "Unauthorized"}

    db = SessionLocal()
    agent = (
        db.query(Agent)
        .filter(Agent.id == agent_id, Agent.user_id == payload["user_id"])
        .first()
    )
    if not agent:
        return {"success": False, "message": "Agent not found"}

    # Cycle: Active → Paused → Active
    agent.status = "Paused" if agent.status == "Active" else "Active"
    db.commit()
    return {"success": True, "status": agent.status}


# ─────────────────────────────────────────────
#  AI WORKFORCE CHAT
# ─────────────────────────────────────────────

VALID_CHAT_AGENTS = {"research", "coding", "marketing", "support"}


def _normalize_agent(agent: str) -> str:
    agent = (agent or "").lower()
    return agent if agent in VALID_CHAT_AGENTS else "research"


@app.get("/chat/{agent}")
def get_chat_history(agent: str, authorization: str = Header(None)):
    payload = _auth(authorization)
    if not payload:
        return {"success": False, "message": "Unauthorized"}

    try:
        agent = _normalize_agent(agent)
        db = SessionLocal()

        messages = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.user_id == payload["user_id"],
                ChatMessage.agent == agent,
            )
            .order_by(ChatMessage.id.asc())
            .all()
        )

        return {
            "success": True,
            "agent": agent,
            "messages": [
                {"role": m.role, "content": m.content, "created_at": m.created_at}
                for m in messages
            ],
        }
    except Exception as e:
        return {"success": False, "message": f"Server error: {e}"}


@app.post("/chat")
def chat(req: ChatRequest, authorization: str = Header(None)):
    payload = _auth(authorization)
    if not payload:
        return {"success": False, "message": "Unauthorized"}

    message = (req.message or "").strip()
    if not message:
        return {"success": False, "message": "Message cannot be empty"}

    try:
        agent = _normalize_agent(req.agent)
        db = SessionLocal()

        user_msg = ChatMessage(
            user_id=payload["user_id"],
            agent=agent,
            role="user",
            content=message,
            created_at=datetime.utcnow().isoformat(),
        )
        db.add(user_msg)
        db.commit()

        history = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.user_id == payload["user_id"],
                ChatMessage.agent == agent,
            )
            .order_by(ChatMessage.id.asc())
            .all()
        )
        history_payload = [{"role": h.role, "content": h.content} for h in history]

        # Try a real local LLM (Ollama) first; if it's not running, fall back
        # to a deterministic, option-aware response so the chat still works.
        try:
            reply = generate_response(agent, message, history_payload)
        except Exception:
            reply = None
        source = "ollama"
        if not reply:
            reply = fallback_response(agent, message)
            source = "rules"

        ai_msg = ChatMessage(
            user_id=payload["user_id"],
            agent=agent,
            role="ai",
            content=reply,
            created_at=datetime.utcnow().isoformat(),
        )
        db.add(ai_msg)
        db.commit()

        return {
            "success": True,
            "agent": agent,
            "reply": reply,
            "source": source,
            "created_at": ai_msg.created_at,
        }
    except Exception as e:
        return {"success": False, "message": f"Server error: {e}"}


@app.delete("/chat/{agent}")
def clear_chat(agent: str, authorization: str = Header(None)):
    payload = _auth(authorization)
    if not payload:
        return {"success": False, "message": "Unauthorized"}

    try:
        agent = _normalize_agent(agent)
        db = SessionLocal()

        db.query(ChatMessage).filter(
            ChatMessage.user_id == payload["user_id"],
            ChatMessage.agent == agent,
        ).delete()
        db.commit()

        return {"success": True, "message": "Chat cleared"}
    except Exception as e:
        return {"success": False, "message": f"Server error: {e}"}


# ─────────────────────────────────────────────
#  MULTI-AGENT ENGINE
# ─────────────────────────────────────────────

from multi_agent_engine import run_multi_agent_task, AGENT_ROSTER
from pydantic import BaseModel as _BM


class MultiAgentRequest(_BM):
    task: str


@app.get("/multi-agent/agents")
def list_agent_roster(authorization: str = Header(None)):
    """Return the available agent roster so the UI can render it."""
    payload = _auth(authorization)
    if not payload:
        return {"success": False, "message": "Unauthorized"}

    return {
        "success": True,
        "agents": [
            {
                "key": key,
                "name": info["name"],
                "icon": info["icon"],
                "description": info["description"],
                "color": info["color"],
            }
            for key, info in AGENT_ROSTER.items()
        ],
    }


@app.post("/multi-agent/run")
def multi_agent_run(req: MultiAgentRequest, authorization: str = Header(None)):
    """
    Execute a multi-agent pipeline for the given task.
    Returns the decomposition steps and synthesised final answer.
    """
    payload = _auth(authorization)
    if not payload:
        return {"success": False, "message": "Unauthorized"}

    task = (req.task or "").strip()
    if not task:
        return {"success": False, "message": "Task cannot be empty"}

    try:
        result = run_multi_agent_task(task)
        return {"success": True, **result}
    except Exception as e:
        import traceback
        traceback.print_exc()  # full stack trace printed to the backend terminal/log
        detail = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
        return {"success": False, "message": f"Engine error: {detail}"}


# ─────────────────────────────────────────────────────────────────────────────
#  WORKFLOWS API
# ─────────────────────────────────────────────────────────────────────────────

from workflow_service import (
    Workflow, WorkflowRun,
    create_workflow, get_workflows, get_workflow,
    update_workflow, delete_workflow, get_workflow_runs,
    run_workflow,
)
from pydantic import BaseModel as _WFBase
from typing import Optional as _Opt, List as _List

# Ensure workflow tables are created
from database import engine as _engine
Workflow.__table__.create(bind=_engine, checkfirst=True)
WorkflowRun.__table__.create(bind=_engine, checkfirst=True)


class WorkflowStepSchema(_WFBase):
    agent: str
    label: str
    prompt_template: _Opt[str] = ""


class WorkflowCreateRequest(_WFBase):
    name: str
    description: _Opt[str] = ""
    steps: _List[WorkflowStepSchema] = []
    trigger: _Opt[str] = "manual"
    schedule: _Opt[str] = None


class WorkflowUpdateRequest(_WFBase):
    name: _Opt[str] = None
    description: _Opt[str] = None
    steps: _Opt[_List[WorkflowStepSchema]] = None
    trigger: _Opt[str] = None
    schedule: _Opt[str] = None
    status: _Opt[str] = None


class WorkflowRunRequest(_WFBase):
    input_text: _Opt[str] = ""


def _wf_dict(wf: Workflow) -> dict:
    import json
    return {
        "id": wf.id,
        "name": wf.name,
        "description": wf.description,
        "steps": json.loads(wf.steps or "[]"),
        "trigger": wf.trigger,
        "schedule": wf.schedule,
        "status": wf.status,
        "run_count": wf.run_count,
        "last_run": wf.last_run,
        "created_at": wf.created_at,
    }


@app.get("/workflows")
def list_workflows(authorization: str = Header(None)):
    payload = _auth(authorization)
    if not payload:
        return {"success": False, "message": "Unauthorized"}
    wfs = get_workflows(payload["user_id"])
    return {"success": True, "workflows": [_wf_dict(w) for w in wfs]}


@app.post("/workflows")
def create_workflow_route(req: WorkflowCreateRequest, authorization: str = Header(None)):
    payload = _auth(authorization)
    if not payload:
        return {"success": False, "message": "Unauthorized"}
    wf = create_workflow(
        user_id=payload["user_id"],
        name=req.name,
        description=req.description or "",
        steps=[s.dict() for s in req.steps],
        trigger=req.trigger or "manual",
        schedule=req.schedule,
    )
    return {"success": True, "workflow": _wf_dict(wf)}


@app.get("/workflows/{workflow_id}")
def get_workflow_route(workflow_id: int, authorization: str = Header(None)):
    payload = _auth(authorization)
    if not payload:
        return {"success": False, "message": "Unauthorized"}
    wf = get_workflow(workflow_id, payload["user_id"])
    if not wf:
        return {"success": False, "message": "Not found"}
    return {"success": True, "workflow": _wf_dict(wf)}


@app.put("/workflows/{workflow_id}")
def update_workflow_route(workflow_id: int, req: WorkflowUpdateRequest, authorization: str = Header(None)):
    payload = _auth(authorization)
    if not payload:
        return {"success": False, "message": "Unauthorized"}
    fields = {k: v for k, v in req.dict().items() if v is not None}
    if "steps" in fields:
        fields["steps"] = [s if isinstance(s, dict) else s.dict() for s in fields["steps"]]
    wf = update_workflow(workflow_id, payload["user_id"], **fields)
    if not wf:
        return {"success": False, "message": "Not found"}
    return {"success": True, "workflow": _wf_dict(wf)}


@app.delete("/workflows/{workflow_id}")
def delete_workflow_route(workflow_id: int, authorization: str = Header(None)):
    payload = _auth(authorization)
    if not payload:
        return {"success": False, "message": "Unauthorized"}
    ok = delete_workflow(workflow_id, payload["user_id"])
    return {"success": ok, "message": "Deleted" if ok else "Not found"}


@app.patch("/workflows/{workflow_id}/status")
def toggle_workflow_status(workflow_id: int, authorization: str = Header(None)):
    payload = _auth(authorization)
    if not payload:
        return {"success": False, "message": "Unauthorized"}
    wf = get_workflow(workflow_id, payload["user_id"])
    if not wf:
        return {"success": False, "message": "Not found"}
    new_status = "Paused" if wf.status == "Active" else "Active"
    update_workflow(workflow_id, payload["user_id"], status=new_status)
    return {"success": True, "status": new_status}


@app.post("/workflows/{workflow_id}/run")
def run_workflow_route(workflow_id: int, req: WorkflowRunRequest, authorization: str = Header(None)):
    payload = _auth(authorization)
    if not payload:
        return {"success": False, "message": "Unauthorized"}
    result = run_workflow(workflow_id, payload["user_id"], req.input_text or "")
    return result


@app.get("/workflows/{workflow_id}/runs")
def get_workflow_runs_route(workflow_id: int, authorization: str = Header(None)):
    payload = _auth(authorization)
    if not payload:
        return {"success": False, "message": "Unauthorized"}
    import json
    runs = get_workflow_runs(workflow_id, payload["user_id"])
    return {
        "success": True,
        "runs": [
            {
                "id": r.id,
                "status": r.status,
                "input_text": r.input_text,
                "final_output": r.final_output,
                "step_results": json.loads(r.step_results or "[]"),
                "started_at": r.started_at,
                "finished_at": r.finished_at,
            }
            for r in runs
        ],
    }
