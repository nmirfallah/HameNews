import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest import mock

from helpers import ScriptedLLM
from trendwatch.llm import PROVIDERS, get_llm
from trendwatch.llm.base import extract_json


class ExtractJsonTests(unittest.TestCase):
    def test_plain_object_and_array(self):
        self.assertEqual(extract_json('{"a": 1}'), {"a": 1})
        self.assertEqual(extract_json("[1, 2]"), [1, 2])

    def test_code_fences(self):
        self.assertEqual(extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(extract_json('```\n[1]\n```'), [1])

    def test_json_surrounded_by_prose(self):
        self.assertEqual(extract_json('Sure! [1, 2, 3] done'), [1, 2, 3])
        self.assertEqual(extract_json('Here {"a": [1, 2]} thanks'), {"a": [1, 2]})

    def test_surrounding_whitespace(self):
        self.assertEqual(extract_json('  \n{"a": 1}\n '), {"a": 1})

    def test_failures_raise_value_error(self):
        for bad in ("no json here", "{bad json}", "", None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                extract_json(bad)


class CompleteJsonTests(unittest.TestCase):
    def test_returns_parsed_json(self):
        llm = ScriptedLLM(['{"ok": true}'])
        self.assertEqual(llm.complete_json("sys", "prompt"), {"ok": True})
        self.assertEqual(len(llm.calls), 1)

    def test_retries_once_with_a_stricter_prompt(self):
        llm = ScriptedLLM(["not json at all", '{"ok": true}'])
        self.assertEqual(llm.complete_json("sys", "prompt"), {"ok": True})
        self.assertEqual(len(llm.calls), 2)
        self.assertIn("ONLY valid JSON", llm.calls[1]["prompt"])
        self.assertTrue(llm.calls[1]["prompt"].startswith("prompt"))

    def test_gives_up_after_one_retry(self):
        llm = ScriptedLLM(["bad", "still bad"])
        with self.assertRaises(ValueError):
            llm.complete_json("sys", "prompt")
        self.assertEqual(len(llm.calls), 2)

    def test_tier_and_token_limit_are_forwarded(self):
        llm = ScriptedLLM(["[]"])
        llm.complete_json("sys", "p", tier="smart", max_tokens=123)
        self.assertEqual((llm.calls[0]["tier"], llm.calls[0]["max_tokens"]), ("smart", 123))

    def test_provider_errors_propagate(self):
        llm = ScriptedLLM([RuntimeError("boom")])
        with self.assertRaises(RuntimeError):
            llm.complete_json("sys", "p")


class GetLlmTests(unittest.TestCase):
    def test_unknown_provider_lists_known_ones(self):
        with self.assertRaises(ValueError) as cm:
            get_llm({"provider": "nope", "models": {}})
        self.assertIn("Known providers", str(cm.exception))
        self.assertIn("anthropic", str(cm.exception))

    def test_registry_builds_provider_with_options(self):
        with mock.patch.dict(PROVIDERS, {"echo": "helpers:EchoLLM"}):
            llm = get_llm({"provider": "echo", "models": {"fast": "f", "smart": "s"},
                           "options": {"flag": "x"}})
        self.assertEqual(llm.flag, "x")
        self.assertEqual(llm.models, {"fast": "f", "smart": "s"})

    def test_options_are_optional(self):
        with mock.patch.dict(PROVIDERS, {"echo": "helpers:EchoLLM"}):
            llm = get_llm({"provider": "echo", "models": {"fast": "f", "smart": "s"}})
        self.assertIsNone(llm.flag)

    def test_builtin_providers_are_registered(self):
        self.assertEqual(set(PROVIDERS), {"anthropic", "openai_compat"})


class AnthropicProviderTests(unittest.TestCase):
    def _fake_module(self):
        created = {}

        class Messages:
            def create(self, **kw):
                created.update(kw)
                return SimpleNamespace(content=[SimpleNamespace(type="text", text="Hi "),
                                                SimpleNamespace(type="tool_use"),
                                                SimpleNamespace(type="text", text="there")])

        class Anthropic:
            def __init__(self, api_key):
                created["api_key"] = api_key
                self.messages = Messages()

        mod = types.ModuleType("anthropic")
        mod.Anthropic = Anthropic
        return mod, created

    def test_complete_sends_the_right_request_and_joins_text_blocks(self):
        mod, created = self._fake_module()
        with mock.patch.dict(sys.modules, {"anthropic": mod}), \
                mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "secret"}):
            from trendwatch.llm.anthropic_provider import AnthropicLLM
            llm = AnthropicLLM({"fast": "m1", "smart": "m2"})
            out = llm.complete("sys", "prompt", tier="smart", max_tokens=50)
        self.assertEqual(out, "Hi there")
        self.assertEqual(created["api_key"], "secret")
        self.assertEqual(created["model"], "m2")
        self.assertEqual(created["max_tokens"], 50)
        self.assertEqual(created["system"], "sys")
        self.assertEqual(created["messages"], [{"role": "user", "content": "prompt"}])

    def test_missing_key_is_a_clear_error(self):
        mod, _ = self._fake_module()
        with mock.patch.dict(sys.modules, {"anthropic": mod}), mock.patch.dict(os.environ):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            from trendwatch.llm.anthropic_provider import AnthropicLLM
            with self.assertRaises(RuntimeError) as cm:
                AnthropicLLM({"fast": "a", "smart": "b"})
        self.assertIn("ANTHROPIC_API_KEY", str(cm.exception))

    def test_custom_key_variable(self):
        mod, created = self._fake_module()
        with mock.patch.dict(sys.modules, {"anthropic": mod}), \
                mock.patch.dict(os.environ, {"MY_KEY": "k2"}):
            from trendwatch.llm.anthropic_provider import AnthropicLLM
            AnthropicLLM({"fast": "a", "smart": "b"}, api_key_env="MY_KEY")
        self.assertEqual(created["api_key"], "k2")


