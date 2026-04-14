from __future__ import annotations

from abc import ABC, abstractmethod

from ...models import AppConfig, ReplanStep


class TranslationProvider(ABC):
    backend_key: str
    label: str
    module_file: str
    estimated_duration: str

    def is_active(self, config: AppConfig) -> bool:
        return config.translation_backend == self.label

    @abstractmethod
    def validate(self, config: AppConfig) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def summary(self, config: AppConfig) -> str:
        raise NotImplementedError

    @abstractmethod
    def build_replan(self, config: AppConfig) -> list[ReplanStep]:
        raise NotImplementedError
