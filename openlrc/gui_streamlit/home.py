#  Copyright (C) 2024. Hao Zheng
#  All rights reserved.

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import hashlib
import logging
import time
import sys
import json
import concurrent.futures
from pathlib import Path
from zipfile import ZipFile

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from openlrc import LRCer, ModelConfig, ModelProvider, TranscriptionConfig, TranslationConfig, list_chatbot_models
from openlrc.context import TranslateInfo
from openlrc.logger import logger
from openlrc.models import Models
from openlrc.prompter import ChunkedTranslatePrompter, ContextReviewPrompter
from openlrc.subtitle import Subtitle
from openlrc.translate import LLMTranslator
from openlrc.gui_streamlit.utils import (
    detect_relay_models,
    get_asr_options,
    get_preprocess_options,
    get_vad_options,
)
from openlrc.utils import get_messages_token_number, get_text_token_number

st.set_page_config(page_title="OpenLRC", page_icon="Audio", layout="wide")

st.title("OpenLRC")
st.caption("使用 SenseVoice 和大语言模型进行音频转写与字幕翻译。")
st.markdown("[zh-plus/openlrc](https://github.com/zh-plus/openlrc)")

st.sidebar.header("配置")

GUI_CONFIG_PATH = PROJECT_ROOT / ".openlrc_gui_config.json"


def load_gui_config() -> dict:
    if not GUI_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(GUI_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_gui_config(config: dict) -> None:
    GUI_CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


saved_gui_config = load_gui_config()


def detect_default_device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def has_nvidia_gpu() -> bool:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return False

    try:
        result = subprocess.run([nvidia_smi, "-L"], capture_output=True, text=True, timeout=5, check=False)
        return result.returncode == 0 and bool(result.stdout.strip())
    except Exception:
        return False


def normalize_output_dir(raw_output_dir: str) -> Path:
    output_dir = Path(raw_output_dir).expanduser()
    if not output_dir.is_absolute():
        output_dir = Path.cwd() / output_dir
    return output_dir.resolve()


def persist_result_files(results: list[str], output_dir: Path) -> tuple[list[Path], Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    copied_files = []

    for result in results:
        src = Path(result)
        dst = output_dir / src.name
        shutil.copy2(src, dst)
        copied_files.append(dst)

    if len(copied_files) == 1:
        return copied_files, copied_files[0]

    zip_path = output_dir / "openlrc_results.zip"
    with ZipFile(zip_path, "w") as zip_object:
        for file_path in copied_files:
            zip_object.write(file_path, arcname=file_path.name)

    return copied_files, zip_path


def persist_intermediate_jsons(transcribed_paths: list[Path], artifact_dir: Path, lrcer: LRCer) -> list[Path]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    copied_files: list[Path] = []

    for transcribed_path in transcribed_paths:
        base_name = lrcer._get_base_name(transcribed_path)
        candidates = [
            (transcribed_path, artifact_dir / f"{base_name}_asr_raw.json"),
            (transcribed_path.with_name(f"{base_name}_preprocessed_transcribed_optimized.json"), artifact_dir / f"{base_name}_asr_optimized.json"),
            (transcribed_path.with_name(f"{base_name}.json"), artifact_dir / f"{base_name}_final.json"),
        ]

        for src, dst in candidates:
            if src.exists():
                shutil.copy2(src, dst)
                copied_files.append(dst)

    return copied_files


def ensure_file_logger(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    resolved = str(log_path.resolve())

    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler) and Path(handler.baseFilename).resolve() == log_path.resolve():
            return

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logger.level)
    file_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)-8s [%(threadName)s] %(message)s"))
    logger.addHandler(file_handler)


def read_log_tail(log_path: Path, max_lines: int = 120) -> str:
    if not log_path.exists():
        return ""
    lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return "\n".join(lines[-max_lines:])


def resolve_model_name_for_estimation(chatbot_model: str | ModelConfig) -> str:
    return chatbot_model.name if isinstance(chatbot_model, ModelConfig) else chatbot_model


def estimate_token_count(text: str, model_name: str) -> int:
    try:
        return get_text_token_number(text, model=model_name)
    except Exception:
        return get_text_token_number(text, model="gpt-4o-mini")


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


