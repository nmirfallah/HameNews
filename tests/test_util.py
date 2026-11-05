import unittest

import helpers  # noqa: F401
from trendwatch.util import clip, short_hash, slugify, strip_html, term_in


class UtilTests(unittest.TestCase):
    def test_strip_html_removes_tags_and_unescapes(self):
        self.assertEqual(strip_html("<p>Hello&amp; <b>world</b></p>"), "Hello& world")

    def test_strip_html_collapses_whitespace_and_handles_none(self):
        self.assertEqual(strip_html("a \n\t b"), "a b")
        self.assertEqual(strip_html(None), "")

    def test_slugify(self):
        self.assertEqual(slugify("Climate Change!"), "climate-change")
        self.assertEqual(slugify("Hamas–Israel war"), "hamas-israel-war")
        self.assertEqual(slugify(""), "topic")
        self.assertEqual(slugify("!!!"), "topic")
        self.assertEqual(len(slugify("a" * 100)), 60)

    def test_short_hash_is_stable_and_short(self):
        self.assertEqual(short_hash("x"), short_hash("x"))
        self.assertNotEqual(short_hash("x"), short_hash("y"))
        self.assertEqual(len(short_hash("x")), 12)

    def test_clip(self):
        self.assertEqual(clip("abcdef", 4), "abc…")
        self.assertEqual(clip("abc", 4), "abc")
        self.assertEqual(clip(None, 5), "")

    def test_term_in_matches_whole_words_only(self):
        self.assertFalse(term_in("AI", "He said it was fine"))
        self.assertTrue(term_in("AI", "New AI rules arrive"))
        self.assertTrue(term_in("climate change", "Climate Change talks resume"))
        self.assertFalse(term_in("war", "software"))


if __name__ == "__main__":
    unittest.main()
