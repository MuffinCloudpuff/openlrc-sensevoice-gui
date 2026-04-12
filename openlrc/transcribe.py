#  Copyright (C) 2025. Hao Zheng
#  All rights reserved.

from pathlib import Path
from typing import NamedTuple
import unicodedata

import pysbd
from tqdm import tqdm

from openlrc.defaults import default_sensevoice_options, resolve_sensevoice_model
from openlrc.logger import logger
from openlrc.utils import Timer, format_timestamp, get_audio_duration


class ASRWord(NamedTuple):
    """A single word/character with timing information."""

    start: float
    end: float
    word: str
    probability: float = 1.0


class ASRSegment(NamedTuple):
    """A transcription segment with start/end time and text.

    This replaces faster_whisper.transcribe.Segment with a local data class,
    decoupling the pipeline from any specific ASR backend.
    """

    id: int
    seek: int
    start: float
    end: float
    text: str
    tokens: list
    avg_logprob: float
    compression_ratio: float
    no_speech_prob: float
    words: list | None
    temperature: float


class TranscriptionInfo(NamedTuple):
    """
    Stores information about a transcription.

    Attributes:
        language (str): The detected language of the audio.
        duration (float): The total duration of the audio in seconds.
        duration_after_vad (float): The duration of the audio after Voice Activity Detection (VAD).
    """

    language: str
    duration: float
    duration_after_vad: float

    @property
    def vad_ratio(self):
        """
        Calculate the ratio of audio removed by VAD.

        Returns:
            float: The proportion of audio removed by VAD.
        """
        return 1 - self.duration_after_vad / self.duration


def _make_segment(seg_id: int, start: float, end: float, text: str, words: list | None = None) -> ASRSegment:
    """Convenience constructor for ASRSegment with sensible defaults."""
    return ASRSegment(
        id=seg_id,
        seek=0,
        start=start,
        end=end,
        text=text,
        tokens=[],
        avg_logprob=0.0,
        compression_ratio=0.0,
        no_speech_prob=0.0,
        words=words,
        temperature=0.0,
    )


