#  Copyright (C) 2025. Hao Zheng
#  All rights reserved.
import logging
import os
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from ffmpeg_normalize import FFmpegNormalize
from tqdm import tqdm

from openlrc.defaults import default_preprocess_options
from openlrc.logger import logger
from openlrc.utils import get_preprocessed_path, release_memory


def loudness_norm_single(audio_path: Path, ln_path: Path):
    """
    Normalize the loudness of a single audio file using FFmpegNormalize.

    Args:
        audio_path (Path): The path to the input audio file.
        ln_path (Path): The path to save the normalized audio file.
    """
    normalizer = FFmpegNormalize(
        output_format="wav",
        sample_rate=48000,
        progress=logger.level <= logging.DEBUG,
        keep_lra_above_loudness_range_target=True,
    )

    if not ln_path.exists():
        normalizer.add_media_file(str(audio_path), str(ln_path))
        normalizer.run_normalization()


class Preprocessor:
    """
    Preprocess audio to make it clear and normalized.
    """

    def __init__(
        self,
        audio_paths: str | Path | list[str] | list[Path],
        output_folder: str = "preprocessed",
        options: dict | None = None,
    ):
        if options is None:
            options = dict(default_preprocess_options)
        paths_list = audio_paths if isinstance(audio_paths, list) else [audio_paths]
        self.audio_paths: list[Path] = [Path(p) for p in paths_list]
        self.output_folder = output_folder
        self.output_paths = [p.parent / output_folder for p in self.audio_paths]
        self.options = options

        for path in self.output_paths:
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)

    def _resolve_preprocess_workers(self) -> int:
        requested = int(self.options.get("preprocess_workers") or 0)
        if requested > 0:
            return max(1, min(8, requested))

        cpu_count = os.cpu_count() or 1
        return max(1, min(4, cpu_count // 2 or 1))

    def noise_suppression(self, audio_paths: list[Path], atten_lim_db: int = 15):
        """
        Suppress noise in audio.
        """
        if not audio_paths:
            return []

        try:
            import torch
            from df.enhance import enhance, init_df, load_audio, save_audio
        except ImportError:
            raise ImportError(
                "Noise suppression requires torch and deepfilternet. "
                "Install them with: pip install 'openlrc[full]'"
            )

        if "atten_lim_db" in self.options:
            atten_lim_db = self.options["atten_lim_db"]

        model, df_state, _ = init_df()
        chunk_size = 180  # 3 min

        ns_audio_paths = []
        for audio_path in audio_paths:
            output_path = audio_path.parent / self.output_folder
            audio_name = audio_path.stem
            ns_path = output_path / f"{audio_name}_ns.wav"

            if not ns_path.exists():
                audio, info = load_audio(audio_path, sr=df_state.sr())

                # Split audio into 3 min chunks
                audio_chunks = [
                    audio[:, i : i + chunk_size * info.sample_rate]
                    for i in range(0, audio.shape[1], chunk_size * info.sample_rate)
                ]

                enhanced_chunks = []
                for ac in tqdm(audio_chunks, desc=f"Noise suppressing for {audio_name}"):
                    enhanced_chunks.append(enhance(model, df_state, ac, atten_lim_db=atten_lim_db))

                enhanced = torch.cat(enhanced_chunks, dim=1)

                assert enhanced.shape == audio.shape, (
                    f"Enhanced audio shape does not match original audio shape: {enhanced.shape} != {audio.shape}"
                )

                save_audio(ns_path, enhanced, sr=df_state.sr())

            ns_audio_paths.append(ns_path)

        release_memory(model)

        return ns_audio_paths

    def loudness_normalization(
        self,
        audio_paths: list[Path],
        progress_callback: Callable[[int, int, Path], None] | None = None,
    ):
        """
        Normalize loudness of audio.
        """
        logger.info("Loudness normalizing...")

        args = []
        ln_audio_paths = []
        for audio_path in audio_paths:
            output_path = audio_path.parent / self.output_folder
            ln_path = output_path / f"{audio_path.stem}_ln.wav"
            args.append((audio_path, ln_path))
            ln_audio_paths.append(ln_path)

        if not args:
            return ln_audio_paths

        max_workers = min(self._resolve_preprocess_workers(), len(args))

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_to_index = {
                executor.submit(loudness_norm_single, *arg): index
                for index, arg in enumerate(args)
            }

            completed = 0
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    future.result()
                except Exception as exception:
                    logger.error(f"Loudness normalization failed, exception: {exception}")
                    raise exception

                completed += 1
                if progress_callback is not None:
                    progress_callback(completed, len(args), args[index][0])

        return ln_audio_paths

    def run(
        self,
        noise_suppress: bool = False,
        progress_callback: Callable[[int, int, Path], None] | None = None,
    ):
        """
        Args:
            noise_suppress (bool, optional): A boolean flag indicating whether to perform noise suppression.
                Defaults to False.

        Returns:
            list of Path: A list of Path objects representing the final processed audio paths.
        """
        # Check if the preprocessed audio already exists.
        need_process = []
        final_processed_audios = []
        completed = 0
        for audio_path, output_path in zip(self.audio_paths, self.output_paths):
            preprocessed_path = get_preprocessed_path(audio_path)
            final_processed_audios.append(preprocessed_path)
            if preprocessed_path.exists():
                logger.info(f"Preprocessed audio already exists in {preprocessed_path}")
                completed += 1
                if progress_callback is not None:
                    progress_callback(completed, len(self.audio_paths), audio_path)
                continue
            else:
                need_process.append(audio_path)

        ns_paths = need_process
        if noise_suppress:
            ns_paths = self.noise_suppression(need_process)
        ln_paths: list[Path] = self.loudness_normalization(
            ns_paths,
            progress_callback=(
                (lambda batch_completed, batch_total, audio_path: progress_callback(
                    completed + batch_completed,
                    len(self.audio_paths),
                    audio_path,
                ))
                if progress_callback is not None and not noise_suppress
                else None
            ),
        )

        for path, audio_path in zip(ln_paths, need_process):
            final_path = get_preprocessed_path(audio_path)
            path.rename(final_path)
            logger.info(f"Preprocessed audio saved to {final_path}")
            completed += 1
            if progress_callback is not None and noise_suppress:
                progress_callback(completed, len(self.audio_paths), audio_path)

        return final_processed_audios
