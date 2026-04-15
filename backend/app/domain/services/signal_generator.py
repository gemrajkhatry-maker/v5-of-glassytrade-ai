from typing import List, Dict, Any
from app.domain.ports.market_data import IMarketData
from app.domain.ports.broker import IBroker
from app.domain.ports.storage import IStorage
from app.domain.ports.llm_inference import ILLMInference
from app.domain.ports.probability_inference import IProbabilityInference
from config.config import Configuration


class SignalGenerator:
    """Generates trading signals from AMT analysis."""

    def __init__(
        self,
        config: Configuration,
        market_data: IMarketData,
        storage: IStorage,
        llm: ILLMInference,
        probability: IProbabilityInference,
    ):
        self.config = config
        self.market_data = market_data
        self.storage = storage
        self.llm = llm
        self.probability = probability

    def generate(
        self,
        candles: List[Dict[str, Any]],
        volume_profile: Dict[str, Any],
        market_state: str,
        lvns: List[float],
        hvns: List[float],
        aggression_score: float,
    ) -> List[Dict[str, Any]]:
        """Generate trading signals from AMT analysis."""
        signals = []

        if not candles or not volume_profile:
            return signals

        current_price = candles[-1]["close"]
        vah = volume_profile.get("vah", 0)
        val = volume_profile.get("val", 0)

        # Check if price is inside value area
        inside_va = val <= current_price <= vah

        # Generate signals based on market state
        if market_state == "BALANCED":
            signals.extend(
                self._generate_balanced_signals(candles, volume_profile, current_price)
            )
        elif market_state == "IMBALANCED":
            signals.extend(
                self._generate_imbalanced_signals(
                    candles, volume_profile, current_price
                )
            )
        elif market_state == "TRENDING":
            signals.extend(
                self._generate_trending_signals(candles, volume_profile, current_price)
            )

        # Add aggression filter
        if aggression_score < 0.3:
            # Low aggression, reduce signal strength
            for signal in signals:
                signal["confidence"] = max(0.1, signal.get("confidence", 0.5) - 0.2)

        return signals

    def _generate_balanced_signals(
        self,
        candles: List[Dict[str, Any]],
        profile: Dict[str, Any],
        current_price: float,
    ) -> List[Dict[str, Any]]:
        """Generate signals for balanced market."""
        signals = []

        vah = profile.get("vah", 0)
        val = profile.get("val", 0)
        poc = profile.get("poc", 0)

        # Mean reversion to POC
        if current_price > poc:
            # Consider short opportunity
            signals.append(
                {
                    "type": "SHORT",
                    "price": current_price,
                    "reason": "Mean reversion from above POC",
                    "confidence": 0.6,
                    "target": poc,
                    "stop": vah,
                }
            )
        elif current_price < poc:
            # Consider long opportunity
            signals.append(
                {
                    "type": "LONG",
                    "price": current_price,
                    "reason": "Mean reversion from below POC",
                    "confidence": 0.6,
                    "target": poc,
                    "stop": val,
                }
            )

        return signals

    def _generate_imbalanced_signals(
        self,
        candles: List[Dict[str, Any]],
        profile: Dict[str, Any],
        current_price: float,
    ) -> List[Dict[str, Any]]:
        """Generate signals for imbalanced market."""
        signals = []

        vah = profile.get("vah", 0)
        val = profile.get("val", 0)

        # Trade toward value area
        if current_price < val:
            signals.append(
                {
                    "type": "LONG",
                    "price": current_price,
                    "reason": "Price below value area",
                    "confidence": 0.7,
                    "target": val,
                    "stop": val * 0.98,  # 2% below val
                }
            )
        elif current_price > vah:
            signals.append(
                {
                    "type": "SHORT",
                    "price": current_price,
                    "reason": "Price above value area",
                    "confidence": 0.7,
                    "target": vah,
                    "stop": vah * 1.02,  # 2% above vah
                }
            )

        return signals

    def _generate_trending_signals(
        self,
        candles: List[Dict[str, Any]],
        profile: Dict[str, Any],
        current_price: float,
    ) -> List[Dict[str, Any]]:
        """Generate signals for trending market."""
        signals = []

        # Trend following
        if self._is_up_trend(candles):
            signals.append(
                {
                    "type": "LONG",
                    "price": current_price,
                    "reason": "Up trend continuation",
                    "confidence": 0.8,
                    "target": current_price * 1.02,  # 2% target
                    "stop": current_price * 0.98,  # 2% stop
                }
            )
        elif self._is_down_trend(candles):
            signals.append(
                {
                    "type": "SHORT",
                    "price": current_price,
                    "reason": "Down trend continuation",
                    "confidence": 0.8,
                    "target": current_price * 0.98,  # 2% target
                    "stop": current_price * 1.02,  # 2% stop
                }
            )

        return signals

    def _is_up_trend(self, candles: List[Dict[str, Any]]) -> bool:
        """Check if we're in an up trend."""
        if len(candles) < 20:
            return False

        recent = candles[-10:]
        higher_highs = all(
            recent[i]["high"] >= recent[i - 1]["high"] for i in range(1, len(recent))
        )
        higher_lows = all(
            recent[i]["low"] >= recent[i - 1]["low"] for i in range(1, len(recent))
        )

        return higher_highs and higher_lows

    def _is_down_trend(self, candles: List[Dict[str, Any]]) -> bool:
        """Check if we're in a down trend."""
        if len(candles) < 20:
            return False

        recent = candles[-10:]
        lower_highs = all(
            recent[i]["high"] <= recent[i - 1]["high"] for i in range(1, len(recent))
        )
        lower_lows = all(
            recent[i]["low"] <= recent[i - 1]["low"] for i in range(1, len(recent))
        )

        return lower_highs and lower_lows
