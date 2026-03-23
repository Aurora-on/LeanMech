from __future__ import annotations

from abc import ABC, abstractmethod

from mech_pipeline.types import CanonicalSample


class DatasetAdapter(ABC):
    @abstractmethod
    def load(self) -> list[CanonicalSample]:
        raise NotImplementedError
