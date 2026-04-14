#  Copyright (C) 2024. Hao Zheng
#  All rights reserved.
# ruff: noqa: E402

from __future__ import annotations

import base64
import concurrent.futures
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from openlrc import LRCer, ModelConfig, ModelProvider, TranscriptionConfig, TranslationConfig, list_chatbot_models
from openlrc.context import TranslateInfo
from openlrc.directory_workflow import (
    CACHE_DIR_NAME,
    STATUS_ASR_DONE,
    STATUS_TRANSLATION_PENDING,
    DirectoryTask,
    materialize_asr_cache,
    scan_directory,
    store_asr_cache,
    store_translated_cache,
    store_translation_estimate_cache,
)
from openlrc.gui_streamlit.utils import detect_relay_models, get_asr_options, get_preprocess_options, get_vad_options
from openlrc.logger import logger
from openlrc.models import Models
from openlrc.prompter import ChunkedTranslatePrompter, ContextReviewPrompter
from openlrc.subtitle import Subtitle
from openlrc.translate import LLMTranslator
from openlrc.utils import get_messages_token_number, get_text_token_number

GUI_CONFIG_PATH = PROJECT_ROOT / ".openlrc_gui_config.json"
CUSTOM_FONT_PATH = PROJECT_ROOT / "yuanshen.ttf"


