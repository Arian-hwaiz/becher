"""Gemeinsame Schnittstelle aller Collector."""
from __future__ import annotations

from abc import ABC, abstractmethod

from common.models import NormalizedEvent


class Collector(ABC):
    source: str = "base"

    @abstractmethod
    def fetch(self) -> list[NormalizedEvent]:
        """Holt die aktuellen Quoten und gibt sie normalisiert zurück."""
