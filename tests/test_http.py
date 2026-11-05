import sys
import types
import unittest
from types import SimpleNamespace
from unittest import mock

import requests

import helpers  # noqa: F401
from trendwatch import http


def response(json_value=None, content=b"", raises=None, bad_json=False):
    r = mock.Mock()
    r.content = content
    if raises:
        r.raise_for_status.side_effect = raises
    if bad_json:
        r.json.side_effect = ValueError("no json")
    else:
        r.json.return_value = json_value
    return r


class HttpTests(unittest.TestCase):
    def test_get_sends_user_agent_params_headers_and_timeout(self):
        with mock.patch.object(http.requests, "get", return_value=response()) as g:
            http.get("http://x", params={"q": 1}, headers={"X-A": "b"}, timeout=7)
        _, kw = g.call_args
        self.assertEqual(kw["params"], {"q": 1})
        self.assertEqual(kw["timeout"], 7)
        self.assertEqual(kw["headers"]["X-A"], "b")
        self.assertEqual(kw["headers"]["User-Agent"], http.UA)

    def test_get_returns_none_on_network_error(self):
        with mock.patch.object(http.requests, "get", side_effect=requests.ConnectionError("down")):
            self.assertIsNone(http.get("http://x"))

    def test_get_returns_none_on_http_error_status(self):
        r = response(raises=requests.HTTPError("403"))
        with mock.patch.object(http.requests, "get", return_value=r):
            self.assertIsNone(http.get("http://x"))

    def test_get_json_parses_or_returns_none(self):
        with mock.patch.object(http.requests, "get", return_value=response({"a": 1})):
            self.assertEqual(http.get_json("http://x"), {"a": 1})
        with mock.patch.object(http.requests, "get", return_value=response(bad_json=True)):
            self.assertIsNone(http.get_json("http://x"))
        with mock.patch.object(http.requests, "get", side_effect=requests.Timeout()):
            self.assertIsNone(http.get_json("http://x"))

    def test_get_feed_parses_the_response_bytes(self):
        fake = types.ModuleType("feedparser")
        fake.parse = lambda content: SimpleNamespace(entries=[content])
        with mock.patch.dict(sys.modules, {"feedparser": fake}), \
                mock.patch.object(http.requests, "get", return_value=response(content=b"<rss/>")):
            feed = http.get_feed("http://x")
        self.assertEqual(feed.entries, [b"<rss/>"])

    def test_get_feed_returns_none_when_the_request_fails(self):
        fake = types.ModuleType("feedparser")
        fake.parse = lambda content: self.fail("must not parse")
        with mock.patch.dict(sys.modules, {"feedparser": fake}), \
                mock.patch.object(http.requests, "get", side_effect=requests.ConnectionError()):
            self.assertIsNone(http.get_feed("http://x"))


if __name__ == "__main__":
    unittest.main()
