import tempfile
import unittest

from helpers import ScriptedLLM, cfg, item
from trendwatch import languages as L
from trendwatch.store import Store


class NameAndNormTests(unittest.TestCase):
    def test_norm(self):
        self.assertEqual(L.norm("fa-IR"), "fa")
        self.assertEqual(L.norm("PT_br"), "pt")
        self.assertEqual(L.norm("iw"), "he")
        self.assertEqual(L.norm("in"), "id")
        self.assertEqual(L.norm("nb"), "no")
        self.assertEqual(L.norm(" EN "), "en")
        for bad in ("", None, "x", "english", "12", "e1", 5):
            self.assertEqual(L.norm(bad), "", repr(bad))

    def test_undetermined_language_codes_are_not_languages(self):
        for code in ("und", "UND", "zxx", "mul", "mis", "xx"):
            self.assertEqual(L.norm(code), "", code)

    def test_more_languages_have_readable_names(self):
        self.assertEqual(L.name("sk"), "Slovak")
        self.assertEqual(L.name("ca"), "Catalan")
        self.assertEqual(L.name(L.norm("und")), "unknown")

    def test_name(self):
        self.assertEqual(L.name("fa"), "Persian")
        self.assertEqual(L.name("zz"), "zz")
        self.assertEqual(L.name(""), "unknown")


class GuessTests(unittest.TestCase):
    CASES = {
        "ar": "العاصمة تشهد احتجاجات واسعة اليوم",
        "fa": "گفتگوهای هسته‌ای ایران آغاز شد",
        "ur": "حکومت نے ٹیکس بڑھا دیا ہے",
        "ru": "Москва заявила о новых санкциях",
        "uk": "Україна отримала нову допомогу",
        "he": "ישראל והאמריקאים הודיעו",
        "el": "Η κυβέρνηση ανακοίνωσε νέα μέτρα",
        "hi": "सरकार ने नई नीति की घोषणा की",
        "th": "รัฐบาลประกาศนโยบายใหม่",
        "ko": "정부가 새로운 정책을 발표했다",
        "ja": "政府は新しい政策を発表した",
        "zh": "政府宣布新的政策",
        "es": "El gobierno de España anunció que los precios suben",
        "fr": "Le gouvernement a annoncé une nouvelle loi pour les familles",
        "de": "Die Regierung hat das neue Gesetz für die Bürger beschlossen",
        "tr": "Hükümet yeni düzenlemeyi açıkladı",
        "en": "The president said the talks with the leaders are over",
    }

    def test_scripts_and_common_words(self):
        for lang, text in self.CASES.items():
            self.assertEqual(L.guess(text), lang, text)

    def test_unsure_cases_return_empty(self):
        for text in ("Hamas attack Israel", "", "12345 !!!", None, "Éclair"):
            self.assertEqual(L.guess(text), "", repr(text))

    def test_mostly_latin_text_with_a_little_arabic_is_not_called_arabic(self):
        self.assertNotEqual(L.guess("Iran سلام hello world from here"), "ar")

    def test_letter_hints_beat_stopwords(self):
        self.assertEqual(L.guess("Mañana"), "es")
        self.assertEqual(L.guess("Straße"), "de")


class AnnotateTests(unittest.TestCase):
    def test_metadata_is_kept_and_normalised_and_gaps_are_guessed(self):
        items = [item(1, text="x", lang="fa-IR"), item(2, text="Москва заявила о новых санкциях"),
                 item(3, text="Hamas attack Israel"), item(4, text="Éclair")]
        L.annotate(items)
        self.assertEqual([i.lang for i in items], ["fa", "ru", "en", ""])

    def test_a_source_language_beats_the_guess(self):
        it = item(1, text="The president said the talks are over", lang="de")
        L.annotate([it])
        self.assertEqual(it.lang, "de")

    def test_needs_translation(self):
        self.assertFalse(L.needs_translation(item(1, lang="en")))
        self.assertTrue(L.needs_translation(item(1, lang="fa")))
        self.assertTrue(L.needs_translation(item(1, lang="")))
        done = item(1, lang="fa")
        done.text_en = "done"
        self.assertFalse(L.needs_translation(done))


class TranslateItemsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Store(self._tmp.name)

    def items(self):
        return [item("p1", text="متن یک", lang="fa"), item("p2", text="متن دو", lang="fa"),
                item("e1", text="English one", lang="en"), item("u1", text="Éclair", lang="")]

    def test_translations_are_applied_normalised_and_cached(self):
        items = self.items()
        reply = [{"i": 0, "lang": "fa", "english": "Talks begin"}, {"i": 1, "lang": "fa-IR", "english": "Sanctions eased"},
                 {"i": 2, "lang": "fr", "english": "Eclair"}]
        llm = ScriptedLLM([reply])
        L.translate_items(llm, items, self.store, cfg())
        self.assertEqual([(i.lang, i.text_en) for i in items],
                         [("fa", "Talks begin"), ("fa", "Sanctions eased"), ("en", ""), ("fr", "Eclair")])
        self.assertEqual(items[0].en, "Talks begin")
        self.assertEqual(items[2].en, "English one")
        self.assertEqual(len(self.store.read(L.TRANSLATIONS_FILE)), 3)
        self.assertEqual(llm.calls[0]["tier"], "fast")
        self.assertNotIn("English one", llm.calls[0]["prompt"])  # English items are never sent

    def test_cache_means_no_second_call(self):
        reply = [{"i": 0, "lang": "fa", "english": "Talks begin"}]
        llm = ScriptedLLM([reply])
        L.translate_items(llm, [item("p1", text="متن", lang="fa")], self.store, cfg())
        again = [item("p1", text="متن", lang="fa")]
        L.translate_items(llm, again, self.store, cfg())
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(again[0].text_en, "Talks begin")

    def test_an_undetermined_answer_keeps_the_existing_guess(self):
        it = item("x", text="Alguna cosa", lang="es")
        L.translate_items(ScriptedLLM([[{"i": 0, "lang": "und", "english": "Something"}]]), [it], self.store, cfg())
        self.assertEqual((it.lang, it.text_en), ("es", "Something"))

    def test_the_model_can_correct_a_wrong_language_guess(self):
        it = item("x", text="Hello there", lang="de")
        L.translate_items(ScriptedLLM([[{"i": 0, "lang": "en", "english": "Hello there"}]]), [it], self.store, cfg())
        self.assertEqual((it.lang, it.text_en, it.en), ("en", "", "Hello there"))

    def test_failure_leaves_items_untranslated_and_uncached(self):
        items = self.items()
        L.translate_items(ScriptedLLM([RuntimeError("down")]), items, self.store, cfg())
        self.assertEqual([i.text_en for i in items], [""] * 4)
        self.assertIsNone(self.store.read(L.TRANSLATIONS_FILE))
        self.assertEqual(items[0].en, "متن یک")  # falls back to the original text

    def test_bad_rows_are_ignored(self):
        items = [item("p1", text="متن", lang="fa")]
        reply = [{"i": 0}, {"i": 5, "english": "x"}, {"i": "zz", "english": "x"}, {"english": "x"}, "junk", None,
                 {"i": 0, "lang": "fa", "english": "ok"}]
        L.translate_items(ScriptedLLM([reply]), items, self.store, cfg())
        self.assertEqual(items[0].text_en, "ok")

    def test_accepts_an_object_with_an_items_key(self):
        it = item("p1", text="متن", lang="fa")
        L.translate_items(ScriptedLLM([{"items": [{"i": 0, "lang": "fa", "english": "ok"}]}]), [it], self.store, cfg())
        self.assertEqual(it.text_en, "ok")

    def test_batches_follow_the_configured_size(self):
        items = [item(f"p{i}", text="متن", lang="fa") for i in range(45)]
        llm = ScriptedLLM([[], [], []])
        L.translate_items(llm, items, self.store, cfg(languages={"batch_size": 20}))
        self.assertEqual(len(llm.calls), 3)

    def test_can_be_disabled(self):
        llm = ScriptedLLM([])
        items = self.items()
        L.translate_items(llm, items, self.store, cfg(languages={"translate": False}))
        self.assertEqual((llm.calls, [i.text_en for i in items]), ([], [""] * 4))

    def test_already_translated_and_english_only_input_costs_nothing(self):
        llm = ScriptedLLM([])
        done = item(1, text="متن", lang="fa")
        done.text_en = "done"
        L.translate_items(llm, [done, item(2, lang="en")], self.store, cfg())
        self.assertEqual(llm.calls, [])

    def test_markup_in_items_is_neutralised_and_the_language_guess_is_shown(self):
        llm = ScriptedLLM([[]])
        L.translate_items(llm, [item(1, text="<script>x</script> متن", lang="fa")], self.store, cfg())
        prompt = llm.calls[0]["prompt"]
        self.assertNotIn("<script>", prompt)
        self.assertIn('lang="fa"', prompt)
        self.assertTrue(prompt.startswith("TASK:translate_items"))
        self.assertIn("do not soften", prompt.lower())


class KeywordTranslationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Store(self._tmp.name)

    def test_default_config_searches_editions_and_site_languages(self):
        self.assertEqual(L.wanted_languages(cfg()), {"ar", "he", "ru", "tr", "de", "fr", "fa"})

    def test_english_and_invalid_codes_are_not_translation_targets(self):
        c = cfg(languages={"search_native": True, "editions": [{"country": "US", "lang": "en"}, {"country": "X", "lang": ""}]},
                news_sites=[{"name": "S", "site": "s.com", "langs": ["en"]}])
        self.assertEqual(L.wanted_languages(c), set())

    def test_translates_once_caps_terms_and_normalises_codes(self):
        topic = {"topic": "Iran talks", "keywords": ["nuclear"]}
        reply = {"ar": ["a1", "a2", "a3", "a4"], "he": ["h1"], "fa-IR": ["p1"], "xx": ["junk"], "ru": "not a list"}
        llm = ScriptedLLM([reply])
        L.translate_keywords(llm, topic, cfg(), self.store)
        self.assertEqual(topic["translations"], {"ar": ["a1", "a2", "a3"], "fa": ["p1"], "he": ["h1"]})
        self.assertIn("Languages: ar, de, fa, fr, he, ru, tr", llm.calls[0]["prompt"])
        self.assertIn("Iran talks", llm.calls[0]["prompt"])
        self.assertEqual(llm.calls[0]["tier"], "fast")

    def test_only_missing_languages_are_asked_for_next_time(self):
        topic = {"topic": "Iran talks", "keywords": []}
        llm = ScriptedLLM([{"ar": ["a"], "he": ["h"], "fa": ["p"]}, {"ru": ["r"]}])
        L.translate_keywords(llm, topic, cfg(), self.store)
        again = {"topic": "Iran talks", "keywords": []}
        L.translate_keywords(llm, again, cfg(), self.store)
        self.assertIn("Languages: de, fr, ru, tr", llm.calls[1]["prompt"])
        self.assertEqual(again["translations"]["ru"], ["r"])
        self.assertEqual(again["translations"]["ar"], ["a"])

    def test_nothing_missing_means_no_call(self):
        topic = {"topic": "T", "keywords": []}
        langs = {l: [l] for l in L.wanted_languages(cfg())}
        llm = ScriptedLLM([langs])
        L.translate_keywords(llm, topic, cfg(), self.store)
        L.translate_keywords(llm, {"topic": "T", "keywords": []}, cfg(), self.store)
        self.assertEqual(len(llm.calls), 1)

    def test_failure_gives_no_translations_and_is_retried_later(self):
        topic = {"topic": "T", "keywords": []}
        L.translate_keywords(ScriptedLLM([RuntimeError("down")]), topic, cfg(), self.store)
        self.assertEqual(topic["translations"], {})
        self.assertIsNone(self.store.read(L.KEYWORDS_FILE))

    def test_no_target_languages_means_no_call(self):
        llm = ScriptedLLM([])
        topic = {"topic": "T", "keywords": []}
        L.translate_keywords(llm, topic, cfg(languages={"search_native": False}, news_sites=[]), self.store)
        self.assertEqual((topic["translations"], llm.calls), ({}, []))


if __name__ == "__main__":
    unittest.main()
