from __future__ import annotations

import argparse
from pathlib import Path

from openlrc import LRCer, TranscriptionConfig, TranslationConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run OpenLRC locally with SenseVoice as the ASR backend."
    )
    parser.add_argument("paths", nargs="+", help="Audio or video files to process.")
    parser.add_argument("--src-lang", default=None, help="Source language. Default: auto detect.")
    parser.add_argument("--target-lang", default="zh-cn", help="Target subtitle language. Default: zh-cn.")
    parser.add_argument(
        "--asr-model",
        default="iic/SenseVoiceSmall",
        help="SenseVoice model name or alias. Use small, large, iic/SenseVoiceSmall, or iic/SenseVoiceLarge.",
    )
    parser.add_argument("--device", default="cuda", help="Inference device. Default: cuda.")
    parser.add_argument(
        "--skip-trans",
        action="store_true",
        help="Only transcribe. Do not call an LLM for translation.",
    )
    parser.add_argument(
        "--noise-suppress",
        action="store_true",
        help="Enable noise suppression. Requires openlrc[full].",
    )
    parser.add_argument(
        "--bilingual-sub",
        action="store_true",
        help="Write bilingual subtitles when translation is enabled.",
    )
    parser.add_argument(
        "--chatbot-model",
        default="gpt-4.1-nano",
        help="Translation model to use when --skip-trans is not set.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    lrcer = LRCer(
        transcription=TranscriptionConfig(
            asr_model=args.asr_model,
            device=args.device,
        ),
        translation=TranslationConfig(
            chatbot_model=args.chatbot_model,
        ),
    )

    outputs = lrcer.run(
        [Path(p) for p in args.paths],
        src_lang=args.src_lang,
        target_lang=args.target_lang,
        skip_trans=args.skip_trans,
        noise_suppress=args.noise_suppress,
        bilingual_sub=args.bilingual_sub,
    )

    print("Generated files:")
    for output in outputs:
        print(output)


if __name__ == "__main__":
    main()
