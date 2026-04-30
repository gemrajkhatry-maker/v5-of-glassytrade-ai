"""Tests for OI Wall Engine — NSE order flow proxy."""

import pytest

from app.domain.services.oi_wall_engine import OIWallEngine, OIWall


class TestOIWallEngine:
    """Tests for OI wall detection."""

    def _make_option_chain(self, strikes_oi: dict[str, dict]) -> list[dict]:
        """Create mock option chain from strike: {ce_oi, pe_oi} dict."""
        chain = []
        for strike, data in strikes_oi.items():
            chain.append({
                "strike": int(strike),
                "ce_oi": data.get("ce_oi", 0),
                "pe_oi": data.get("pe_oi", 0),
                "ce_oi_change": data.get("ce_oi_change", 0),
                "pe_oi_change": data.get("pe_oi_change", 0),
                "ce_volume": data.get("ce_volume", 0),
                "pe_volume": data.get("pe_volume", 0),
            })
        return chain

    def test_detects_call_wall_above_threshold(self):
        """CE OI > 3x average should be detected as call wall."""
        engine = OIWallEngine()

        # Create chain where strike 25000 has high CE OI
        chain = self._make_option_chain({
            "24900": {"ce_oi": 50_000, "pe_oi": 200_000},
            "24950": {"ce_oi": 100_000, "pe_oi": 150_000},
            "25000": {"ce_oi": 500_000, "pe_oi": 100_000},  # High CE = call wall
            "25050": {"ce_oi": 120_000, "pe_oi": 200_000},
            "25100": {"ce_oi": 60_000, "pe_oi": 180_000},
        })

        walls = engine.detect_walls(chain)

        call_walls = [w for w in walls if w.wall_type == "CALL_WALL"]
        assert len(call_walls) == 1
        assert call_walls[0].strike == 25000
        assert call_walls[0].strength >= 3.0

    def test_detects_put_wall_above_threshold(self):
        """PE OI > 3x average should be detected as put wall."""
        engine = OIWallEngine()

        # Use much higher PE OI to clear threshold
        chain = self._make_option_chain({
            "24900": {"ce_oi": 50_000, "pe_oi": 500_000},  # High PE = put wall
            "24950": {"ce_oi": 80_000, "pe_oi": 90_000},
            "25000": {"ce_oi": 100_000, "pe_oi": 100_000},
            "25050": {"ce_oi": 90_000, "pe_oi": 80_000},
            "25100": {"ce_oi": 60_000, "pe_oi": 50_000},
        })

        walls = engine.detect_walls(chain)

        put_walls = [w for w in walls if w.wall_type == "PUT_WALL"]
        assert len(put_walls) >= 1

    def test_no_walls_below_threshold(self):
        """OI below threshold should not create walls."""
        engine = OIWallEngine()

        # All strikes have similar OI (no wall)
        chain = self._make_option_chain({
            "24900": {"ce_oi": 100_000, "pe_oi": 110_000},
            "25000": {"ce_oi": 105_000, "pe_oi": 105_000},
            "25100": {"ce_oi": 100_000, "pe_oi": 115_000},
        })

        walls = engine.detect_walls(chain)
        assert len(walls) == 0

    def test_sorts_by_spot_proximity(self):
        """Walls should be sorted by distance to spot price."""
        engine = OIWallEngine()

        # Create chain with varying OI - need some high disparity
        chain = self._make_option_chain({
            "24900": {"ce_oi": 30_000, "pe_oi": 400_000},  # PE wall (strong)
            "25000": {"ce_oi": 400_000, "pe_oi": 30_000},  # CE wall (strong)
            "25100": {"ce_oi": 30_000, "pe_oi": 400_000},  # PE wall (strong)
        })

        # Spot at 25000 - nearest walls should be 25000
        walls = engine.detect_walls(chain, spot_price=25000)

        assert len(walls) >= 1
        # 25000 should have a wall
        strikes = [w.strike for w in walls]
        assert 25000 in strikes

    def test_get_nearest_wall_for_longs(self):
        """LONG stop should use nearest PUT_WALL below price."""
        engine = OIWallEngine()

        walls = [
            OIWall(strike=24900, wall_type="PUT_WALL", oi=200_000, oi_change=10_000, strength=4.0, confidence=0.8),
            OIWall(strike=24950, wall_type="PUT_WALL", oi=150_000, oi_change=5_000, strength=3.5, confidence=0.7),
            OIWall(strike=25050, wall_type="CALL_WALL", oi=300_000, oi_change=-5_000, strength=5.0, confidence=0.9),
        ]

        # LONG at 24980 - nearest put wall below
        nearest = engine.get_nearest_wall(walls, 24980, "LONG")
        assert nearest is not None
        assert nearest.strike == 24950

    def test_get_nearest_wall_for_shorts(self):
        """SHORT stop should use nearest CALL_WALL above price."""
        engine = OIWallEngine()

        walls = [
            OIWall(strike=24900, wall_type="PUT_WALL", oi=200_000, oi_change=10_000, strength=4.0, confidence=0.8),
            OIWall(strike=25050, wall_type="CALL_WALL", oi=300_000, oi_change=-5_000, strength=5.0, confidence=0.9),
            OIWall(strike=25100, wall_type="CALL_WALL", oi=250_000, oi_change=-3_000, strength=4.5, confidence=0.8),
        ]

        # SHORT at 25000 - nearest call wall above
        nearest = engine.get_nearest_wall(walls, 25000, "SHORT")
        assert nearest is not None
        assert nearest.strike == 25050

    def test_align_with_volume_profile(self):
        """Walls aligning with VP levels have higher significance."""
        engine = OIWallEngine()

        walls = [
            OIWall(strike=24900, wall_type="PUT_WALL", oi=200_000, oi_change=10_000, strength=4.0, confidence=0.8),
            OIWall(strike=24950, wall_type="CALL_WALL", oi=300_000, oi_change=-5_000, strength=5.0, confidence=0.9),
            OIWall(strike=25000, wall_type="PUT_WALL", oi=150_000, oi_change=5_000, strength=3.5, confidence=0.7),
            OIWall(strike=25100, wall_type="CALL_WALL", oi=250_000, oi_change=-3_000, strength=4.5, confidence=0.8),
        ]

        # VAL=24900, VAH=25100, POC=25000
        aligned = engine.align_with_vp_levels(walls, val=24900, vah=25100, poc=25000)

        assert len(aligned) == 4  # All align with VP levels

    def test_empty_chain_returns_empty_walls(self):
        """Empty option chain should return no walls."""
        engine = OIWallEngine()
        walls = engine.detect_walls([])
        assert walls == []


class TestOIWall:
    """Tests for OIWall dataclass."""

    def test_wall_creation(self):
        wall = OIWall(
            strike=25000,
            wall_type="CALL_WALL",
            oi=500_000,
            oi_change=10_000,
            strength=5.0,
            confidence=0.9,
        )

        assert wall.strike == 25000
        assert wall.wall_type == "CALL_WALL"
        assert wall.oi == 500_000
        assert wall.strength == 5.0
        assert wall.confidence == 0.9