class Transcriber:
    """
    A class for transcribing audio files using the SenseVoice model via FunASR.

    Attributes:
        model_name (str): The name of the SenseVoice model to use.
        device (str): The device to run the model on (e.g., 'cuda:0').
        continuous_scripted (list): List of languages that are continuously scripted.
        sensevoice_options (dict): Options for the SenseVoice model.
    """

    def __init__(
        self,
        model_name: str = "iic/SenseVoiceSmall",
        compute_type: str = "float16",
        device: str = "cuda",
        vad_filter: bool = True,
        asr_options: dict | None = None,
        vad_options: dict | None = None,
    ):
        self.model_name = resolve_sensevoice_model(model_name)
        self.device = device
        self.continuous_scripted = ["ja", "zh", "zh-cn", "th", "vi", "lo", "km", "my", "bo"]
        self.sensevoice_options = {**default_sensevoice_options, **(asr_options or {})}

        from funasr import AutoModel

        model_kwargs = {
            "model": self.model_name,
            "device": device,
        }

        if vad_filter:
            model_kwargs["vad_model"] = "fsmn-vad"
            model_kwargs["vad_kwargs"] = {"max_single_segment_time": 30000}
            if vad_options:
                model_kwargs["vad_kwargs"].update(vad_options)

        logger.info(f"Loading SenseVoice model: {self.model_name} on {device}")
        self.model = AutoModel(**model_kwargs)
        logger.info("SenseVoice model loaded successfully.")

    def transcribe(self, audio_path: str | Path, language: str | None = None):
        """
        Transcribe an audio file.

        Args:
            audio_path (Union[str, Path]): Path to the audio file.
            language (Optional[str]): Language of the audio. If None, it will be auto-detected.

        Returns:
            tuple: A tuple containing:
                - list[ASRSegment]: List of transcribed segments.
                - TranscriptionInfo: Information about the transcription.
        """
        from funasr.utils.postprocess_utils import rich_transcription_postprocess

        audio_path = Path(audio_path)
        total_duration = get_audio_duration(audio_path)

        language = self._map_language(language)

        with Timer("SenseVoice transcription"):
            with tqdm(total=int(total_duration), unit=" seconds", desc="Transcribing") as pbar:
                res = self.model.generate(
                    input=str(audio_path),
                    language=language or "auto",
                    use_itn=True,
                    output_timestamp=True,
                    batch_size_s=self.sensevoice_options.get("batch_size_s", 60),
                    merge_vad=True,
                    merge_length_s=self.sensevoice_options.get("merge_length_s", 15),
                )
                pbar.update(int(total_duration))

        if not res or not res[0]:
            logger.warning(f"No speech found for {audio_path}")
            return [], TranscriptionInfo(
                language=language or "en",
                duration=total_duration,
                duration_after_vad=total_duration,
            )

        result_data = res[0] if isinstance(res[0], list) else res
        if isinstance(result_data, dict):
            result_data = [result_data]

        raw_segments = []
        for item in result_data:
            raw_text = item.get("text", "")
            text = rich_transcription_postprocess(raw_text)

            if not text.strip():
                continue

            raw_segments.append(
                {
                    "text": text,
                    "timestamps": item.get("timestamp", []),  # [[start_ms, end_ms], ...] per word/token
                    "words": item.get("words", []),
                }
            )

        if not raw_segments:
            logger.warning(f"No speech found for {audio_path}")
            return [], TranscriptionInfo(
                language=language or "en",
                duration=total_duration,
                duration_after_vad=total_duration,
            )

        detected_lang = language or self._detect_language(raw_segments[0]["text"])

        with Timer("Sentence Segmentation"):
            result = self._build_segments(raw_segments, detected_lang)

        if result:
            duration_after_vad = result[-1].end
        else:
            duration_after_vad = total_duration

        info = TranscriptionInfo(
            language=detected_lang,
            duration=total_duration,
            duration_after_vad=duration_after_vad,
        )

        silence_duration = total_duration - info.duration_after_vad
        if silence_duration > 0:
            logger.info(
                f"Approximate silence removed: {format_timestamp(silence_duration)}s "
                f"({info.vad_ratio * 100:.1f}%)"
            )

        return result, info

    def _build_segments(self, raw_segments: list[dict], lang: str) -> list[ASRSegment]:
        """
        Convert SenseVoice raw output to ASRSegment list.

        For each raw segment, use pysbd to split text into sentences,
        then map word/token-level timestamps to sentence-level segments.
        """
        segmenter = pysbd.Segmenter(language=lang, clean=False)
        result = []
        seg_id = 0

        for raw in raw_segments:
            text = raw["text"]
            timestamps = raw["timestamps"]
            words = raw.get("words", [])

            sentences = [s for s in segmenter.segment(text) if s.strip()]

            if not sentences:
                start, end = self._get_segment_time(timestamps, 0, len(timestamps))
                result.append(_make_segment(seg_id, start, end, text.strip()))
                seg_id += 1
                continue

            word_offset = 0
            for sent in sentences:
                sent_text = sent.strip()
                alignment = self._align_sentence_to_words(sent_text, words, word_offset)

                if alignment is None:
                    logger.warning(f"Failed to align sentence to SenseVoice word timestamps: {sent_text!r}")
                    start_sec, end_sec = self._get_segment_time(timestamps, word_offset, len(timestamps))
                    result.append(_make_segment(seg_id, start_sec, end_sec, sent_text))
                    seg_id += 1
                    word_offset = len(words)
                    continue

                word_start_idx, word_end_idx = alignment
                word_slice = words[word_start_idx:word_end_idx]
                timestamp_slice = timestamps[word_start_idx:word_end_idx]
                start_sec, end_sec = self._get_segment_time(timestamps, word_start_idx, word_end_idx)

                char_limit = 45 if lang in self.continuous_scripted else 90
                if len(sent_text) > char_limit and timestamp_slice:
                    sub_segments = self._split_long_sentence(sent_text, word_slice, timestamp_slice, seg_id, lang)
                    result.extend(sub_segments)
                    seg_id += len(sub_segments)
                else:
                    result.append(_make_segment(seg_id, start_sec, end_sec, sent_text))
                    seg_id += 1

                word_offset = word_end_idx

        return result

    def _get_segment_time(self, timestamps: list, start_idx: int, end_idx: int) -> tuple[float, float]:
        """
        Get start/end time in seconds from word/token-level timestamps.

        Args:
            timestamps: [[start_ms, end_ms], ...] per word/token
            start_idx: Start token index
            end_idx: End token index (exclusive)

        Returns:
            (start_seconds, end_seconds)
        """
        if not timestamps:
            return 0.0, 0.0

        start_idx = max(0, min(start_idx, len(timestamps) - 1))
        end_idx = max(0, min(end_idx - 1, len(timestamps) - 1))

        try:
            start_ms = timestamps[start_idx][0]
            end_ms = timestamps[end_idx][1]
            return start_ms / 1000.0, end_ms / 1000.0
        except (IndexError, TypeError):
            logger.warning("Timestamp index out of range, using fallback")
            return 0.0, 0.0

    def _split_long_sentence(self, text: str, words: list, timestamps: list, start_id: int, lang: str) -> list[ASRSegment]:
        """
        Split a long sentence into smaller segments using word/token timestamps.
        """
        char_limit = 30 if lang in self.continuous_scripted else 60
        segments = []
        start = 0

        while start < len(words):
            end = start + 1
            best_break = None

            while end <= len(words):
                candidate_text = self._render_words(words[start:end], lang)
                if len(candidate_text) > char_limit:
                    break
                if self._is_break_token(words[end - 1]):
                    best_break = end
                end += 1

            if end > len(words):
                split_end = len(words)
            elif best_break is not None and best_break > start:
                split_end = best_break
            else:
                split_end = max(start + 1, end - 1)

            chunk_words = words[start:split_end]
            chunk_timestamps = timestamps[start:split_end]
            chunk_text = self._render_words(chunk_words, lang).strip()

            if not chunk_text:
                start = split_end
                continue

            try:
                start_sec = chunk_timestamps[0][0] / 1000.0
                end_sec = chunk_timestamps[-1][1] / 1000.0
            except (IndexError, TypeError):
                start_sec = 0.0
                end_sec = 0.0

            segments.append(_make_segment(start_id + len(segments), start_sec, end_sec, chunk_text))
            start = split_end

        return segments

    @staticmethod
    def _normalize_alignment_text(text: str) -> str:
        return "".join(ch for ch in text if not ch.isspace() and unicodedata.category(ch) != "So")

    def _align_sentence_to_words(self, sentence: str, words: list[str], start_idx: int) -> tuple[int, int] | None:
        target = self._normalize_alignment_text(sentence)
        if not target:
            return None

        current = ""
        first_idx = None
        idx = start_idx

        while idx < len(words):
            token = self._normalize_alignment_text(words[idx])
            if not token:
                idx += 1
                continue

            candidate = current + token
            if target.startswith(candidate):
                if first_idx is None:
                    first_idx = idx
                current = candidate
                idx += 1
                if current == target:
                    return first_idx, idx
                continue

            if first_idx is None:
                idx += 1
                continue

            break

        return None

    def _render_words(self, words: list[str], lang: str) -> str:
        if lang in self.continuous_scripted:
            return "".join(words)

        no_space_before = {".", ",", "!", "?", ":", ";", "%", ")", "]", "}", "。", "，", "！", "？", "：", "；"}
        no_space_after = {"(", "[", "{", "$", "#"}
        join_tokens = {"'", "’", "-", "/"}

        rendered = ""
        for word in words:
            if not word:
                continue

            if not rendered:
                rendered = word
                continue

            if word in no_space_before or word in join_tokens or rendered[-1] in join_tokens or rendered[-1] in no_space_after:
                rendered += word
            else:
                rendered += " " + word

        return rendered

    @staticmethod
    def _is_break_token(word: str) -> bool:
        return word in {".", ",", "!", "?", ":", ";", "。", "，", "！", "？", "：", "；"}

    @staticmethod
    def _map_language(lang: str | None) -> str | None:
        """Map common language codes to SenseVoice format."""
        if lang is None:
            return None
        lang_map = {
            "zh-cn": "zh",
            "zh-tw": "zh",
            "chinese": "zh",
            "japanese": "ja",
            "english": "en",
            "korean": "ko",
            "cantonese": "yue",
            "yue": "yue",
        }
        return lang_map.get(lang.lower(), lang.lower())

    @staticmethod
    def _detect_language(text: str) -> str:
        """Simple language detection from transcribed text."""
        cjk_count = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        hiragana_count = sum(1 for c in text if "\u3040" <= c <= "\u309f")
        katakana_count = sum(1 for c in text if "\u30a0" <= c <= "\u30ff")
        hangul_count = sum(1 for c in text if "\uac00" <= c <= "\ud7af")

        total = len(text)
        if total == 0:
            return "en"

        if hangul_count / total > 0.3:
            return "ko"
        if (hiragana_count + katakana_count) / total > 0.2:
            return "ja"
        if cjk_count / total > 0.3:
            return "zh"

        return "en"
