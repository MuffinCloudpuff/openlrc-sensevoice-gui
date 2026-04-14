from __future__ import annotations

from .providers.local_hymt import LocalHYMTProvider
from .providers.official_api import OfficialApiProvider
from .providers.relay_api import RelayApiProvider

TRANSLATION_PROVIDERS = [
    OfficialApiProvider(),
    RelayApiProvider(),
    LocalHYMTProvider(),
]


def get_provider_by_label(label: str):
    if not label:
        label = "中转 API"
    for provider in TRANSLATION_PROVIDERS:
        if provider.label == label:
            return provider
    raise KeyError(label)
