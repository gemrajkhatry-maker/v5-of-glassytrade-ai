"""HVN/LVN (High/Low Volume Node) Detector."""

from __future__ import annotations

from typing import Dict, List

from brokersv2.analytics.profile.events import VolumeNode, VolumeNodeType


class HVNLVNDetector:
    """
    Detect High and Low Volume Nodes in volume profiles.
    
    Features:
    - HVN detection (volume concentration)
    - LVN detection (volume gaps)
    - Strength calculation
    - Node sorting
    """

    def __init__(
        self,
        hvn_threshold: float = 1.5,
        lvn_threshold: float = 0.5,
    ):
        """
        Initialize detector.
        
        Args:
            hvn_threshold: Multiple of average volume for HVN
            lvn_threshold: Multiple of average volume for LVN
        """
        self.hvn_threshold = hvn_threshold
        self.lvn_threshold = lvn_threshold

    def find_hvns(
        self,
        volumes: Dict[float, float],
        threshold_volume: float,
    ) -> List[VolumeNode]:
        """
        Find High Volume Nodes.
        
        Args:
            volumes: Dict of price -> volume
            threshold_volume: Minimum volume threshold
            
        Returns:
            List of HVN nodes sorted by strength
        """
        if not volumes:
            return []
        
        max_volume = max(volumes.values())
        nodes = []
        
        for price, volume in volumes.items():
            if volume >= threshold_volume:
                strength = volume / max_volume if max_volume > 0 else 0.0
                nodes.append(VolumeNode(
                    node_type=VolumeNodeType.HVN,
                    price=price,
                    volume=volume,
                    strength=strength,
                ))
        
        # Sort by strength descending
        nodes.sort(key=lambda n: n.strength, reverse=True)
        return nodes

    def find_lvns(
        self,
        volumes: Dict[float, float],
        threshold_volume: float,
    ) -> List[VolumeNode]:
        """
        Find Low Volume Nodes.
        
        Args:
            volumes: Dict of price -> volume
            threshold_volume: Maximum volume threshold
            
        Returns:
            List of LVN nodes sorted by strength (inverse)
        """
        if not volumes:
            return []
        
        min_volume = min(volumes.values())
        max_volume = max(volumes.values())
        volume_range = max_volume - min_volume if max_volume != min_volume else 1.0
        
        nodes = []
        
        for price, volume in volumes.items():
            if volume <= threshold_volume:
                # Strength is inverse: lower volume = stronger LVN
                strength = 1.0 - ((volume - min_volume) / volume_range)
                nodes.append(VolumeNode(
                    node_type=VolumeNodeType.LVN,
                    price=price,
                    volume=volume,
                    strength=strength,
                ))
        
        # Sort by strength descending
        nodes.sort(key=lambda n: n.strength, reverse=True)
        return nodes
