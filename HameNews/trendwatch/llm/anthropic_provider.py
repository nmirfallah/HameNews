import os

from .base import LLM


class AnthropicLLM(LLM):
    def __init__(self, models, api_key_env="ANTHROPIC_API_KEY"):
        super().__init__(models)
        import anthropic
        key = os.environ.get(api_key_env)
        if not key:
            raise RuntimeError(f"Set the {api_key_env} environment variable.")
        self.client = anthropic.Anthropic(api_key=key)

    def complete(self, system, prompt, tier="fast", max_tokens=2000):
        resp = self.client.messages.create(
            model=self.models[tier],
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