def apply_runtime_api_keys(
    openai_key: str, anthropic_key: str, google_key: str, openrouter_key: str
) -> None:
    key_map = {
        "OPENAI_API_KEY": openai_key,
        "ANTHROPIC_API_KEY": anthropic_key,
        "GOOGLE_API_KEY": google_key,
        "OPENROUTER_API_KEY": openrouter_key,
    }
    for env_name, value in key_map.items():
        if value.strip():
            os.environ[env_name] = value.strip()


def wait_for_translation_result(
    lrcer: LRCer,
    base_name: str,
    target_lang: str,
    transcribed_opt_sub: Subtitle,
    log_path: Path,
    log_live,
    current_file_status,
    idx: int,
    total: int,
):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(lrcer._build_final_subtitle, base_name, target_lang, transcribed_opt_sub, False)
        tick = 0
        while not future.done():
            dots = "." * (tick % 3 + 1)
            current_file_status.caption(
                f"正在调用 LLM 翻译 {idx}/{total}：`{transcribed_opt_sub.filename.name}` {dots}"
            )
            log_live.code(read_log_tail(log_path) or "日志为空。")
            time.sleep(0.5)
            tick += 1

        log_live.code(read_log_tail(log_path) or "日志为空。")
        final_subtitle = future.result()

    if final_subtitle is None:
        if lrcer.exception:
            raise lrcer.exception
        raise RuntimeError("翻译步骤未返回字幕结果。")

    return final_subtitle


def stage_progress(stage_index: int, stage_total: int, item_index: int | None = None, item_total: int | None = None) -> float:
    if item_index is None or item_total is None or item_total <= 0:
        progress = stage_index / stage_total
    else:
        progress = (stage_index - 1 + item_index / item_total) / stage_total
    return max(0.0, min(1.0, progress))


def stage_progress_within(stage_index: int, stage_total: int, portion: float) -> float:
    progress = (stage_index - 1 + portion) / stage_total
    return max(0.0, min(1.0, progress))

with st.sidebar.popover("API 密钥"):
    openai_api_key = st.text_input("OpenAI API Key", value=os.environ.get("OPENAI_API_KEY", ""), key="openai_api")
    anthropic_api_key = st.text_input(
        "Anthropic API Key", value=os.environ.get("ANTHROPIC_API_KEY", ""), key="anthropic_api"
    )
    google_api_key = st.text_input("Google API Key", value=os.environ.get("GOOGLE_API_KEY", ""), key="google_api")
    openrouter_api_key = st.text_input(
        "OpenRouter API Key", value=os.environ.get("OPENROUTER_API_KEY", ""), key="openrouter_api"
    )

default_device = detect_default_device()

asr_model = st.sidebar.selectbox(
    "SenseVoice 模型",
    ["small", "large", "iic/SenseVoiceSmall", "iic/SenseVoiceLarge"],
    index=["small", "large", "iic/SenseVoiceSmall", "iic/SenseVoiceLarge"].index(
        saved_gui_config.get("asr_model", "small")
    )
    if saved_gui_config.get("asr_model", "small") in ["small", "large", "iic/SenseVoiceSmall", "iic/SenseVoiceLarge"]
    else 0,
    key="asr_model",
    help="推荐默认使用 small。large 更重，可能需要更多显存或内存。",
)
device_options = ["cuda", "cpu"] if default_device == "cuda" else ["cpu", "cuda"]
device = st.sidebar.selectbox(
    "运行设备",
    device_options,
    index=device_options.index(saved_gui_config.get("device", device_options[0]))
    if saved_gui_config.get("device", device_options[0]) in device_options
    else 0,
    key="device",
    help="默认按当前机器环境自动选择。若检测到 NVIDIA GPU，会优先使用 cuda。",
)
compute_type = st.sidebar.selectbox(
    "计算精度",
    ["int8", "int8_float16", "int16", "float16", "float32"],
    index=["int8", "int8_float16", "int16", "float16", "float32"].index(saved_gui_config.get("compute_type", "float16"))
    if saved_gui_config.get("compute_type", "float16") in ["int8", "int8_float16", "int16", "float16", "float32"]
    else 3,
    key="compute_type",
)
proxy = st.sidebar.text_input(
    "代理",
    value=saved_gui_config.get("proxy", ""),
    help="例如 http://127.0.0.1:7890",
    key="proxy",
)
output_dir = st.sidebar.text_input(
    "输出目录",
    value=saved_gui_config.get("output_dir", str(Path.cwd() / "output")),
    help="生成的字幕文件会复制到这里，而不是留在临时上传目录。",
)
st.sidebar.caption(f"当前设备选择：`{device}`")
if has_nvidia_gpu() and default_device != "cuda":
    st.sidebar.warning("检测到 NVIDIA 显卡，但当前 Python/PyTorch 不是 CUDA 版；现在会按 CPU 跑。")
