from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

from openlrc import LRCer, ModelConfig, ModelProvider, TranscriptionConfig, TranslationConfig, list_chatbot_models
from openlrc.context import TranslateInfo
from openlrc.directory_workflow import STATUS_ASR_DONE, STATUS_TRANSLATION_PENDING, DirectoryTask, store_asr_cache
from openlrc.gui_streamlit.utils import get_asr_options, get_preprocess_options, get_vad_options
from openlrc.logger import logger
from openlrc.models import Models
from openlrc.prompter import ChunkedTranslatePrompter, ContextReviewPrompter
from openlrc.subtitle import Subtitle
from openlrc.translate import LLMTranslator
from openlrc.utils import get_messages_token_number, get_text_token_number

from ..models import AppConfig


def ensure_file_logger(log_path: Path) -> logging.FileHandler:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler) and Path(handler.baseFilename).resolve() == log_path.resolve():
            return handler

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logger.level)
    file_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)-8s [%(threadName)s] %(message)s"))
    logger.addHandler(file_handler)
    return file_handler


def close_file_logger(log_path: Path | None) -> None:
    if log_path is None:
        return

    target = log_path.resolve()
    for handler in list(logger.handlers):
        if not isinstance(handler, logging.FileHandler):
            continue
        if Path(handler.baseFilename).resolve() != target:
            continue
        logger.removeHandler(handler)
        handler.close()


def apply_runtime_api_keys(config: AppConfig) -> None:
    key_map = {
        "OPENAI_API_KEY": config.openai_api_key.strip(),
        "ANTHROPIC_API_KEY": config.anthropic_api_key.strip(),
        "GOOGLE_API_KEY": config.google_api_key.strip(),
        "OPENROUTER_API_KEY": config.openrouter_api_key.strip(),
    }
    for env_name, value in key_map.items():
        if value:
            os.environ[env_name] = value


def resolve_relay_api_key(config: AppConfig) -> str:
    explicit = config.relay_api_key.strip()
    if explicit:
        return explicit

    base_url = config.relay_base_url.lower()
    if config.relay_provider == "OpenAI 兼容":
        if "openrouter.ai" in base_url:
            return config.openrouter_api_key.strip() or config.openai_api_key.strip()
        return config.openai_api_key.strip() or config.openrouter_api_key.strip()
    if config.relay_provider == "Anthropic 兼容":
        return config.anthropic_api_key.strip()
    return ""


def resolve_chatbot_model(config: AppConfig) -> str:
    if config.chatbot_model:
        return config.chatbot_model
    available_models = sorted(set(list_chatbot_models()))
    if "gpt-4.1-nano" in available_models:
        return "gpt-4.1-nano"
    return available_models[0]


def build_translation_model(config: AppConfig) -> str | ModelConfig:
    if config.translation_backend == "官方 API":
        return resolve_chatbot_model(config)
    if config.translation_backend == "本地 HY-MT":
        return resolve_chatbot_model(config)

    relay_api_key = resolve_relay_api_key(config)
    return ModelConfig(
        provider=ModelProvider.OPENAI if config.relay_provider == "OpenAI 兼容" else ModelProvider.ANTHROPIC,
        name=config.relay_model_name.strip(),
        base_url=config.relay_base_url.strip(),
        api_key=relay_api_key or None,
        proxy=config.proxy.strip() or None,
    )


def build_lrcer(config: AppConfig) -> tuple[LRCer, str | ModelConfig]:
    translation_model = build_translation_model(config)
    lrcer = LRCer(
        transcription=TranscriptionConfig(
            asr_model=config.asr_model,
            compute_type=config.compute_type,
            device=config.device,
            asr_options=get_asr_options(config.batch_size_s, config.merge_length_s, config.use_itn, config.output_timestamp),
            vad_options=get_vad_options(config.max_single_segment_time),
            preprocess_options=get_preprocess_options(config.atten_lim_db),
        ),
        translation=TranslationConfig(
            chatbot_model=translation_model,
            fee_limit=config.fee_limit,
            consumer_thread=config.consumer_thread,
            proxy=config.proxy.strip() or None,
        ),
    )
    return lrcer, translation_model


def is_local_translation_backend(config: AppConfig) -> bool:
    return config.translation_backend == "本地 HY-MT"


def normalize_src_lang(src_lang: str) -> str | None:
    return None if src_lang == "自动检测" else src_lang


def run_asr_for_task(
    lrcer: LRCer,
    task: DirectoryTask,
    src_lang: str | None,
    noise_suppress: bool,
    target_lang: str | None,
    cache_status: str,
) -> tuple[Path, Path]:
    audio_paths = lrcer.pre_process([task.audio_path], noise_suppress=noise_suppress)
    if not audio_paths:
        raise RuntimeError(f"预处理未返回音频：{task.relative_path}")

    transcribed_path = lrcer._transcribe_single(audio_paths[0], src_lang)
    transcribed_sub = Subtitle.from_json(transcribed_path)
    transcribed_opt_sub = lrcer.post_process(transcribed_sub, update_name=True)
    optimized_path = transcribed_opt_sub.filename
    store_asr_cache(task, transcribed_path, optimized_path, target_lang=target_lang, status=cache_status)
    return transcribed_path, optimized_path


