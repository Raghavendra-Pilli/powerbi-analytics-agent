"""Anthropic Claude API client wrapper."""

from anthropic import Anthropic
from pbi_agent.config import LLMConfig
from pbi_agent.logging import get_logger

log = get_logger("llm")


def _extract_text(response) -> str:
    """Pull the text content out of a Claude response.

    Some models/modes prepend non-text blocks (e.g. ThinkingBlock) before
    the actual text block, so we can't assume content[0] is always text.
    """
    for block in response.content:
        if getattr(block, "type", None) == "text":
            return block.text
    # Fallback: no explicit "text" type found, try attribute directly
    for block in response.content:
        text = getattr(block, "text", None)
        if text:
            return text
    return ""


class LLMClient:
    """Wrapper around the Anthropic API with model routing."""

    def __init__(self, config: LLMConfig):
        if not config.api_key:
            raise ValueError("ANTHROPIC_API_KEY not set. Add it to .env file.")
        self.client = Anthropic(api_key=config.api_key)
        self.config = config

    def route(self, user_message: str) -> str:
        """Classify user intent using the fast/cheap router model."""
        system = (
            "You are an intent classifier for a Power BI analytics agent. "
            "Classify the user message into exactly one of these categories:\n"
            "- CONNECT: User wants to connect to a data source (CSV/Excel/SQL)\n"
            "- SUMMARIZE: User wants a plain-language summary/description of data that is "
            "already connected (e.g. 'summarize the data', 'what's in this file', "
            "'describe the data')\n"
            "- INSPECT: User wants to inspect/explore an existing Power BI semantic model's "
            "structure/quality (tables, measures, relationships already defined in a .pbip project)\n"
            "- REVIEW: User wants to review an existing Power BI report's health or quality\n"
            "- SCAFFOLD: User wants to create/generate a new .pbip Power BI project FROM a "
            "connected CSV/Excel file (e.g. 'create a pbip for this excel file', "
            "'generate a power bi project from this data', 'build a pbip report')\n"
            "- REMEDIATE: User wants to FIX gaps in an already-loaded PBIP model — generate "
            "missing DAX measures, fix the date table, improve the health score, make it "
            "'production ready' (e.g. 'fix all gaps in the model', 'create the missing "
            "measures', 'improve the health score')\n"
            "- EXPORT: User wants to export an EXISTING PBIP project to PBIX or a package\n"
            "- HELP: User needs help or has a general question\n\n"
            "Respond with ONLY the category name, nothing else."
        )
        response = self.client.messages.create(
            model=self.config.router_model,
            max_tokens=20,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        intent = _extract_text(response).strip().upper()
        log.info(f"Routed intent: {intent}")
        return intent

    def analyze(self, system_prompt: str, user_message: str, max_tokens: int | None = None) -> str:
        """Run an analysis task using the reasoning model."""
        response = self.client.messages.create(
            model=self.config.analysis_model,
            max_tokens=max_tokens or self.config.max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return _extract_text(response)

    def chat(self, messages: list[dict], system_prompt: str = "") -> str:
        """Multi-turn conversation."""
        kwargs = {
            "model": self.config.analysis_model,
            "max_tokens": self.config.max_tokens,
            "messages": messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        response = self.client.messages.create(**kwargs)
        return _extract_text(response)
