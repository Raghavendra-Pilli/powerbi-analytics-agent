"""Anthropic Claude API client wrapper."""

from anthropic import Anthropic
from pbi_agent.config import LLMConfig
from pbi_agent.logging import get_logger

log = get_logger("llm")


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
            "- CONNECT: User wants to connect to a data source\n"
            "- INSPECT: User wants to inspect/explore a semantic model\n"
            "- REVIEW: User wants to review report health or quality\n"
            "- EXPORT: User wants to export PBIX or project files\n"
            "- HELP: User needs help or has a general question\n\n"
            "Respond with ONLY the category name, nothing else."
        )
        response = self.client.messages.create(
            model=self.config.router_model,
            max_tokens=20,
            temperature=0.0,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        intent = response.content[0].text.strip().upper()
        log.info(f"Routed intent: {intent}")
        return intent

    def analyze(self, system_prompt: str, user_message: str) -> str:
        """Run an analysis task using the reasoning model."""
        response = self.client.messages.create(
            model=self.config.analysis_model,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text

    def chat(self, messages: list[dict], system_prompt: str = "") -> str:
        """Multi-turn conversation."""
        kwargs = {
            "model": self.config.analysis_model,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "messages": messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        response = self.client.messages.create(**kwargs)
        return response.content[0].text
