"""Language support: detect the language of each item, translate non-English items to English for
analysis (originals are kept and shown), and translate topic keywords so topics can be searched in
other languages.

Detection order: the source's own metadata (Bluesky, Mastodon, RSS, Google News edition) is trusted
first; only items without metadata are guessed from their script and common words."""
import re

from . import prompts
from .util import clip, log, short_hash, slugify

TRANSLATIONS_FILE = "translations.json"
KEYWORDS_FILE = "keyword_translations.json"

NAMES = {
    "en": "English", "ar": "Arabic", "he": "Hebrew", "fa": "Persian", "ur": "Urdu", "ru": "Russian",
    "uk": "Ukrainian", "tr": "Turkish", "de": "German", "fr": "French", "es": "Spanish",
    "pt": "Portuguese", "it": "Italian", "nl": "Dutch", "zh": "Chinese", "ja": "Japanese",
    "ko": "Korean", "hi": "Hindi", "bn": "Bengali", "th": "Thai", "el": "Greek", "id": "Indonesian",
    "ms": "Malay", "vi": "Vietnamese", "pl": "Polish", "cs": "Czech", "hu": "Hungarian",
    "ro": "Romanian", "bg": "Bulgarian", "sr": "Serbian", "hr": "Croatian", "sv": "Swedish",
    "no": "Norwegian", "da": "Danish", "fi": "Finnish", "az": "Azerbaijani", "kk": "Kazakh",
    "ka": "Georgian", "hy": "Armenian", "sw": "Swahili", "sk": "Slovak", "sl": "Slovenian",
    "lt": "Lithuanian", "lv": "Latvian", "et": "Estonian", "is": "Icelandic", "ga": "Irish", "ca": "Catalan",
    "eu": "Basque", "gl": "Galician", "af": "Afrikaans", "sq": "Albanian", "mk": "Macedonian",
    "bs": "Bosnian", "mt": "Maltese", "lb": "Luxembourgish", "tl": "Filipino", "ta": "Tamil",
    "te": "Telugu", "ml": "Malayalam", "kn": "Kannada", "mr": "Marathi", "gu": "Gujarati",
    "pa": "Punjabi", "ne": "Nepali", "si": "Sinhala", "my": "Burmese", "km": "Khmer", "mn": "Mongolian",
    "ps": "Pashto", "ku": "Kurdish", "am": "Amharic", "so": "Somali", "ha": "Hausa", "yo": "Yoruba",
    "zu": "Zulu", "la": "Latin", "eo": "Esperanto", "cy": "Welsh", "be": "Belarusian",
}
UNDETERMINED = {"und", "zxx", "mul", "mis", "xx"}   # "language undetermined" style codes, not languages


def name(code):
    return NAMES.get(code, code or "unknown")


def norm(code):
    """'fa-IR' -> 'fa', 'iw' -> 'he'; anything that is not a plausible language code -> ''."""
    c = str(code or "").strip().lower().replace("_", "-").split("-")[0]
    c = {"iw": "he", "in": "id", "nb": "no", "nn": "no"}.get(c, c)
    return c if c.isalpha() and 2 <= len(c) <= 3 and c not in UNDETERMINED else ""


# ------------------------------------------------------------- guessing
def _script(ch):
    o = ord(ch)
    if 0x0600 <= o <= 0x077F or 0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF:
        return "arabic"
    if 0x0590 <= o <= 0x05FF:
        return "hebrew"
    if 0x0400 <= o <= 0x052F:
        return "cyrillic"
    if 0x0370 <= o <= 0x03FF or 0x1F00 <= o <= 0x1FFF:
        return "greek"
    if 0x0900 <= o <= 0x097F:
        return "devanagari"
    if 0x0980 <= o <= 0x09FF:
        return "bengali"
    if 0x0E00 <= o <= 0x0E7F:
        return "thai"
    if 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF:
        return "hangul"
    if 0x3040 <= o <= 0x30FF:
        return "kana"
    if 0x3400 <= o <= 0x9FFF:
        return "han"
    if ch.isalpha():
        return "latin" if o < 0x250 else "other"
    return ""


STOPWORDS = {
    "en": "the and of to in is for on with that at by from as are was has have will over after says".split(),
    "es": "el la los las de del que y en un una por con para se su al es más tras".split(),
    "fr": "le la les des du de et en un une pour dans sur que qui est au aux par avec après".split(),
    "de": "der die das und in den von zu mit für auf ist im dem nicht ein eine nach bei über".split(),
    "pt": "o a os as de do da dos das e em um uma para com por que não no na".split(),
    "it": "il lo la i gli le di del della e in un una per con che non sono dopo".split(),
    "nl": "de het een en van in op te voor met is dat die zijn aan naar bij".split(),
}
LETTER_HINTS = [("tr", "ğışİ"), ("es", "ñ¿¡"), ("pt", "ãõ"), ("de", "ß"), ("pl", "ąęłńśźż"),
                ("ro", "ăâîșț"), ("hu", "őű"), ("vi", "ơưăđ")]


