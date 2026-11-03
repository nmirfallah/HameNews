"""The only interface the rest of the app knows about.

To support a new model/provider, subclass LLM, implement complete(), and register
the class in trendwatch/llm/__init__.py. Nothing else in the project changes.
"""
import json
import re
from abc import ABC, abstractmethod


class LLM(ABC):
    def __init__(self, models):
        # models maps a tier name to a provider-specific model id:
        #   "fast"  -> cheap model for high-volume labelling
        #   "smart" -> stronger model for clustering and report writing
        self.models = models

    @abstractmethod
    def complete(self, system, prompt, tier="fast", max_tokens=2000):
        """Return the model's reply as plain text."""

    def complete_json(self, system, prompt, tier="fast", max_tokens=2000):
        text = self.complete(system, prompt, tier, max_tokens)
        try:
            return extract_json(text)
        except ValueError:
            retry = prompt + "\n\nYour previous reply was not valid JSON. Reply with ONLY valid JSON."
            return extract_json(self.complete(system, retry, tier, max_tokens))


def extract_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        raise ValueError("no JSON found in model reply")
    start, end = min(starts), max(text.rfind("}"), text.rfind("]"))
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON in model reply: {e}")
