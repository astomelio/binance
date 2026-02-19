from __future__ import annotations

from abc import ABC, abstractmethod

from ..fees import FeeModel
from ..models import FeatureSet, SignalDecision


class Strategy(ABC):
    @abstractmethod
    def generate(self, features: FeatureSet, fee_model: FeeModel) -> SignalDecision:
        raise NotImplementedError

