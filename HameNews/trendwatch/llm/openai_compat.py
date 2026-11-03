"""Works with OpenAI and anything exposing an OpenAI-style chat API
(Ollama, vLLM, LM Studio, OpenRouter, ...). Set options.base_url for non-OpenAI servers."""
import os

from .base import LLM


class OpenAICompatLLM(LLM):
    def __init__(self, models, base_url=None, api_key_env="OPENAI_API_KEY"):
        super().__init__(models)
        import openai
        self._openai = openai
        # Local servers often need no key, but the SDK wants a non-empty string.
        self.client = openai.OpenAI(base_url=base_url,
                                    api_key=os.environ.get(api_key_env) or "not-needed")

    def complete(self, system, prompt, tier="fast", max_tokens=2000):
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": prompt}]
        try:
            r = self.client.chat.completions.create(
                model=self.models[tier], messages=messages, max_completion_tokens=max_tokens)
        except self._openai.BadRequestError:
            # Older / third-party servers only understand max_tokens.
            r = self.client.chat.completions.create(
                model=self.models[tier], messages=messages, max_tokens=max_tokens)
        return r.choices[0].message.content or ""
