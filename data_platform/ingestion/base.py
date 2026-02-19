from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List


class Collector(ABC):
    source: str
    dataset: str

    @abstractmethod
    def collect(self) -> List[Dict]:
        raise NotImplementedError