def confirmation_id(root_dir: Path, target_lang: str, entries: list[dict]) -> str:
    digest_source = "|".join([str(root_dir), target_lang, *[entry["relative_path"] for entry in entries]])
    return hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:12]


def build_translation_confirmation_state(root_dir: Path, target_lang: str, entries: list[dict]) -> dict:
    total_floor_fee = sum(float(entry["estimate"]["total_floor_fee"]) for entry in entries)
    total_likely_fee = sum(float(entry["estimate"]["total_likely_fee"]) for entry in entries)
    state = {
        "root_dir": str(root_dir),
        "target_lang": target_lang,
        "entries": entries,
        "total_floor_fee": total_floor_fee,
        "total_likely_fee": total_likely_fee,
    }
    state["id"] = confirmation_id(root_dir, target_lang, entries)
    return state


def selected_fee_summary(state: dict, selected_relative_paths: list[str]) -> tuple[float, float]:
    selected_set = set(selected_relative_paths)
    floor_fee = 0.0
    likely_fee = 0.0
    for entry in state.get("entries", []):
        if entry["relative_path"] not in selected_set:
            continue
        floor_fee += float(entry["estimate"]["total_floor_fee"])
        likely_fee += float(entry["estimate"]["total_likely_fee"])
    return floor_fee, likely_fee


def resolve_model_name_for_estimation(chatbot_model: str | ModelConfig) -> str:
    return chatbot_model.name if isinstance(chatbot_model, ModelConfig) else chatbot_model


def estimate_message_tokens(messages: list[dict], model_name: str) -> tuple[int, int]:
    try:
        total_tokens = get_messages_token_number(messages, model=model_name)
        user_tokens = sum(
            get_text_token_number(message["content"], model=model_name)
            for message in messages
            if message["role"] == "user"
        )
    except Exception:
        total_tokens = get_messages_token_number(messages, model="gpt-4o-mini")
        user_tokens = sum(
            get_text_token_number(message["content"], model="gpt-4o-mini")
            for message in messages
            if message["role"] == "user"
        )
    return total_tokens, user_tokens


def estimate_message_fee(messages: list[dict], model_name: str) -> dict[str, float]:
    model_info = Models.get_model(model_name)
    input_tokens, user_tokens = estimate_message_tokens(messages, model_name)
    estimated_output_tokens = max(1, user_tokens * 2)
    fee = (input_tokens * model_info.input_price + estimated_output_tokens * model_info.output_price) / 1_000_000
    return {
        "input_tokens": float(input_tokens),
        "user_tokens": float(user_tokens),
        "estimated_output_tokens": float(estimated_output_tokens),
        "estimated_fee": fee,
    }


def build_token_placeholder(token_count: int) -> str:
    if token_count <= 0:
        return ""
    return "placeholder " * token_count


def estimate_translation_fee(
    texts: list[str],
    src_lang: str,
    target_lang: str,
    chatbot_model: str | ModelConfig,
    *,
    title: str = "",
    glossary: dict | None = None,
) -> dict[str, float | int]:
    model_name = resolve_model_name_for_estimation(chatbot_model)
    info = TranslateInfo(title=title, audio_type="Movie", glossary=glossary)

    context_prompter = ContextReviewPrompter(src_lang, target_lang)
    context_messages = [
        {"role": "system", "content": context_prompter.system()},
        {"role": "user", "content": context_prompter.user("\n".join(texts), title=title, given_glossary=glossary)},
    ]
    context_estimate = estimate_message_fee(context_messages, model_name)
    estimated_guideline_tokens = int(max(300, min(4000, context_estimate["estimated_output_tokens"])))

    translate_prompter = ChunkedTranslatePrompter(src_lang, target_lang, info)
    summary_placeholder_tokens = 80
    chunks = LLMTranslator.make_chunks(texts)
    chunk_floor_fee = 0.0
    chunk_likely_fee = 0.0

    for idx, chunk in enumerate(chunks, start=1):
        user_input = translate_prompter.format_texts(chunk)
        summaries_str = build_token_placeholder(summary_placeholder_tokens * max(idx - 1, 0))
        floor_messages = [
            {"role": "system", "content": translate_prompter.system()},
            {"role": "user", "content": translate_prompter.user(idx, user_input, summaries=summaries_str, guideline="")},
        ]
        likely_messages = [
            {"role": "system", "content": translate_prompter.system()},
            {
                "role": "user",
                "content": translate_prompter.user(
                    idx,
                    user_input,
                    summaries=summaries_str,
                    guideline=build_token_placeholder(estimated_guideline_tokens),
                ),
            },
        ]
        chunk_floor_fee += estimate_message_fee(floor_messages, model_name)["estimated_fee"]
        chunk_likely_fee += estimate_message_fee(likely_messages, model_name)["estimated_fee"]

    return {
        "chunk_count": len(chunks),
        "line_count": len(texts),
        "context_fee": context_estimate["estimated_fee"],
        "chunk_floor_fee": chunk_floor_fee,
        "chunk_likely_fee": chunk_likely_fee,
        "total_floor_fee": context_estimate["estimated_fee"] + chunk_floor_fee,
        "total_likely_fee": context_estimate["estimated_fee"] + chunk_likely_fee,
        "estimated_guideline_tokens": estimated_guideline_tokens,
    }
