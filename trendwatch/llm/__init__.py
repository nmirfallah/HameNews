import importlib

from .base import LLM, extract_json  # noqa: F401

# name -> "module:Class". Providers are imported lazily, so you only need the SDK
# of the provider you actually use. Add your own here.
PROVIDERS = {
    "anthropic": "trendwatch.llm.anthropic_provider:AnthropicLLM",
    "openai_compat": "trendwatch.llm.openai_compat:OpenAICompatLLM",
}


def get_llm(llm_cfg):
    name = llm_cfg["provider"]
    spec = PROVIDERS.get(name)
    if spec is None:
        raise ValueError(f"Unknown llm.provider {name!r}. Known providers: {sorted(PROVIDERS)}")
    module, cls = spec.split(":")
    klass = getattr(importlib.import_module(module), cls)
    return klass(models=llm_cfg["models"], **(llm_cfg.get("options") or {}))
