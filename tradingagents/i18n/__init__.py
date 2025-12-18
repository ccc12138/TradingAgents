from tradingagents.i18n import en, zh

_TRANSLATIONS = {"en": en.TEXTS, "zh": zh.TEXTS}


def get_text(key: str, lang: str = "en") -> str:
    """Get translated text by key. Falls back to English if key missing."""
    texts = _TRANSLATIONS.get(lang, _TRANSLATIONS["en"])
    return texts.get(key, _TRANSLATIONS["en"].get(key, key))