def guess(text):
    """Best-effort language code from the text alone; '' when unsure. Only used when the source gave none."""
    letters = [c for c in (text or "") if c.isalpha()]
    if not letters:
        return ""
    counts = {}
    for c in letters:
        sc = _script(c)
        counts[sc] = counts.get(sc, 0) + 1
    script, top = max(counts.items(), key=lambda kv: kv[1])
    if script in ("kana", "han", "hangul"):
        cjk = counts.get("kana", 0) + counts.get("han", 0) + counts.get("hangul", 0)
        if cjk / len(letters) < 0.5:
            return ""
        if counts.get("kana", 0):
            return "ja"
        return "ko" if counts.get("hangul", 0) > counts.get("han", 0) else "zh"
    if top / len(letters) < 0.5:
        return ""
    if script == "arabic":
        if any(c in text for c in "ٹڈڑںےہھ"):
            return "ur"
        if any(c in text for c in "پچژگکی"):
            return "fa"
        return "ar"
    if script == "cyrillic":
        if any(c in text for c in "іїєґІЇЄҐ"):
            return "uk"
        if any(c in text for c in "ђћљњ"):
            return "sr"
        return "ru"
    simple = {"hebrew": "he", "greek": "el", "devanagari": "hi", "bengali": "bn", "thai": "th"}
    if script in simple:
        return simple[script]
    if script != "latin":
        return ""
    lowered = text.lower()
    for lang, chars in LETTER_HINTS:
        if any(c in lowered for c in chars):
            return lang
    words = re.findall(r"[^\W\d_]+", lowered)
    scores = sorted(((sum(w in sw for w in words), lang) for lang, sw in STOPWORDS.items()), reverse=True)
    (best, lang), second = scores[0], scores[1][0]
    return lang if best >= 2 and best > second else ""


def annotate(items):
    """Set item.lang: keep the source's metadata, otherwise guess; plain ASCII with no clue is taken as English."""
    for it in items:
        it.lang = norm(it.lang) or guess(it.text) or ("en" if it.text.isascii() else "")


def needs_translation(item):
    return item.lang != "en" and not item.text_en


# ---------------------------------------------------------- translating
def _block(items, max_chars=400):
    lines = []
    for idx, it in enumerate(items):
        text = it.text.replace("\n", " ").replace("<", "‹").replace(">", "›")
        guess_attr = f' lang="{it.lang}"' if it.lang else ""
        lines.append(f'<item i="{idx}"{guess_attr}>{clip(text, max_chars)}</item>')
    return "\n".join(lines)


def _apply(item, lang, english):
    item.lang = lang or item.lang
    item.text_en = "" if item.lang == "en" else english


def translate_items(llm, items, store, cfg):
    """Translate non-English items into English (item.text_en). Results are cached per item."""
    lc = cfg.get("languages", {})
    if not lc.get("translate", True):
        return
    cache = store.read(TRANSLATIONS_FILE, {}) or {}
    todo = []
    for it in items:
        if not needs_translation(it):
            continue
        hit = cache.get(short_hash(it.id))
        if hit:
            _apply(it, norm(hit.get("lang")), hit.get("english", ""))
        else:
            todo.append(it)

    changed, size = False, lc.get("batch_size", 20)
    for start in range(0, len(todo), size):
        batch = todo[start:start + size]
        try:
            data = llm.complete_json(prompts.SYSTEM, prompts.translate_items(_block(batch)),
                                     tier="fast", max_tokens=4000)
        except Exception as e:      # untranslated items are analysed in their original language
            log.warning("translation failed: %s", e)
            continue
        if isinstance(data, dict):
            data = data.get("items", [])
        for row in data:
            try:
                j, english = int(row["i"]), str(row.get("english", "")).strip()
            except (KeyError, ValueError, TypeError, AttributeError):
                continue
            if not 0 <= j < len(batch) or not english:
                continue
            _apply(batch[j], norm(row.get("lang")), english)
            cache[short_hash(batch[j].id)] = {"lang": batch[j].lang, "english": english}
            changed = True
    if changed:
        store.write(TRANSLATIONS_FILE, cache)


def wanted_languages(cfg):
    lc = cfg.get("languages", {})
    langs = set()
    if lc.get("search_native"):
        langs |= {norm(e.get("lang")) for e in lc.get("editions", [])}
    for site in cfg.get("news_sites", []):
        langs |= {norm(c) for c in site.get("langs", [])}
    langs.discard("en")
    langs.discard("")
    return langs


def translate_keywords(llm, topic, cfg, store):
    """Set topic['translations'] = {lang: [search terms]} for every language we search in. Cached per topic."""
    langs = wanted_languages(cfg)
    if not langs:
        topic["translations"] = {}
        return
    cache = store.read(KEYWORDS_FILE, {}) or {}
    slug = slugify(topic["topic"])
    entry = cache.get(slug, {})
    missing = sorted(langs - set(entry))
    if missing:
        try:
            data = llm.complete_json(prompts.SYSTEM,
                                     prompts.translate_keywords(topic["topic"], topic.get("keywords", []), missing),
                                     tier="fast", max_tokens=1500)
        except Exception as e:
            log.warning("keyword translation failed: %s", e)
            data = {}
        for lang, terms in (data.items() if isinstance(data, dict) else []):
            lang = norm(lang)
            if lang in missing and isinstance(terms, list):
                clean = [str(t).strip() for t in terms if str(t).strip()][:3]
                if clean:
                    entry[lang] = clean
        if entry:
            cache[slug] = entry
            store.write(KEYWORDS_FILE, cache)
    topic["translations"] = {l: entry[l] for l in sorted(langs) if l in entry}
