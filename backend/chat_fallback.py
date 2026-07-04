"""
chat_fallback.py
-----------------
Deterministic, option-aware responses used whenever Ollama is not
running. These are keyed off the quick-action the user picked (or
keywords in their message) so the chat still feels purposeful instead
of returning a generic canned line.
"""

import re

_STRIP_PREFIX = re.compile(
    r"^(research a topic|research|analyze data|analyze|write content|write|"
    r"build workflow|build|generate code|generate|create workforce|create)\b[:\-]?\s*",
    re.IGNORECASE,
)


def _topic(message: str) -> str:
    cleaned = _STRIP_PREFIX.sub("", message, count=1).strip()
    return cleaned or "this"


def _research_reply(message: str) -> str:
    topic = _topic(message)
    return (
        f"Here's how I'd kick off research on **{topic}**:\n\n"
        f"• **Overview** — map the key facts, players, and recent developments.\n"
        f"• **Sources** — pull from primary sources, recent news, and reputable reports.\n"
        f"• **Synthesis** — condense everything into the 3–5 points that actually matter for your decision.\n\n"
        f"Tell me which angle you care about most (market size, competitors, technical background, etc.) "
        f"and I'll go deeper."
    )


def _workforce_reply(message: str) -> str:
    return (
        "Let's build you a workforce. Head over to **Create Workforce** and pick a template "
        "(Research, Sales, Support, or Dev squad) — or just tell me what work you need handled "
        "and I'll suggest which agents to deploy and what roles to give them."
    )


def _workflow_reply(message: str) -> str:
    return (
        "I can help design that automation. A solid workflow usually has three parts:\n\n"
        "1. **Trigger** — what kicks it off (a new lead, a schedule, an incoming email…)\n"
        "2. **Steps** — which agents act, and in what order\n"
        "3. **Output** — where the result lands (a report, a message, a CRM update…)\n\n"
        "Describe the task you want automated and I'll sketch the steps — then build it on the Workflows page."
    )


def _code_reply(message: str) -> str:
    topic = _topic(message)
    return (
        f"Happy to help with code{'' if topic == 'this' else ' for ' + topic}. "
        f"Tell me the language/framework and what you're building (a function, a bug fix, a small feature) "
        f"and I'll write it out, explain the approach, and flag edge cases to watch for."
    )


def _data_reply(message: str) -> str:
    return (
        "For data analysis, share what you're working with (a CSV, a metric, a dataset) and your goal "
        "(spot a trend, compare groups, forecast something). I'll outline the cleaning steps, the right "
        "chart or stat to use, and what the result would actually tell you."
    )


def _content_reply(message: str) -> str:
    topic = _topic(message)
    return (
        f"I can draft that{'' if topic == 'this' else ' on ' + topic}. Let me know the format "
        f"(blog post, ad copy, email, social caption), the tone you want (casual, professional, bold), "
        f"and the target audience — and I'll write a first draft you can edit."
    )


_KEYWORD_HANDLERS = [
    (re.compile(r"research", re.I), _research_reply),
    (re.compile(r"create\s*workforce|create\s*a\s*workforce", re.I), _workforce_reply),
    (re.compile(r"workflow", re.I), _workflow_reply),
    (re.compile(r"generate\s*code|\bcode\b|debug|bug\b", re.I), _code_reply),
    (re.compile(r"analy[sz]e|data\b", re.I), _data_reply),
    (re.compile(r"write\s*content|\bwrite\b|copy\b|caption", re.I), _content_reply),
]

_PERSONA_LINES = {
    "research": "I'm your Research Agent — give me a topic, question, or article and I'll dig in and summarize it for you.",
    "coding": "I'm your Coding Agent — share a bug, a feature you need, or a language/framework and I'll write or debug the code.",
    "marketing": "I'm your Marketing Agent — tell me about your product and audience and I'll draft campaign ideas, ad copy, or outreach messages.",
    "support": "I'm your Support Agent — describe what's going wrong (billing, account, a feature) and I'll help you sort it out.",
    "analytics": "I'm your Analytics Agent — share the data or metric you care about and I'll help you analyze it and report on it.",
    "writer": "I'm your Writer Agent — tell me the format and topic and I'll draft the content for you.",
}


def fallback_response(agent: str, message: str) -> str:
    message = (message or "").strip()
    if not message:
        return _PERSONA_LINES.get(agent, _PERSONA_LINES["research"])

    for pattern, handler in _KEYWORD_HANDLERS:
        if pattern.search(message):
            return handler(message)

    persona_line = _PERSONA_LINES.get(agent, _PERSONA_LINES["research"])
    return f'Got it — "{message}". {persona_line}'