def load_gui_config() -> dict:
    if not GUI_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(GUI_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_gui_config(config: dict) -> None:
    GUI_CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def choose_folder_dialog(initial_dir: str = "") -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return ""

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    selected = filedialog.askdirectory(initialdir=initial_dir or str(Path.home()))
    root.destroy()
    return selected or ""


def apply_pending_scan_root_dir() -> None:
    pending_dir = st.session_state.pop("scan_root_dir_input_pending", None)
    if pending_dir is not None:
        st.session_state["scan_root_dir_input"] = pending_dir


def inject_custom_font(font_path: Path, font_family: str = "YuanShen") -> None:
    if not font_path.exists():
        return

    font_data = base64.b64encode(font_path.read_bytes()).decode("ascii")
    st.markdown(
        f"""
        <style>
        @font-face {{
            font-family: '{font_family}';
            src: url(data:font/ttf;base64,{font_data}) format('truetype');
            font-weight: normal;
            font-style: normal;
        }}

        :root {{
            --app-font-family: '{font_family}', sans-serif;
        }}

        html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {{
            font-family: var(--app-font-family) !important;
        }}

        [data-testid="stAppViewContainer"] p,
        [data-testid="stAppViewContainer"] label,
        [data-testid="stAppViewContainer"] button,
        [data-testid="stAppViewContainer"] input,
        [data-testid="stAppViewContainer"] textarea,
        [data-testid="stAppViewContainer"] select,
        [data-testid="stAppViewContainer"] li,
        [data-testid="stAppViewContainer"] a,
        [data-testid="stAppViewContainer"] h1,
        [data-testid="stAppViewContainer"] h2,
        [data-testid="stAppViewContainer"] h3,
        [data-testid="stAppViewContainer"] h4,
        [data-testid="stAppViewContainer"] h5,
        [data-testid="stAppViewContainer"] h6,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] button,
        [data-testid="stSidebar"] input,
        [data-testid="stSidebar"] textarea,
        [data-testid="stSidebar"] select,
        [data-testid="stSidebar"] li,
        [data-testid="stSidebar"] a,
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] h4,
        [data-testid="stSidebar"] h5,
        [data-testid="stSidebar"] h6 {{
            font-family: '{font_family}', sans-serif !important;
        }}

        .material-symbols-rounded,
        .material-symbols-outlined,
        .material-icons,
        .material-icons-round,
        .material-icons-outlined,
        [class*="material-symbols"] {{
            font-family: 'Material Symbols Rounded', 'Material Symbols Outlined', 'Material Icons' !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def inject_app_styles() -> None:
    st.markdown(
        """
        <style>
        .fork-hero {
            padding: 0.75rem 0 1rem 0;
            border-bottom: 1px solid rgba(80, 86, 102, 0.12);
            color: #111827;
            margin: 0.1rem 0 1rem 0;
        }

        .fork-hero h3 {
            margin: 0 0 0.25rem 0;
            font-size: 1.05rem;
            font-weight: 700;
        }

        .fork-hero p {
            margin: 0;
            line-height: 1.65;
            color: #6b7280;
            font-size: 0.92rem;
        }

        .summary-grid {
            display: flex;
            flex-direction: column;
            gap: 0;
            margin: 0.25rem 0 1rem 0;
            border: 1px solid rgba(80, 86, 102, 0.14);
            border-radius: 10px;
            overflow: hidden;
            background: rgba(255,255,255,0.64);
        }

        .summary-card {
            display: grid;
            grid-template-columns: 7.5rem minmax(0, 1fr);
            gap: 0.75rem;
            align-items: baseline;
            border-bottom: 1px solid rgba(80, 86, 102, 0.1);
            padding: 0.55rem 0.7rem;
            background: transparent;
        }

        .summary-card:last-child {
            border-bottom: 0;
        }

        .summary-label {
            font-size: 0.76rem;
            letter-spacing: 0.02em;
            text-transform: uppercase;
            color: #6b7280;
            margin-bottom: 0.35rem;
        }

        .summary-value {
            font-size: 0.9rem;
            font-weight: 600;
            color: #111827;
            word-break: break-word;
        }

        .panel-title {
            margin: 0.15rem 0 0.35rem 0;
            font-size: 0.92rem;
            font-weight: 700;
            color: #111827;
        }

        .panel-note {
            margin: -0.15rem 0 0.7rem 0;
            color: #61697a;
            font-size: 0.86rem;
        }

        .status-shell {
            border: 1px solid rgba(80, 86, 102, 0.16);
            border-radius: 10px;
            padding: 1rem 1rem 0.6rem 1rem;
            background: rgba(255,255,255,0.72);
            margin-top: 1rem;
        }

        .status-shell h4 {
            margin: 0 0 0.25rem 0;
            font-size: 1rem;
        }

        .status-shell p {
            margin: 0 0 0.8rem 0;
            color: #677083;
        }

        [data-testid="stSidebarNav"] {
            display: none;
        }

        .side-menu {
            display: flex;
            flex-direction: column;
            gap: 0.2rem;
            margin: 0.35rem 0 0.8rem 0;
        }

        div[data-testid="stSidebar"] .stButton > button {
            width: 100%;
            justify-content: flex-start;
            border-radius: 0;
            border: 1px solid transparent;
            background: transparent;
            color: #374151;
            font-weight: 500;
            margin: 0.05rem 0;
            padding: 0.45rem 0.55rem;
            border-left: 2px solid transparent;
        }

        div[data-testid="stSidebar"] .stButton > button:hover {
            border-left-color: rgba(80, 86, 102, 0.34);
            background: rgba(80, 86, 102, 0.06);
        }

        div[data-testid="stSidebar"] .stButton > button[data-baseweb="button"][aria-label^="active-config-"] {
            border-left-color: #5e6ad2;
            background: rgba(94, 106, 210, 0.08);
            color: #111827;
        }

        div[data-testid="stSidebar"] .stButton > button:focus {
            box-shadow: none;
        }

        [data-testid="stFileUploaderDropzone"] {
            border: 1px dashed rgba(80, 86, 102, 0.22) !important;
            border-radius: 12px !important;
            background: rgba(255,255,255,0.58) !important;
            padding: 0.75rem !important;
        }

        [data-testid="stFileUploaderDropzone"] button {
            border-radius: 8px !important;
            border: 1px solid rgba(80, 86, 102, 0.18) !important;
            background: rgba(255,255,255,0.7) !important;
            color: #111827 !important;
        }

        @media (max-width: 900px) {
            .summary-grid {
                grid-template-columns: 1fr;
            }

        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_info_cards(items: list[tuple[str, str]]) -> None:
    cards_html = "".join(
        f'<div class="summary-card"><div class="summary-label">{label}</div><div class="summary-value">{value}</div></div>'
        for label, value in items
    )
    st.markdown(f'<div class="summary-grid">{cards_html}</div>', unsafe_allow_html=True)


def ui_mode_label(skip_trans: bool, bilingual_sub: bool) -> str:
    if skip_trans:
        return "仅转写"
    if bilingual_sub:
        return "完整翻译 + 双语字幕"
    return "完整翻译"


CONFIG_PANEL_MAP = {
    "asr": "ASR",
    "translation": "翻译",
    "performance": "费用与性能",
    "advanced": "输出与高级",
}


def get_active_config_panel() -> str:
    return st.session_state.setdefault("active_config_panel", "ASR")


def render_config_menu(active_panel: str) -> None:
    items = [
        ("ASR", "ASR"),
        ("翻译", "翻译"),
        ("费用与性能", "费用与性能"),
        ("输出与高级", "输出与高级"),
    ]
    for panel_key, title in items:
        button_label = title
        button_help = f"active-config-{panel_key}" if panel_key == active_panel else None
        if st.sidebar.button(
            button_label,
            key=f"config_menu_{panel_key}",
            use_container_width=True,
            help=button_help,
        ):
            st.session_state["active_config_panel"] = panel_key
            st.rerun()


st.set_page_config(page_title="OpenLRC", page_icon="Audio", layout="wide")
inject_custom_font(CUSTOM_FONT_PATH)
inject_app_styles()

st.title("OpenLRC")
st.caption("使用 SenseVoice 和大语言模型进行音频转写与字幕翻译。")
st.markdown("[zh-plus/openlrc](https://github.com/zh-plus/openlrc)")

st.sidebar.header("配置")


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


def discover_audio_files(root_dir: Path) -> list[Path]:
    return [task.audio_path for task in scan_directory(root_dir)]


def task_status_label(task: DirectoryTask) -> str:
    if task.cache_valid:
        return task.status
    return "需转写"


def cache_summary(tasks: list[DirectoryTask]) -> str:
    cached_count = sum(1 for task in tasks if task.cache_valid)
    pending_count = max(len(tasks) - cached_count, 0)
    return f"ASR 可复用 {cached_count} / 需转写 {pending_count}"


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


def render_translation_confirmation(state: dict) -> tuple[bool, list[str]]:
    entries = state.get("entries", [])
    options = [entry["relative_path"] for entry in entries]
    selection_key = f"translation_selection_{state.get('id', 'default')}"
    st.session_state.setdefault(selection_key, options)

    st.markdown('<div class="panel-title">步骤 3 · 翻译确认</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="panel-note">ASR 已完成。确认预算和文件范围后，才会调用 LLM 翻译。</div>',
        unsafe_allow_html=True,
    )
    render_info_cards(
        [
            ("待确认文件", str(len(entries))),
            ("保底估算", f"${float(state.get('total_floor_fee', 0.0)):.4f}"),
            ("建议预留", f"${float(state.get('total_likely_fee', 0.0)):.4f}"),
            ("目标语言", str(state.get("target_lang", ""))),
        ]
    )

    select_col, clear_col = st.columns(2, gap="small")
    with select_col:
        if st.button("全选待翻译文件", use_container_width=True):
            st.session_state[selection_key] = options
            st.rerun()
    with clear_col:
        if st.button("全不选", use_container_width=True):
            st.session_state[selection_key] = []
            st.rerun()

    selected = st.multiselect(
        "选择本次要翻译的文件",
        options=options,
        key=selection_key,
        help="未选择的文件会保留 ASR 缓存，之后可以继续翻译。",
    )
    with st.expander("查看文件级费用估算", expanded=False):
        for entry in entries:
            estimate = entry["estimate"]
            st.code(
                f"{entry['relative_path']} | 行数 {int(estimate['line_count'])} | "
                f"分块 {int(estimate['chunk_count'])} | "
                f"保底 ${float(estimate['total_floor_fee']):.4f} | "
                f"建议 ${float(estimate['total_likely_fee']):.4f}"
            )

    confirmed = st.button("确认翻译所选文件", type="primary", use_container_width=True, disabled=not selected)
    return confirmed, list(selected)


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


def ensure_file_logger(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)

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

default_device = detect_default_device()
device_options = ["cuda", "cpu"] if default_device == "cuda" else ["cpu", "cuda"]
available_chatbot_models = sorted(set(list_chatbot_models()))
default_chatbot_model = "gpt-4.1-nano" if "gpt-4.1-nano" in available_chatbot_models else available_chatbot_models[0]

asr_model_options = ["small", "large", "iic/SenseVoiceSmall", "iic/SenseVoiceLarge"]
compute_type_options = ["int8", "int8_float16", "int16", "float16", "float32"]
relay_provider_options = ["OpenAI 兼容", "Anthropic 兼容"]


def saved_or_state(key: str, default):
    return st.session_state.get(key, saved_gui_config.get(key, default))


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
    digest = hashlib.sha256(f"{provider_label}|{base_url.strip()}|{api_key.strip()}".encode()).hexdigest()[:12]
    return f"{provider_label}|{base_url.strip()}|{digest}"


st.markdown(
    """
    <div class="fork-hero">
        <h3>本地字幕工作流</h3>
        <p>先选择根文件夹，再确认语言、模式与费用上限。左侧配置菜单一次只展开一个大类，减少页面噪音。</p>
    </div>
    """,
    unsafe_allow_html=True,
)

main_area = st.container()

with st.sidebar:
    active_config_panel = get_active_config_panel()
    render_config_menu(active_config_panel)

    if active_config_panel == "ASR":
        st.markdown("#### ASR")
        asr_model = st.selectbox(
            "SenseVoice 模型",
            asr_model_options,
            index=asr_model_options.index(saved_or_state("asr_model", "small"))
            if saved_or_state("asr_model", "small") in asr_model_options
            else 0,
            key="asr_model",
            help="默认建议 small。large 更重，可能需要更多显存或内存。",
        )
    else:
        asr_model = saved_or_state("asr_model", "small")

    if active_config_panel == "翻译":
        st.markdown("#### 翻译")
        endpoint_mode_default = "中转平台" if saved_gui_config.get("use_custom_translation_endpoint", False) else "官方 API"
        endpoint_mode = st.radio(
            "翻译接口",
            ["中转平台", "官方 API"],
            index=["中转平台", "官方 API"].index(st.session_state.get("endpoint_mode", endpoint_mode_default)),
            key="endpoint_mode",
        )
        use_custom_translation_endpoint = endpoint_mode == "中转平台"

        if use_custom_translation_endpoint:
            relay_provider = st.selectbox(
                "中转提供商类型",
                relay_provider_options,
                index=relay_provider_options.index(saved_or_state("relay_provider", "OpenAI 兼容"))
                if saved_or_state("relay_provider", "OpenAI 兼容") in relay_provider_options
                else 0,
                key="relay_provider",
            )
            relay_base_url = st.text_input(
                "Base URL",
                value=saved_or_state(
                    "relay_base_url",
                    "https://openrouter.ai/api/v1" if relay_provider == "OpenAI 兼容" else "",
                ),
                key="relay_base_url",
            )
            remember_relay_api_key = st.checkbox(
                "记住中转 API Key",
                value=bool(saved_or_state("remember_relay_api_key", False)),
                key="remember_relay_api_key",
            )
            relay_api_key = st.text_input(
                "中转 API Key",
                value=saved_or_state("relay_api_key", "") if remember_relay_api_key else "",
                type="password",
                key="relay_api_key",
            )
        else:
            relay_provider = saved_or_state("relay_provider", "OpenAI 兼容")
            relay_base_url = saved_or_state("relay_base_url", "")
            remember_relay_api_key = bool(saved_or_state("remember_relay_api_key", False))
            relay_api_key = saved_or_state("relay_api_key", "") if remember_relay_api_key else ""

        if not use_custom_translation_endpoint:
            openai_api_key = st.text_input("OpenAI API Key", value=os.environ.get("OPENAI_API_KEY", ""), key="openai_api")
            anthropic_api_key = st.text_input(
                "Anthropic API Key", value=os.environ.get("ANTHROPIC_API_KEY", ""), key="anthropic_api"
            )
            google_api_key = st.text_input("Google API Key", value=os.environ.get("GOOGLE_API_KEY", ""), key="google_api")
            openrouter_api_key = st.text_input(
                "OpenRouter API Key", value=os.environ.get("OPENROUTER_API_KEY", ""), key="openrouter_api"
            )
            chatbot_model = st.selectbox(
                "翻译模型",
                available_chatbot_models,
                index=available_chatbot_models.index(saved_or_state("chatbot_model", default_chatbot_model))
                if saved_or_state("chatbot_model", default_chatbot_model) in available_chatbot_models
                else available_chatbot_models.index(default_chatbot_model),
                key="chatbot_model",
            )
            relay_model_name = saved_or_state("relay_model_name", "")
            resolved_relay_api_key = ""
        else:
            openai_api_key = st.session_state.get("openai_api", os.environ.get("OPENAI_API_KEY", ""))
            anthropic_api_key = st.session_state.get("anthropic_api", os.environ.get("ANTHROPIC_API_KEY", ""))
            google_api_key = st.session_state.get("google_api", os.environ.get("GOOGLE_API_KEY", ""))
            openrouter_api_key = st.session_state.get("openrouter_api", os.environ.get("OPENROUTER_API_KEY", ""))
            resolved_relay_api_key = resolve_relay_api_key(relay_provider, relay_base_url, relay_api_key)
            current_detect_key = relay_detect_state_key(relay_provider, relay_base_url, resolved_relay_api_key)
            if st.button("探测模型", use_container_width=True):
                if not relay_base_url.strip():
                    st.error("请先填写 Base URL。")
                elif not resolved_relay_api_key:
                    st.error("请先填写中转 API Key，或在 API key 环境变量中提供可用凭证。")
                else:
                    try:
                        detected_models = detect_relay_models(
                            provider_kind="openai" if relay_provider == "OpenAI 兼容" else "anthropic",
                            base_url=relay_base_url,
                            api_key=resolved_relay_api_key,
                            proxy=saved_or_state("proxy", "") or None,
                        )
                        st.session_state["relay_detect_key"] = current_detect_key
                        st.session_state["relay_detected_models"] = detected_models
                        st.session_state["relay_detect_error"] = ""
                        st.success(f"探测到 {len(detected_models)} 个模型。")
                    except Exception as exc:
                        st.session_state["relay_detect_key"] = current_detect_key
                        st.session_state["relay_detected_models"] = []
                        st.session_state["relay_detect_error"] = str(exc)
                        st.error(str(exc))

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
                selected_relay_model = st.selectbox("中转模型名", detected_models, index=0, key="relay_detected_model")
                relay_manual_override = st.text_input("手动覆盖模型名（可选）", value="", key="relay_manual_override")
                relay_model_name = relay_manual_override.strip() or selected_relay_model
            else:
                relay_model_name = st.text_input(
                    "中转模型名",
                    value=saved_or_state("relay_model_name", manual_default_model),
                    key="relay_model_name",
                )
                if detect_error:
                    st.caption("未能自动探测模型，当前使用手动输入。")
            chatbot_model = None
    else:
        use_custom_translation_endpoint = bool(
            st.session_state.get(
                "use_custom_translation_endpoint",
                st.session_state.get("endpoint_mode", "中转平台" if saved_gui_config.get("use_custom_translation_endpoint", False) else "官方 API")
                == "中转平台",
            )
        )
        openai_api_key = st.session_state.get("openai_api", os.environ.get("OPENAI_API_KEY", ""))
        anthropic_api_key = st.session_state.get("anthropic_api", os.environ.get("ANTHROPIC_API_KEY", ""))
        google_api_key = st.session_state.get("google_api", os.environ.get("GOOGLE_API_KEY", ""))
        openrouter_api_key = st.session_state.get("openrouter_api", os.environ.get("OPENROUTER_API_KEY", ""))
        relay_provider = saved_or_state("relay_provider", "OpenAI 兼容")
        relay_base_url = saved_or_state("relay_base_url", "")
        remember_relay_api_key = bool(saved_or_state("remember_relay_api_key", False))
        relay_api_key = saved_or_state("relay_api_key", "") if remember_relay_api_key else ""
        resolved_relay_api_key = resolve_relay_api_key(relay_provider, relay_base_url, relay_api_key)
        relay_model_name = saved_or_state("relay_model_name", "")
        chatbot_model = None if use_custom_translation_endpoint else saved_or_state("chatbot_model", default_chatbot_model)

    if active_config_panel == "费用与性能":
        st.markdown("#### 费用与性能")
        fee_limit = st.slider(
            "费用上限（USD）",
            min_value=0.0,
            max_value=10.0,
            value=float(saved_or_state("fee_limit", 0.5)),
            step=0.01,
            key="fee_limit",
        )
        consumer_thread = st.slider("翻译线程数", min_value=1, max_value=12, value=int(saved_or_state("consumer_thread", 4)), step=1, key="consumer_thread")
        if fee_limit <= 0.1:
            st.warning("当前费用上限较低。几分钟以上的音频可能会因为超出上限而中止翻译。")
    else:
        fee_limit = float(saved_or_state("fee_limit", 0.5))
        consumer_thread = int(saved_or_state("consumer_thread", 4))

    if active_config_panel == "输出与高级":
        st.markdown("#### 输出与高级")
        st.caption("输出规则：生成的 LRC 会直接保存到各自源音频所在目录。")
        device = st.selectbox(
            "运行设备",
            device_options,
            index=device_options.index(saved_or_state("device", device_options[0]))
            if saved_or_state("device", device_options[0]) in device_options
            else 0,
            key="device",
        )
        compute_type = st.selectbox(
            "计算精度",
            compute_type_options,
            index=compute_type_options.index(saved_or_state("compute_type", "float16"))
            if saved_or_state("compute_type", "float16") in compute_type_options
            else 3,
            key="compute_type",
        )
        proxy = st.text_input("代理", value=saved_or_state("proxy", ""), key="proxy", help="例如 http://127.0.0.1:7890")
        batch_size_s = st.number_input("批处理时长（秒）", min_value=1, max_value=300, value=int(saved_or_state("batch_size_s", 60)), key="batch_size_s")
        merge_length_s = st.number_input("VAD 合并时长（秒）", min_value=1, max_value=120, value=int(saved_or_state("merge_length_s", 15)), key="merge_length_s")
        use_itn = st.checkbox("启用 ITN", value=bool(saved_or_state("use_itn", True)), key="use_itn")
        output_timestamp = st.checkbox("输出时间戳", value=bool(saved_or_state("output_timestamp", True)), key="output_timestamp")
        max_single_segment_time = st.number_input(
            "单段最大时长（毫秒）",
            min_value=1000,
            max_value=120000,
            value=int(saved_or_state("max_single_segment_time", 30000)),
            step=1000,
            key="max_single_segment_time",
        )
        atten_lim_db = st.number_input("响度限制（dB）", value=int(saved_or_state("atten_lim_db", 15)), min_value=0, key="atten_lim_db")
    else:
        device = saved_or_state("device", device_options[0])
        compute_type = saved_or_state("compute_type", "float16")
        proxy = saved_or_state("proxy", "")
        batch_size_s = int(saved_or_state("batch_size_s", 60))
        merge_length_s = int(saved_or_state("merge_length_s", 15))
        use_itn = bool(saved_or_state("use_itn", True))
        output_timestamp = bool(saved_or_state("output_timestamp", True))
        max_single_segment_time = int(saved_or_state("max_single_segment_time", 30000))
        atten_lim_db = int(saved_or_state("atten_lim_db", 15))

save_payload = {
    "asr_model": asr_model,
    "device": device,
    "compute_type": compute_type,
    "proxy": proxy,
    "scan_root_dir": st.session_state.get(
        "scan_root_dir_input",
        st.session_state.get("scan_root_dir", saved_gui_config.get("scan_root_dir", "")),
    ),
    "use_custom_translation_endpoint": use_custom_translation_endpoint,
    "relay_provider": relay_provider,
    "relay_base_url": relay_base_url,
    "relay_model_name": relay_model_name,
    "remember_relay_api_key": remember_relay_api_key,
    "relay_api_key": relay_api_key if remember_relay_api_key else "",
    "fee_limit": fee_limit,
    "consumer_thread": consumer_thread,
    "chatbot_model": chatbot_model if isinstance(chatbot_model, str) else None,
    "batch_size_s": batch_size_s,
    "merge_length_s": merge_length_s,
    "use_itn": use_itn,
    "output_timestamp": output_timestamp,
    "max_single_segment_time": max_single_segment_time,
    "atten_lim_db": atten_lim_db,
}
if save_payload != saved_gui_config:
    save_gui_config(save_payload)

if has_nvidia_gpu() and default_device != "cuda":
    st.warning("检测到 NVIDIA 显卡，但当前 Python/PyTorch 不是 CUDA 版；现在会按 CPU 跑。")

confirm_translation_requested = False
confirmed_translation_selection: list[str] = []

with main_area:
    st.markdown('<div class="panel-title">步骤 1 · 上传与任务参数</div>', unsafe_allow_html=True)
    st.markdown('<div class="panel-note">选择一个根文件夹，系统会递归扫描其中所有音频文件，并把生成的 LRC 直接保存回源文件所在目录。</div>', unsafe_allow_html=True)
    apply_pending_scan_root_dir()
    if "scan_root_dir_input" not in st.session_state:
        st.session_state["scan_root_dir_input"] = st.session_state.get(
            "scan_root_dir",
            saved_gui_config.get("scan_root_dir", ""),
        )
    initial_scan_dir = st.session_state["scan_root_dir_input"]
    folder_col, browse_col = st.columns([1, 0.18], gap="small")
    with folder_col:
        scan_root_dir = st.text_input(
            "根文件夹",
            key="scan_root_dir_input",
            placeholder="选择包含音频文件的根目录",
        )
    with browse_col:
        st.markdown("<div style='height: 1.9rem;'></div>", unsafe_allow_html=True)
        if st.button("选择", use_container_width=True):
            selected_dir = choose_folder_dialog(initial_scan_dir)
            if selected_dir:
                st.session_state["scan_root_dir_input_pending"] = selected_dir
                st.rerun()

    selected_root_path = Path(scan_root_dir).expanduser() if scan_root_dir.strip() else None
    directory_tasks: list[DirectoryTask] = []
    discovered_audio_files: list[Path] = []
    relative_audio_paths: list[str] = []
    if selected_root_path:
        if selected_root_path.exists() and selected_root_path.is_dir():
            directory_tasks = scan_directory(selected_root_path)
            discovered_audio_files = [task.audio_path for task in directory_tasks]
            relative_audio_paths = [str(task.relative_path) for task in directory_tasks]
            st.caption(f"共发现 {len(directory_tasks)} 个音频文件。{cache_summary(directory_tasks)}。")
            if directory_tasks:
                with st.expander("查看扫描结果", expanded=False):
                    for task in directory_tasks:
                        st.code(
                            f"{task.relative_path} | {task_status_label(task)} | "
                            f"{CACHE_DIR_NAME}/{task.relative_path.with_suffix('')}"
                        )
        else:
            st.warning("当前根文件夹不存在，或不是一个有效目录。")
    else:
        st.caption("请选择一个根文件夹，系统会递归处理其中所有音频文件。")

    lang_col, target_col = st.columns([1, 1], gap="medium")
    with lang_col:
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
    with target_col:
        target_lang = st.text_input("目标语言", value="zh-cn", help="填写目标翻译语言代码。")

    mode_col1, mode_col2, mode_col3 = st.columns(3, gap="small")
    with mode_col1:
        skip_trans = st.checkbox("仅转写")
    with mode_col2:
        noise_suppress = st.checkbox("降噪")
    with mode_col3:
        bilingual_sub = st.checkbox("双语字幕")

    st.markdown('<div class="panel-title">步骤 2 · 任务摘要</div>', unsafe_allow_html=True)
    st.markdown('<div class="panel-note">开始前先检查当前模式、模型、设备、费用和根目录；最终 LRC 会保存回各自源音频所在目录。</div>', unsafe_allow_html=True)
    translation_summary = (
        f"{relay_provider} / {relay_model_name.strip() or '未填写'}"
        if use_custom_translation_endpoint
        else str(chatbot_model or "未设置")
    )
    render_info_cards(
        [
            ("文件数", str(len(discovered_audio_files))),
            ("任务模式", ui_mode_label(skip_trans, bilingual_sub)),
            ("ASR 模型", asr_model),
            ("运行设备", device),
            ("翻译配置", "关闭" if skip_trans else translation_summary),
            ("费用上限", f"${fee_limit:.2f}"),
            ("根目录", str(selected_root_path) if selected_root_path else "未选择"),
            ("高级参数", f"线程 {consumer_thread} / ITN {'开' if use_itn else '关'}"),
        ]
    )
    submitted = st.button("开始处理", type="primary", use_container_width=True)

    pending_confirmation = st.session_state.get("translation_confirmation")
    if pending_confirmation and pending_confirmation.get("entries"):
        confirm_translation_requested, confirmed_translation_selection = render_translation_confirmation(
            pending_confirmation
        )
        if confirm_translation_requested:
            st.session_state["confirmed_translation_selection"] = confirmed_translation_selection

if submitted or confirm_translation_requested:
    st.info("已收到处理请求，正在检查参数...")
    active_confirmation = st.session_state.get("translation_confirmation") if confirm_translation_requested else None
    has_files = bool(active_confirmation.get("entries")) if active_confirmation else bool(discovered_audio_files)
    has_any_direct_api_key = any([openai_api_key, anthropic_api_key, google_api_key, openrouter_api_key])
    has_translation_credentials = has_any_direct_api_key or (
        use_custom_translation_endpoint and bool(resolved_relay_api_key)
    )

    translation_required = confirm_translation_requested or not skip_trans
    if not has_files:
        st.error("请先选择一个有效根文件夹，并确保其中至少包含一个可处理的音频文件。")
    elif translation_required and not has_translation_credentials:
        st.error("当前启用了翻译，但没有设置任何 API Key。请先在侧边栏填写，或勾选“仅转写”。")
        st.stop()
    elif translation_required and use_custom_translation_endpoint and (not relay_model_name.strip() or not relay_base_url.strip()):
        st.error("启用了中转 / 自定义接口时，必须填写模型名和 Base URL。")
        st.stop()
    else:
        src_lang = None if src_lang == "自动检测" else src_lang
        root_dir = Path(active_confirmation["root_dir"]).resolve() if active_confirmation else selected_root_path.resolve()
        target_lang = active_confirmation["target_lang"] if active_confirmation else target_lang
        run_skip_trans = False if confirm_translation_requested else skip_trans
        normalized_artifact_dir = root_dir / CACHE_DIR_NAME
        log_path = root_dir / "openlrc_run.log"
        st.session_state["last_log_path"] = str(log_path)
        directory_tasks = scan_directory(root_dir)
        paths = [str(task.audio_path) for task in directory_tasks]
        phase_count = 4
        status_container = st.container()
        with status_container:
            st.markdown(
                """
                <div class="status-shell">
                    <h4>运行状态</h4>
                    <p>处理开始后，这里会固定显示阶段进度、当前文件、费用预估和实时日志。</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            phase_progress = st.progress(0, text="等待开始...")
            phase_status = st.empty()
            current_file_status = st.empty()
            translation_estimate_status = st.empty()
            log_live = st.empty()

        try:
            ensure_file_logger(log_path)
            apply_runtime_api_keys(openai_api_key, anthropic_api_key, google_api_key, openrouter_api_key)
            translation_model = chatbot_model
            if not run_skip_trans and use_custom_translation_endpoint:
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
            elif run_skip_trans:
                st.info("当前为仅转写模式，不会调用翻译 API。")
            else:
                st.info(f"使用内置翻译模型：`{translation_model}`")

            phase_status.info("阶段 1/4：准备任务")
            st.info(
                "准备开始处理：\n\n"
                f"- 文件数：`{len(paths)}`\n"
                f"- 根目录：`{root_dir}`\n"
                f"- 运行设备：`{device}`\n"
                f"- ASR 模型：`{asr_model}`\n"
                f"- 输出方式：`每个 LRC 保存回源音频所在目录`\n"
                f"- ASR 缓存目录：`{normalized_artifact_dir}`\n"
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

            phase_status.info("阶段 2/4：ASR 缓存与转写")
            asr_outputs: list[tuple[DirectoryTask, Path, Path]] = []
            asr_cache_status = STATUS_ASR_DONE if run_skip_trans else STATUS_TRANSLATION_PENDING
            for idx, task in enumerate(directory_tasks, start=1):
                if task.cache_valid:
                    current_file_status.caption(f"复用 ASR 缓存 {idx}/{len(directory_tasks)}：`{task.relative_path}`")
                    transcribed_path, optimized_path = materialize_asr_cache(task)
                    logger.info(f"Reused ASR cache for {task.relative_path}: {task.cache_dir}")
                else:
                    current_file_status.caption(f"正在转写 {idx}/{len(directory_tasks)}：`{task.relative_path}`")
                    transcribed_path, optimized_path = run_asr_for_task(
                        lrcer,
                        task,
                        src_lang,
                        noise_suppress,
                        target_lang if not run_skip_trans else None,
                        asr_cache_status,
                    )
                asr_outputs.append((task, transcribed_path, optimized_path))
                log_live.code(read_log_tail(log_path) or "日志为空。")
                phase_progress.progress(
                    stage_progress(2, phase_count, idx, max(len(directory_tasks), 1)),
                    text=f"ASR 阶段 {idx}/{len(directory_tasks)}",
                )

            if run_skip_trans:
                phase_status.info("阶段 3/4：仅转写导出")
                for idx, (task, transcribed_path, optimized_path) in enumerate(asr_outputs, start=1):
                    base_name = task.audio_path.stem
                    current_file_status.caption(f"正在导出 {idx}/{len(asr_outputs)}：`{task.relative_path}`")
                    transcribed_opt_sub = Subtitle.from_json(optimized_path)
                    final_subtitle = lrcer._build_final_subtitle(base_name, None, transcribed_opt_sub, True)
                    lrcer._generate_subtitle_files(final_subtitle, base_name, "lrc")
                    store_asr_cache(task, transcribed_path, optimized_path, target_lang=None, status=STATUS_ASR_DONE)
                    log_live.code(read_log_tail(log_path) or "日志为空。")
                    phase_progress.progress(
                        stage_progress(3, phase_count, idx, max(len(asr_outputs), 1)),
                        text=f"导出中 {idx}/{len(asr_outputs)}",
                    )
                phase_status.info("阶段 4/4：完成")
                phase_progress.progress(stage_progress(4, phase_count), text="导出完成")
            else:
                if not confirm_translation_requested:
                    phase_status.info("阶段 3/4：费用估算")
                    confirmation_entries = []
                    for idx, (task, _transcribed_path, optimized_path) in enumerate(asr_outputs, start=1):
                        base_name = task.audio_path.stem
                        transcribed_opt_sub = Subtitle.from_json(optimized_path)
                        current_file_status.caption(f"正在估算 {idx}/{len(asr_outputs)}：`{task.relative_path}`")

                        cost_estimate = estimate_translation_fee(
                            transcribed_opt_sub.texts,
                            src_lang=transcribed_opt_sub.lang,
                            target_lang=target_lang,
                            chatbot_model=translation_model,
                            title=base_name,
                            glossary=lrcer.glossary,
                        )
                        store_translation_estimate_cache(task, cost_estimate)
                        confirmation_entries.append(
                            {
                                "relative_path": str(task.relative_path),
                                "cache_dir": str(task.cache_dir),
                                "estimate": cost_estimate,
                            }
                        )
                        translation_estimate_status.info(
                            "翻译费用预估：\n\n"
                            f"- 当前文件：`{task.relative_path}`\n"
                            f"- 行数 / 分块：`{cost_estimate['line_count']}` / `"
                            f"{cost_estimate['chunk_count']}`\n"
                            f"- 保底总估算：`${cost_estimate['total_floor_fee']:.4f}`\n"
                            f"- 建议预留：`${cost_estimate['total_likely_fee']:.4f}`"
                        )
                        log_live.code(read_log_tail(log_path) or "日志为空。")
                        phase_progress.progress(
                            stage_progress(3, phase_count, idx, max(len(asr_outputs), 1)),
                            text=f"费用估算 {idx}/{len(asr_outputs)}",
                        )

                    confirmation_state = build_translation_confirmation_state(
                        root_dir, target_lang, confirmation_entries
                    )
                    st.session_state["translation_confirmation"] = confirmation_state
                    phase_status.success("ASR 与费用估算完成，等待翻译确认")
                    current_file_status.caption("请选择要翻译的文件后再确认。")
                    phase_progress.progress(stage_progress(3, phase_count), text="等待翻译确认")
                    st.info(
                        "已完成 ASR 缓存和费用估算，本次不会自动调用 LLM。\n\n"
                        f"- 待确认文件：`{len(confirmation_entries)}`\n"
                        f"- 保底总估算：`${confirmation_state['total_floor_fee']:.4f}`\n"
                        f"- 建议预留：`${confirmation_state['total_likely_fee']:.4f}`"
                    )
                    st.rerun()

                selected_relative_paths = set(st.session_state.get("confirmed_translation_selection", []))
                selected_outputs = [
                    output for output in asr_outputs if str(output[0].relative_path) in selected_relative_paths
                ]
                estimate_by_relative = {
                    entry["relative_path"]: entry["estimate"] for entry in active_confirmation.get("entries", [])
                }
                selected_floor_fee = sum(
                    float(estimate_by_relative[str(task.relative_path)]["total_floor_fee"])
                    for task, _transcribed_path, _optimized_path in selected_outputs
                    if str(task.relative_path) in estimate_by_relative
                )
                selected_likely_fee = sum(
                    float(estimate_by_relative[str(task.relative_path)]["total_likely_fee"])
                    for task, _transcribed_path, _optimized_path in selected_outputs
                    if str(task.relative_path) in estimate_by_relative
                )
                translation_estimate_status.info(
                    "已确认本次翻译范围：\n\n"
                    f"- 文件数：`{len(selected_outputs)}`\n"
                    f"- 保底总估算：`${selected_floor_fee:.4f}`\n"
                    f"- 建议预留：`${selected_likely_fee:.4f}`\n"
                    f"- 当前费用上限：`${fee_limit:.2f}`"
                )
                if selected_floor_fee > fee_limit:
                    translation_estimate_status.error(
                        "本次勾选文件的保底估算超过费用上限，已中止翻译。\n\n"
                        f"- 当前上限：`${fee_limit:.2f}`\n"
                        f"- 保底总估算：`${selected_floor_fee:.4f}`\n"
                        f"- 建议预留：`${selected_likely_fee:.4f}`"
                    )
                    st.stop()

                phase_status.info("阶段 3/4：翻译所选文件")
                for idx, (task, transcribed_path, optimized_path) in enumerate(selected_outputs, start=1):
                    base_name = task.audio_path.stem
                    transcribed_opt_sub = Subtitle.from_json(optimized_path)
                    current_file_status.caption(f"正在翻译 {idx}/{len(selected_outputs)}：`{task.relative_path}`")

                    final_subtitle = wait_for_translation_result(
                        lrcer=lrcer,
                        base_name=base_name,
                        target_lang=target_lang,
                        transcribed_opt_sub=transcribed_opt_sub,
                        log_path=log_path,
                        log_live=log_live,
                        current_file_status=current_file_status,
                        idx=idx,
                        total=max(len(selected_outputs), 1),
                    )
                    log_live.code(read_log_tail(log_path) or "日志为空。")
                    phase_progress.progress(
                        stage_progress(3, phase_count, idx, max(len(selected_outputs), 1)),
                        text=f"翻译中 {idx}/{len(selected_outputs)}",
                    )

                    phase_status.info("阶段 4/4：导出字幕")
                    current_file_status.caption(f"正在导出字幕 {idx}/{len(selected_outputs)}：`{task.relative_path}`")
                    lrcer._generate_subtitle_files(final_subtitle, base_name, "lrc")
                    if bilingual_sub:
                        current_file_status.caption(f"正在导出双语字幕 {idx}/{len(selected_outputs)}：`{task.relative_path}`")
                        lrcer._handle_bilingual_subtitles(transcribed_path, base_name, transcribed_opt_sub, "lrc")
                    store_translated_cache(task, final_subtitle.filename, target_lang=target_lang)
                    log_live.code(read_log_tail(log_path) or "日志为空。")
                    phase_progress.progress(
                        stage_progress(4, phase_count, idx, max(len(selected_outputs), 1)),
                        text=f"导出完成 {idx}/{len(selected_outputs)}",
                    )

                remaining_entries = [
                    entry
                    for entry in active_confirmation.get("entries", [])
                    if entry["relative_path"] not in selected_relative_paths
                ]
                if remaining_entries:
                    st.session_state["translation_confirmation"] = build_translation_confirmation_state(
                        root_dir, target_lang, remaining_entries
                    )
                else:
                    st.session_state.pop("translation_confirmation", None)
                st.session_state.pop("confirmed_translation_selection", None)

            generated_files = [Path(path) for path in lrcer.transcribed_paths]
            phase_status.success("处理完成")
            current_file_status.caption("所有阶段已完成。")
            phase_progress.progress(1.0, text="全部完成")
            st.success(f"处理完成，共生成 {len(generated_files)} 个文件。")
            st.info(
                f"本次运行设备：`{device}`\n\n"
                f"根目录：`{root_dir}`\n\n"
                f"输出方式：`LRC 与源音频同目录保存`\n\n"
                f"ASR 缓存目录：`{normalized_artifact_dir}`"
            )

            st.write("生成的文件：")
            for result in generated_files:
                st.code(str(result))
            with st.expander("查看日志", expanded=False):
                st.code(read_log_tail(log_path) or "日志为空。")
        except Exception as e:
            st.exception(e)
            with st.expander("查看日志", expanded=True):
                st.code(read_log_tail(log_path) or "日志为空。")