class OpenAICompatProviderTests(unittest.TestCase):
    def _fake_module(self, reject_new_param=False, content="done"):
        calls, init = [], {}

        class BadRequestError(Exception):
            pass

        class Completions:
            def create(self, **kw):
                calls.append(kw)
                if reject_new_param and "max_completion_tokens" in kw:
                    raise BadRequestError("unsupported parameter")
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

        class OpenAI:
            def __init__(self, base_url=None, api_key=None):
                init.update(base_url=base_url, api_key=api_key)
                self.chat = SimpleNamespace(completions=Completions())

        mod = types.ModuleType("openai")
        mod.OpenAI, mod.BadRequestError = OpenAI, BadRequestError
        return mod, calls, init

    def test_happy_path_uses_max_completion_tokens(self):
        mod, calls, init = self._fake_module()
        with mock.patch.dict(sys.modules, {"openai": mod}), mock.patch.dict(os.environ):
            os.environ.pop("OPENAI_API_KEY", None)
            from trendwatch.llm.openai_compat import OpenAICompatLLM
            llm = OpenAICompatLLM({"fast": "f", "smart": "s"}, base_url="http://localhost:11434/v1")
            out = llm.complete("sys", "hello", tier="fast", max_tokens=77)
        self.assertEqual(out, "done")
        self.assertEqual(init, {"base_url": "http://localhost:11434/v1", "api_key": "not-needed"})
        self.assertEqual(calls[0]["max_completion_tokens"], 77)
        self.assertEqual(calls[0]["messages"][0], {"role": "system", "content": "sys"})
        self.assertEqual(calls[0]["messages"][1], {"role": "user", "content": "hello"})

    def test_falls_back_to_max_tokens_for_older_servers(self):
        mod, calls, _ = self._fake_module(reject_new_param=True)
        with mock.patch.dict(sys.modules, {"openai": mod}):
            from trendwatch.llm.openai_compat import OpenAICompatLLM
            out = OpenAICompatLLM({"fast": "f", "smart": "s"}).complete("s", "p", max_tokens=9)
        self.assertEqual(out, "done")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]["max_tokens"], 9)
        self.assertNotIn("max_completion_tokens", calls[1])

    def test_empty_content_becomes_empty_string(self):
        mod, _, _ = self._fake_module(content=None)
        with mock.patch.dict(sys.modules, {"openai": mod}):
            from trendwatch.llm.openai_compat import OpenAICompatLLM
            self.assertEqual(OpenAICompatLLM({"fast": "f", "smart": "s"}).complete("s", "p"), "")

    def test_api_key_comes_from_the_environment(self):
        mod, _, init = self._fake_module()
        with mock.patch.dict(sys.modules, {"openai": mod}), mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk"}):
            from trendwatch.llm.openai_compat import OpenAICompatLLM
            OpenAICompatLLM({"fast": "f", "smart": "s"})
        self.assertEqual(init["api_key"], "sk")


if __name__ == "__main__":
    unittest.main()