st.sidebar.caption(f"输出目录：`{normalize_output_dir(output_dir)}`")

last_log_path = st.session_state.get("last_log_path")
if last_log_path:
    st.sidebar.caption(f"最近一次日志：`{last_log_path}`")

available_chatbot_models = sorted(set(list_chatbot_models()))
default_chatbot_model = "gpt-4.1-nano" if "gpt-4.1-nano" in available_chatbot_models else available_chatbot_models[0]


def resolve_relay_api_key(provider_label: str, base_url: str, explicit_api_key: str) -> str:
    if explicit_api_key.strip():
        return explicit_api_key.strip()

    if provider_label == "OpenAI 兼容":
        if "openrouter.ai" in base_url.lower():
            return openrouter_api_key.strip() or openai_api_key.strip()
        return openai_api_key.strip() or openrouter_api_key.strip()

    if provider_label == "Anthropic 兼容":
        return anthropic_api_key.strip()

    return ""


def relay_detect_state_key(provider_label: str, base_url: str, api_key: str) -> str:
    digest = hashlib.sha256(f"{provider_label}|{base_url.strip()}|{api_key.strip()}".encode("utf-8")).hexdigest()[:12]
    return f"{provider_label}|{base_url.strip()}|{digest}"


use_custom_translation_endpoint = st.sidebar.checkbox(
    "使用中转 / 自定义接口",
    value=saved_gui_config.get("use_custom_translation_endpoint", False),
    help="适用于 OpenAI/Anthropic 兼容中转、OpenRouter 或其它第三方平台。",
)

if use_custom_translation_endpoint:
    relay_provider = st.sidebar.selectbox(
        "中转提供商类型",
        ["OpenAI 兼容", "Anthropic 兼容"],
        index=["OpenAI 兼容", "Anthropic 兼容"].index(saved_gui_config.get("relay_provider", "OpenAI 兼容"))
        if saved_gui_config.get("relay_provider", "OpenAI 兼容") in ["OpenAI 兼容", "Anthropic 兼容"]
        else 0,
        help="OpenRouter、DeepSeek 风格接口通常选 OpenAI 兼容。",
    )
    relay_base_url = st.sidebar.text_input(
        "Base URL",
        value=saved_gui_config.get(
            "relay_base_url",
            "https://openrouter.ai/api/v1" if relay_provider == "OpenAI 兼容" else "",
        ),
        help="填写第三方中转平台的接口地址。",
    )
    remember_relay_api_key = st.sidebar.checkbox(
        "记住中转 API Key",
        value=saved_gui_config.get("remember_relay_api_key", False),
        help="会把中转 Key 保存在当前项目目录下的 .openlrc_gui_config.json 中。",
    )
    relay_api_key = st.sidebar.text_input(
        "中转 API Key",
        value=saved_gui_config.get("relay_api_key", "") if remember_relay_api_key else "",
        type="password",
        help="优先使用这里填写的 Key；留空时才会尝试环境变量。",
    )
    resolved_relay_api_key = resolve_relay_api_key(relay_provider, relay_base_url, relay_api_key)
    current_detect_key = relay_detect_state_key(relay_provider, relay_base_url, resolved_relay_api_key)
    if st.sidebar.button("探测模型", use_container_width=True):
        if not relay_base_url.strip():
            st.sidebar.error("请先填写 Base URL。")
        elif not resolved_relay_api_key:
            st.sidebar.error("请先填写中转 API Key，或在上方提供可用的环境 Key。")
        else:
            try:
                detected_models = detect_relay_models(
                    provider_kind="openai" if relay_provider == "OpenAI 兼容" else "anthropic",
                    base_url=relay_base_url,
                    api_key=resolved_relay_api_key,
                    proxy=proxy or None,
                )
                st.session_state["relay_detect_key"] = current_detect_key
                st.session_state["relay_detected_models"] = detected_models
                st.session_state["relay_detect_error"] = ""
                st.sidebar.success(f"探测到 {len(detected_models)} 个模型。")
            except Exception as exc:
                st.session_state["relay_detect_key"] = current_detect_key
                st.session_state["relay_detected_models"] = []
                st.session_state["relay_detect_error"] = str(exc)
                st.sidebar.error(str(exc))

    detected_models = (
        st.session_state.get("relay_detected_models", [])
        if st.session_state.get("relay_detect_key") == current_detect_key
        else []
    )
    detect_error = (
        st.session_state.get("relay_detect_error", "")
        if st.session_state.get("relay_detect_key") == current_detect_key
        else ""
    )

    manual_default_model = "google/gemini-2.5-flash" if relay_provider == "OpenAI 兼容" else "claude-3-5-sonnet-latest"
    if detected_models:
        relay_model_name = st.sidebar.selectbox(
            "中转模型名",
            detected_models,
            index=0,
            help="这是从中转平台自动探测出来的模型列表。",
        )
        relay_manual_override = st.sidebar.text_input(
            "手动覆盖模型名（可选）",
            value="",
            help="如果你想用下拉里没有的模型，可以在这里手动覆盖。",
        )
        relay_model_name = relay_manual_override.strip() or relay_model_name
    else:
        relay_model_name = st.sidebar.text_input(
            "中转模型名",
            value=saved_gui_config.get("relay_model_name", manual_default_model),
            help="填写中转平台要求的模型名，例如 google/gemini-2.5-flash 或 deepseek-chat。",
        )
        if detect_error:
            st.sidebar.caption("未能自动探测模型，当前使用手动输入。")
    chatbot_model = None
