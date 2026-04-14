from __future__ import annotations

import json
import re
import subprocess
from functools import lru_cache
from pathlib import Path

import requests
from transformers import AutoTokenizer

from ...models import AppConfig, PROJECT_ROOT
from ..prompts.local_hymt import build_local_batch_translation_prompt, build_local_translation_prompt

OLLAMA_EXE_CANDIDATES = [
    Path(r"C:\Users\Liu\AppData\Local\Programs\Ollama\ollama.exe"),
    Path(r"C:\Program Files\Ollama\ollama.exe"),
]


def detect_ollama_exe() -> str:
    for candidate in OLLAMA_EXE_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return ""


def ensure_ollama_available(config: AppConfig) -> None:
    if not config.local_mt_host.strip():
        raise RuntimeError("本地 HY-MT 模式需要可用的 Ollama 地址。")
    try:
        response = requests.get(f"{config.local_mt_host.rstrip('/')}/api/tags", timeout=10)
        response.raise_for_status()
    except Exception as exc:
        raise RuntimeError(
            "本地 HY-MT 模式需要已启动的 Ollama 服务。请先确认 Ollama 已安装并正在运行。"
        ) from exc


def model_exists_in_ollama(config: AppConfig) -> bool:
    response = requests.get(f"{config.local_mt_host.rstrip('/')}/api/tags", timeout=20)
    response.raise_for_status()
    data = response.json()
    for item in data.get("models", []):
        name = item.get("name", "")
        if name == config.local_mt_model_id or name == f"{config.local_mt_model_id}:latest":
            return True
    return False


def ensure_ollama_model_ready(config: AppConfig) -> None:
    ensure_ollama_available(config)
    if model_exists_in_ollama(config):
        return

    ollama_exe = detect_ollama_exe()
    if not ollama_exe:
        raise RuntimeError("未找到 Ollama 可执行文件，无法自动创建本地模型。")
    if not config.local_mt_gguf_path.strip():
        raise RuntimeError("未配置 GGUF 文件路径，无法自动创建本地模型。")

    gguf_path = Path(config.local_mt_gguf_path).expanduser()
    if not gguf_path.exists():
        raise RuntimeError(f"GGUF 文件不存在：{gguf_path}")

    modelfile = PROJECT_ROOT / "models" / "hy-mt-gguf" / "AutoModelfile"
    modelfile.parent.mkdir(parents=True, exist_ok=True)
    modelfile.write_text(
        "\n".join(
            [
                f"FROM {gguf_path}",
                "PARAMETER num_ctx 4096",
                f"PARAMETER num_predict {config.local_mt_max_new_tokens}",
                f"PARAMETER temperature {config.local_mt_temperature}",
            ]
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [ollama_exe, "create", config.local_mt_model_id, "-f", str(modelfile)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Ollama 本地模型创建失败：{result.stderr or result.stdout}")


@lru_cache(maxsize=2)
def _load_tokenizer(tokenizer_dir: str):
    return AutoTokenizer.from_pretrained(tokenizer_dir, trust_remote_code=True, fix_mistral_regex=True)


def detect_local_hymt_tokenizer_dir() -> str:
    candidate_dirs = [
        PROJECT_ROOT / "HY-MT1.5-1.8B-GPTQ-Int4",
        PROJECT_ROOT / "models" / "hy-mt" / "HY-MT1.5-1.8B-GPTQ-Int4",
    ]
    for candidate in candidate_dirs:
        if (candidate / "tokenizer_config.json").exists():
            return str(candidate)
    return ""


def _wrap_with_chat_template(content: str, tokenizer_dir: str) -> str:
    tokenizer = _load_tokenizer(tokenizer_dir)
    return tokenizer.apply_chat_template(
        [{"role": "user", "content": content}],
        tokenize=False,
        add_generation_prompt=True,
    )


def _normalize_output_line(text: str) -> str:
    line = text.strip()
    line = line.split("<｜hy_Assistant｜>", 1)[0].strip()
    line = re.sub(r"^\d+[\).\s-]*", "", line).strip()
    line = re.sub(r"^[-•]\s*", "", line).strip()
    line = re.sub(r"</?[^>]+>", "", line).strip()
    line = line.replace("<|im_end|>", "").replace("<|im_start|>", "").strip()
    line = re.sub(r"\s+", " ", line).strip()
    return line


def _normalize_output_lines(text: str) -> list[str]:
    lines = [line for line in (_normalize_output_line(line) for line in text.splitlines()) if line]
    return [line for line in lines if not _looks_like_echo_or_instruction(line)]


def _looks_like_echo_or_instruction(line: str) -> bool:
    lowered = line.lower()
    if lowered.startswith("translate the following"):
        return True
    if "without explanation" in lowered:
        return True
    if "output only" in lowered:
        return True
    return False


def _ollama_generate(content: str, config: AppConfig, tokenizer_dir: str) -> str:
    prompt = _wrap_with_chat_template(content, tokenizer_dir)
    payload = {
        "model": config.local_mt_model_id,
        "stream": False,
        "raw": True,
        "prompt": prompt,
        "options": {
            "temperature": float(config.local_mt_temperature),
            "top_k": int(config.local_mt_top_k),
            "top_p": float(config.local_mt_top_p),
            "repeat_penalty": float(config.local_mt_repetition_penalty),
            "num_predict": int(config.local_mt_max_new_tokens),
        },
    }
    response = requests.post(f"{config.local_mt_host.rstrip('/')}/api/generate", json=payload, timeout=600)
    response.raise_for_status()
    return response.json().get("response", "")


def _translate_single_line(text: str, target_lang: str, config: AppConfig, tokenizer_dir: str) -> str:
    translated_text = _ollama_generate(build_local_translation_prompt(text, target_lang), config, tokenizer_dir)
    normalized = _normalize_output_line(translated_text)
    if not normalized:
        raise RuntimeError("HY-MT 返回了空译文。")
    return normalized


def _translate_batch(texts: list[str], target_lang: str, config: AppConfig, tokenizer_dir: str) -> list[str]:
    translated_text = _ollama_generate(build_local_batch_translation_prompt(texts, target_lang), config, tokenizer_dir)
    lines = _normalize_output_lines(translated_text)
    if len(lines) != len(texts):
        raise RuntimeError(f"批量翻译行数不一致：预期 {len(texts)} 行，实际 {len(lines)} 行。")
    return lines


def _chunk_texts(texts: list[str], chunk_size: int) -> list[list[str]]:
    return [texts[index : index + chunk_size] for index in range(0, len(texts), chunk_size)]


def translate_lines_with_hymt(
    texts: list[str],
    src_lang: str | None,
    target_lang: str,
    config: AppConfig,
) -> list[str]:
    _ = src_lang
    ensure_ollama_model_ready(config)

    tokenizer_dir = config.local_mt_tokenizer_dir.strip() or detect_local_hymt_tokenizer_dir()
    if not tokenizer_dir:
        raise RuntimeError("未找到 HY-MT tokenizer 目录，无法构造稳定 prompt。")

    batch_size = max(1, int(getattr(config, "local_mt_batch_size", 1) or 1))
    if batch_size == 1:
        return [_translate_single_line(text, target_lang, config, tokenizer_dir) for text in texts]

    translations: list[str] = []
    for chunk in _chunk_texts(texts, batch_size):
        try:
            translations.extend(_translate_batch(chunk, target_lang, config, tokenizer_dir))
        except Exception:
            translations.extend(_translate_single_line(text, target_lang, config, tokenizer_dir) for text in chunk)
    return translations
