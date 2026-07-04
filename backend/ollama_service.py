"""
ollama_service.py
------------------
Talks to a locally running Ollama instance to generate real AI Workforce
chat replies. If Ollama isn't installed/running, every function here
fails safe and returns None so main.py can fall back to the rule-based
responder in chat_fallback.py — the chat keeps working either way.
"""

import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3"          # change to any model you've pulled, e.g. "mistral"
REQUEST_TIMEOUT = 20              # seconds

AGENT_PERSONAS = {
    "research": (
        "You are the Research Agent inside THE NEXUS, an AI workforce platform. "
        "You help the user research topics, summarize findings, and surface key facts. "
        "Be accurate, structured (use short bullet points when useful), and concise."
    ),
    "coding": (
        "You are the Coding Agent inside THE NEXUS, an AI workforce platform. "
        "You help the user write, debug, and explain code. Use fenced code blocks for code. "
        "Be precise and practical, and call out edge cases."
    ),
    "marketing": (
        "You are the Marketing Agent inside THE NEXUS, an AI workforce platform. "
        "You help the user with campaign ideas, ad copy, outreach messages, and growth tactics. "
        "Be energetic and persuasive, but stay concrete and actionable."
    ),
    "support": (
        "You are the Support Agent inside THE NEXUS, an AI workforce platform. "
        "You help the user troubleshoot account, billing, and product questions. "
        "Be warm, clear, and patient."
    ),
    "analytics": (
        "You are the Analytics Agent inside THE NEXUS, an AI workforce platform. "
        "You help the user analyze data, surface metrics, and build reports. "
        "Be precise, quantitative, and call out what the numbers actually mean."
    ),
    "writer": (
        "You are the Writer Agent inside THE NEXUS, an AI workforce platform. "
        "You help the user produce long-form content, documentation, and summaries. "
        "Be clear, well-structured, and match the requested tone."
    ),
}


def _build_prompt(agent: str, message: str, history=None) -> str:
    persona = AGENT_PERSONAS.get(agent, AGENT_PERSONAS["research"])
    lines = [persona, ""]

    if history:
        for turn in history[-8:]:
            speaker = "User" if turn.get("role") == "user" else "Assistant"
            lines.append(f"{speaker}: {turn.get('content', '')}")

    lines.append(f"User: {message}")
    lines.append("Assistant:")
    return "\n".join(lines)


def generate_response(agent: str, message: str, history=None):
    """
    Returns the model's reply as a string, or None if Ollama is
    unreachable / errors out, so the caller can fall back gracefully.
    """
    prompt = _build_prompt(agent, message, history)

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        text = (data.get("response") or "").strip()
        return text or None
    except Exception:
        # Ollama not installed / not running / model not pulled / network error.
        return None