else:
    chatbot_model = st.sidebar.selectbox(
        "翻译模型",
        available_chatbot_models,
        index=available_chatbot_models.index(saved_gui_config.get("chatbot_model", default_chatbot_model))
        if saved_gui_config.get("chatbot_model", default_chatbot_model) in available_chatbot_models
        else available_chatbot_models.index(default_chatbot_model),
        key="chatbot_model",
    )
    relay_provider = None
    relay_model_name = ""
    relay_base_url = ""
    relay_api_key = ""
    resolved_relay_api_key = ""
    remember_relay_api_key = False

fee_limit = st.sidebar.slider(
    "费用上限（USD）",
    min_value=0.0,
    max_value=10.0,
    value=float(saved_gui_config.get("fee_limit", 0.5)),
    step=0.01,
    key="fee_limit",
)
consumer_thread = st.sidebar.slider("翻译线程数", min_value=1, max_value=12, value=4, step=1, key="consumer_thread")
if fee_limit <= 0.1:
    st.sidebar.warning("当前费用上限较低。几分钟以上的音频在生成上下文后，可能会因为超出上限而中止翻译。")

save_payload = {
    "asr_model": asr_model,
    "device": device,
    "compute_type": compute_type,
    "proxy": proxy,
    "output_dir": output_dir,
    "use_custom_translation_endpoint": use_custom_translation_endpoint,
    "relay_provider": relay_provider,
    "relay_base_url": relay_base_url,
    "relay_model_name": relay_model_name,
    "remember_relay_api_key": remember_relay_api_key,
    "relay_api_key": relay_api_key if remember_relay_api_key else "",
    "fee_limit": fee_limit,
    "chatbot_model": chatbot_model if isinstance(chatbot_model, str) else None,
}
if save_payload != saved_gui_config:
    save_gui_config(save_payload)

with st.sidebar.expander("高级配置", expanded=False):
    st.write("### SenseVoice 选项")
    batch_size_s = st.number_input(
        "批处理时长（秒）", min_value=1, max_value=300, value=60, help="每批处理的音频秒数。"
    )
    merge_length_s = st.number_input(
        "VAD 合并时长（秒）",
        min_value=1,
        max_value=120,
        value=15,
        help="把相邻的 VAD 片段合并到这个长度以内。",
    )
    use_itn = st.checkbox(
        "启用 ITN",
        value=True,
        help="规范化识别结果中的数字和标点。",
    )
    output_timestamp = st.checkbox(
        "输出时间戳",
        value=True,
        help="保留字幕生成所需的时间戳。",
    )

    st.write("### VAD 选项")
    max_single_segment_time = st.number_input(
        "单段最大时长（毫秒）",
        min_value=1000,
        max_value=120000,
        value=30000,
        step=1000,
        help="传给 FunASR 的单个 VAD 片段最大时长。",
    )

    st.write("### 预处理选项")
    atten_lim_db = st.number_input("响度限制（dB）", value=15, min_value=0, help="响度标准化的限制值。")

