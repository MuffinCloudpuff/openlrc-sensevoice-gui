from __future__ import annotations

LANGUAGE_LABELS = {
    "zh": "Chinese",
    "zh-cn": "Simplified Chinese",
    "zh-tw": "Traditional Chinese",
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "ru": "Russian",
}


def language_name(code: str | None) -> str:
    if not code:
        return "the source language"
    return LANGUAGE_LABELS.get(code.lower(), code)


def build_local_translation_prompt(text: str, target_lang: str) -> str:
    return (
        f"Translate the following subtitle line into {language_name(target_lang)}. "
        "Output only the translation without explanation.\n\n"
        f"{text.replace(chr(10), ' ').strip()}"
    )


def build_local_batch_translation_prompt(texts: list[str], target_lang: str) -> str:
    numbered_lines = "\n".join(f"{idx}. {text.replace(chr(10), ' ').strip()}" for idx, text in enumerate(texts, start=1))
    return (
        f"Translate the following subtitle lines into {language_name(target_lang)}. "
        "Keep the same number of lines. Output only the translations, one line per input line, "
        "without numbering or explanation.\n\n"
        f"{numbered_lines}"
    )
