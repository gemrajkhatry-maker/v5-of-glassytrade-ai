from typing import List, Dict, Any, Optional
from app.domain.ports.market_data import IMarketData, OptionChain, OptionContract
from app.domain.ports.broker import IBroker
from app.domain.ports.storage import IStorage
from app.domain.ports.llm_inference import ILLMInference
from app.domain.ports.probability_inference import IProbabilityInference
from config.config import Configuration


class ScannerService:
    """Service for scanning and selecting option contracts."""

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

    async def scan(
        self,
        underlyings: List[str],
        n: int = 3,
        per_underlying: int = 2,
    ) -> List[Dict[str, Any]]:
        """Scan for top option contracts."""
        results = []

        for underlying in underlyings:
            # Fetch option chains
            chain = await self.market_data.get_option_chain(
                underlying=underlying,
                exchange="NFO",
                expiry_index=0,
            )
            if not chain:
                continue

            # Filter contracts
            contracts = self._filter_contracts(chain)

            # Score contracts
            scored = self._score_contracts(contracts, chain.spot_price)

            # Select top N per underlying
            top_n = scored[:per_underlying]
            results.extend(top_n)

        # Global top N
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:n]

    def _filter_contracts(self, chain: OptionChain) -> List[OptionContract]:
        """Filter option contracts based on criteria."""
        contracts = []

        for contract in chain.contracts.values():
            # Premium filter
            if not (
                self.config.scanner.min_premium
                <= contract.ltp
                <= self.config.scanner.max_premium
            ):
                continue

            # OI filter
            if contract.oi < self.config.scanner.min_oi:
                continue

            # Spread filter
            spread_pct = (
                (contract.ask - contract.bid)
                / ((contract.ask + contract.bid) / 2)
                * 100
            )
            if spread_pct > self.config.scanner.max_spread_pct:
                continue

            contracts.append(contract)

        return contracts

    def _score_contracts(
        self,
        contracts: List[OptionContract],
        spot_price: float,
    ) -> List[Dict[str, Any]]:
        """Score option contracts based on multiple factors."""
        scored = []

        for contract in contracts:
            score = 0

            # ATM proximity (40 points)
            atm_distance = abs(contract.strike - spot_price)
            atm_weight = 40 * (
                1
                - min(atm_distance / (self.config.scanner.strikes_around_atm * 100), 1)
            )
            score += atm_weight

            # Liquidity (30 points)
            liquidity_score = min(contract.oi / 10000, 1.0)  # Normalize to 0-1
            score += liquidity_score * 30

            # Momentum (20 points)
            momentum_score = self._calculate_momentum(contract)
            score += momentum_score * 20

            # Delta sweet spot (10 points)
            delta_score = 1.0 if 0.4 <= abs(contract.delta) <= 0.7 else 0.0
            score += delta_score * 10

            # Spread penalty
            spread_pct = (
                (contract.ask - contract.bid)
                / ((contract.ask + contract.bid) / 2)
                * 100
            )
            spread_penalty = min(spread_pct - 1.0, 0)  # Penalty for spreads > 1%
            score += spread_penalty * 20  # Up to -20 points

            scored.append(
                {
                    "contract": contract,
                    "score": score,
                    "underlying": contract.underlying,
                }
            )

        return scored

    def _calculate_momentum(self, contract: OptionContract) -> float:
        """Calculate momentum score for a contract."""
        # This is a simplified momentum calculation
        # In reality, you'd use historical data and volume profile
        return 0.5  # Placeholder
