#  Copyright (C) 2024. Hao Zheng
#  All rights reserved.

SENSEVOICE_MODEL_PRESETS = {
    "small": "iic/SenseVoiceSmall",
    "large": "iic/SenseVoiceLarge",
}


def resolve_sensevoice_model(model_name: str) -> str:
    """
    Normalize a user-facing SenseVoice model alias into the concrete model id.

    Examples:
        ``small`` -> ``iic/SenseVoiceSmall``
        ``large`` -> ``iic/SenseVoiceLarge``
    """

    return SENSEVOICE_MODEL_PRESETS.get(model_name.strip().lower(), model_name)


# SenseVoice ASR options for FunASR
# See https://github.com/modelscope/FunASR and https://github.com/FunAudioLLM/SenseVoice
default_sensevoice_options = {
    "batch_size_s": 60,       # Batch size in seconds for processing
    "merge_length_s": 15,     # Merge VAD segments up to this length (seconds)
    "use_itn": True,          # Inverse text normalization (punctuation, numbers)
    "output_timestamp": True, # Enable character-level timestamps
}

# Kept for backward compatibility with legacy code / tests
default_asr_options = default_sensevoice_options

# Check https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py#L123 for details
# Note: VAD is now handled by FunASR's fsmn-vad internally, these options are passed to vad_kwargs
default_vad_options = {
    "max_single_segment_time": 30000,  # Max segment duration in ms (30 seconds)
}

default_preprocess_options = {"atten_lim_db": 15, "preprocess_workers": 0}

# Currently bottleneck-ed by Spacy
supported_languages = {
    "ca",
    "zh",
    "hr",
    "da",
    "nl",
    "en",
    "fi",
    "fr",
    "de",
    "el",
    "it",
    "ja",
    "ko",
    "lt",
    "mk",
    "nb",
    "pl",
    "pt",
    "ro",
    "ru",
    "sl",
    "es",
    "sv",
    "uk",
}

supported_languages_lingua = {
    "CATALAN",
    "CHINESE",
    "CROATIAN",
    "DANISH",
    "DUTCH",
    "ENGLISH",
    "FINNISH",
    "FRENCH",
    "GERMAN",
    "GREEK",
    "ITALIAN",
    "JAPANESE",
    "KOREAN",
    "LITHUANIAN",
    "MACEDONIAN",
    "BOKMAL",
    "POLISH",
    "PORTUGUESE",
    "ROMANIAN",
    "RUSSIAN",
    "SLOVENE",
    "SPANISH",
    "SWEDISH",
    "UKRAINIAN",
}