st.write("## 转写与翻译")

files = st.file_uploader(
    "上传文件",
    accept_multiple_files=True,
    type=["mp3", "wav", "flac", "m4a", "mp4", "avi", "mkv", "webm", "mov", "wmv", "flv"],
)
if files:
    st.caption(f"已加入 {len(files)} 个文件。")
else:
    st.caption("提示：选中文件后，如果上传框里出现 add / Upload 按钮，请再点一次，文件才会真正加入任务。")

src_lang = st.selectbox(
    "源语言",
    options=[
        "自动检测",
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
    ],
    index=0,
    format_func=lambda x: "自动检测" if x == "自动检测" else x.upper(),
)
target_lang = st.text_input("目标语言", value="zh-cn", help="填写目标翻译语言代码。")

col1, col2, col3 = st.columns(3)
with col1:
    skip_trans = st.checkbox("仅转写")
with col2:
    noise_suppress = st.checkbox("降噪")
with col3:
    bilingual_sub = st.checkbox("双语字幕")

submitted = st.button("开始处理", type="primary", use_container_width=True)

if submitted:
    st.info("已收到处理请求，正在检查参数...")
    has_files = bool(files)
    has_any_direct_api_key = any([openai_api_key, anthropic_api_key, google_api_key, openrouter_api_key])
    has_translation_credentials = has_any_direct_api_key or (
        use_custom_translation_endpoint and bool(resolved_relay_api_key)
    )

    if not has_files:
        st.error("请至少上传一个音频或视频文件。")
    elif not skip_trans and not has_translation_credentials:
        st.error("当前启用了翻译，但没有设置任何 API Key。请先在侧边栏填写，或勾选“仅转写”。")
        st.stop()
    elif not skip_trans and use_custom_translation_endpoint and (not relay_model_name.strip() or not relay_base_url.strip()):
        st.error("启用了中转 / 自定义接口时，必须填写模型名和 Base URL。")
        st.stop()
    else:
        src_lang = None if src_lang == "自动检测" else src_lang
        tmpdir = tempfile.mkdtemp(prefix="openlrc-streamlit-")
        normalized_output_dir = normalize_output_dir(output_dir)
        normalized_artifact_dir = PROJECT_ROOT / "json_artifacts"
        log_path = normalized_output_dir / "openlrc_run.log"
        st.session_state["last_log_path"] = str(log_path)
        paths = []
        phase_count = 4
        phase_progress = st.progress(0, text="等待开始...")
        phase_status = st.empty()
        current_file_status = st.empty()
        translation_estimate_status = st.empty()
        log_live = st.empty()

        try:
            ensure_file_logger(log_path)
            apply_runtime_api_keys(openai_api_key, anthropic_api_key, google_api_key, openrouter_api_key)
            translation_model = chatbot_model
            if not skip_trans and use_custom_translation_endpoint:
                st.info(
                    "使用中转接口：\n\n"
                    f"- 类型：`{relay_provider}`\n"
                    f"- Base URL：`{relay_base_url.strip()}`\n"
                    f"- 模型：`{relay_model_name.strip()}`\n"
                    f"- API Key：`{'已填写' if resolved_relay_api_key else '未填写'}`"
                )
                translation_model = ModelConfig(
                    provider=ModelProvider.OPENAI if relay_provider == "OpenAI 兼容" else ModelProvider.ANTHROPIC,
                    name=relay_model_name.strip(),
                    base_url=relay_base_url.strip(),
                    api_key=resolved_relay_api_key or None,
                    proxy=proxy or None,
                )
            elif skip_trans:
                st.info("当前为仅转写模式，不会调用翻译 API。")
            else:
                st.info(f"使用内置翻译模型：`{translation_model}`")

            for file in files:
                file_path = Path(tmpdir) / file.name
                with open(file_path, "wb") as f:
                    f.write(file.read())
                paths.append(str(file_path))

            phase_status.info("阶段 1/4：准备任务")
            st.info(
                "准备开始处理：\n\n"
                f"- 文件数：`{len(paths)}`\n"
                f"- 运行设备：`{device}`\n"
                f"- ASR 模型：`{asr_model}`\n"
                f"- 输出目录：`{normalized_output_dir}`\n"
                f"- 中间 JSON 目录：`{normalized_artifact_dir}`\n"
                f"- 日志文件：`{log_path}`"
            )
            phase_progress.progress(stage_progress(1, phase_count), text="已完成任务准备")

            lrcer = LRCer(
                transcription=TranscriptionConfig(
                    asr_model=asr_model,
                    compute_type=compute_type,
                    device=device,
                    asr_options=get_asr_options(batch_size_s, merge_length_s, use_itn, output_timestamp),
                    vad_options=get_vad_options(max_single_segment_time),
                    preprocess_options=get_preprocess_options(atten_lim_db),
                ),
                translation=TranslationConfig(
                    chatbot_model=translation_model,
                    fee_limit=fee_limit,
                    consumer_thread=consumer_thread,
                    proxy=proxy or None,
                ),
            )

            phase_status.info("阶段 2/4：预处理音频")
            current_file_status.caption("正在执行预处理...")
            audio_paths = lrcer.pre_process(paths, noise_suppress=noise_suppress)
            log_live.code(read_log_tail(log_path) or "日志为空。")
            phase_progress.progress(stage_progress(2, phase_count), text=f"预处理完成，共 {len(audio_paths)} 个文件")

            phase_status.info("阶段 3/4：转写音频")
            transcribed_paths = []
            for idx, audio_path in enumerate(audio_paths, start=1):
                current_file_status.caption(f"正在转写 {idx}/{len(audio_paths)}：`{audio_path.name}`")
                transcribed_paths.append(lrcer._transcribe_single(audio_path, src_lang))
                log_live.code(read_log_tail(log_path) or "日志为空。")
                phase_progress.progress(
                    stage_progress(3, phase_count, idx, max(len(audio_paths), 1)),
                    text=f"转写中 {idx}/{len(audio_paths)}",
                )

            if skip_trans:
                phase_status.info("阶段 4/4：导出字幕")
                for idx, transcribed_path in enumerate(transcribed_paths, start=1):
                    current_file_status.caption(f"正在导出 {idx}/{len(transcribed_paths)}：`{transcribed_path.name}`")
                    lrcer._process_transcribed_file(transcribed_path, target_lang=None, skip_trans=True, bilingual_sub=False)
                    log_live.code(read_log_tail(log_path) or "日志为空。")
                    phase_progress.progress(
                        stage_progress(4, phase_count, idx, max(len(transcribed_paths), 1)),
                        text=f"导出中 {idx}/{len(transcribed_paths)}",
                    )
            else:
                phase_status.info("阶段 4/4：翻译并导出字幕")
                for idx, transcribed_path in enumerate(transcribed_paths, start=1):
                    base_name = lrcer._get_base_name(transcribed_path)
                    subtitle_format = "srt" if lrcer._is_video_transcription(transcribed_path, base_name) else "lrc"

                    current_file_status.caption(
                        f"正在后处理转写 {idx}/{len(transcribed_paths)}：`{transcribed_path.name}`"
                    )
                    transcribed_sub = Subtitle.from_json(transcribed_path)
                    transcribed_opt_sub = lrcer.post_process(transcribed_sub, update_name=True)
                    log_live.code(read_log_tail(log_path) or "日志为空。")
                    phase_progress.progress(
                        stage_progress_within(4, phase_count, (idx - 1 + 0.33) / max(len(transcribed_paths), 1)),
                        text=f"翻译准备中 {idx}/{len(transcribed_paths)}",
                    )

                    cost_estimate = estimate_translation_fee(
                        transcribed_opt_sub.texts,
                        src_lang=transcribed_opt_sub.lang,
                        target_lang=target_lang,
                        chatbot_model=translation_model,
                        title=base_name,
                        glossary=lrcer.glossary,
                    )
                    translation_estimate_status.info(
                        "翻译费用预估：\n\n"
                        f"- 当前文件：`{transcribed_path.name}`\n"
                        f"- 行数 / 分块：`{cost_estimate['line_count']}` / `"
                        f"{cost_estimate['chunk_count']}`\n"
                        f"- 上下文估算：`${cost_estimate['context_fee']:.4f}`\n"
                        f"- 保底总估算：`${cost_estimate['total_floor_fee']:.4f}`\n"
                        f"- 建议预留：`${cost_estimate['total_likely_fee']:.4f}`"
                    )
                    if cost_estimate["total_floor_fee"] > fee_limit:
                        translation_estimate_status.error(
                            "当前费用上限不足，已在翻译前中止。\n\n"
                            f"- 当前上限：`${fee_limit:.2f}`\n"
                            f"- 保底总估算：`${cost_estimate['total_floor_fee']:.4f}`\n"
                            f"- 建议预留：`${cost_estimate['total_likely_fee']:.4f}`\n\n"
                            "请提高“费用上限（USD）”后再重试。"
                        )
                        st.stop()
                    if cost_estimate["total_likely_fee"] > fee_limit:
                        translation_estimate_status.warning(
                            "当前费用上限可能不够。\n\n"
                            f"- 当前上限：`${fee_limit:.2f}`\n"
                            f"- 保底总估算：`${cost_estimate['total_floor_fee']:.4f}`\n"
                            f"- 建议预留：`${cost_estimate['total_likely_fee']:.4f}`"
                        )

                    final_subtitle = wait_for_translation_result(
                        lrcer=lrcer,
                        base_name=base_name,
                        target_lang=target_lang,
                        transcribed_opt_sub=transcribed_opt_sub,
                        log_path=log_path,
                        log_live=log_live,
                        current_file_status=current_file_status,
                        idx=idx,
                        total=max(len(transcribed_paths), 1),
                    )
                    phase_progress.progress(
                        stage_progress_within(4, phase_count, (idx - 1 + 0.66) / max(len(transcribed_paths), 1)),
                        text=f"翻译中 {idx}/{len(transcribed_paths)}",
                    )

                    current_file_status.caption(
                        f"正在导出字幕 {idx}/{len(transcribed_paths)}：`{transcribed_path.name}`"
                    )
                    lrcer._generate_subtitle_files(final_subtitle, base_name, subtitle_format)
                    if bilingual_sub:
                        current_file_status.caption(
                            f"正在导出双语字幕 {idx}/{len(transcribed_paths)}：`{transcribed_path.name}`"
                        )
                        lrcer._handle_bilingual_subtitles(
                            transcribed_path, base_name, transcribed_opt_sub, subtitle_format
                        )
                    log_live.code(read_log_tail(log_path) or "日志为空。")
                    phase_progress.progress(
                        stage_progress(4, phase_count, idx, max(len(transcribed_paths), 1)),
                        text=f"导出完成 {idx}/{len(transcribed_paths)}",
                    )

            results = [str(path) for path in lrcer.transcribed_paths]
            copied_files, result_file_path = persist_result_files(results, normalized_output_dir)
            copied_jsons = persist_intermediate_jsons(transcribed_paths, normalized_artifact_dir, lrcer)
            phase_status.success("处理完成")
            current_file_status.caption("所有阶段已完成。")
            phase_progress.progress(1.0, text="全部完成")
            st.success(f"处理完成，共生成 {len(copied_files)} 个文件。")
            st.info(
                f"本次运行设备：`{device}`\n\n"
                f"输出目录：`{normalized_output_dir}`\n\n"
                f"中间 JSON 目录：`{normalized_artifact_dir}`"
            )

            with open(result_file_path, "rb") as f:
                st.download_button("下载结果", f, file_name=result_file_path.name)

            st.write("生成的文件：")
            for result in copied_files:
                st.code(str(result))
            if copied_jsons:
                st.write("导出的中间 JSON：")
                for result in copied_jsons:
                    st.code(str(result))
            with st.expander("查看日志", expanded=False):
                st.code(read_log_tail(log_path) or "日志为空。")
        except Exception as e:
            st.exception(e)
            with st.expander("查看日志", expanded=True):
                st.code(read_log_tail(log_path) or "日志为空。")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
