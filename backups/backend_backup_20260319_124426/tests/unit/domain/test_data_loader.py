import os
import csv
import pytest
from app.domain.fabio_ai.rl.data_loader import load_from_csv, split_data, DataSplit
from app.domain.trading.models.value_objects import OHLC

class TestDataLoader:
    def test_load_from_csv_empty(self, tmp_path):
        # File doesn't exist
        assert load_from_csv(str(tmp_path / "missing.csv")) == []

    def test_load_from_csv_valid(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        with open(csv_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["time", "open", "high", "low", "close", "volume", "delta"])
            writer.writeheader()
            writer.writerow({"time": "2024-01-01T00:00:00Z", "open": 100, "high": 105, "low": 95, "close": 102, "volume": 1000, "delta": 100})
            writer.writerow({"time": "2024-01-01T00:01:00Z", "open": 102, "high": 106, "low": 101, "close": 104, "volume": 1200, "delta": 200})

        candles = load_from_csv(str(csv_file))
        assert len(candles) == 2
        assert candles[0].open == 100
        assert candles[1].close == 104
        assert candles[0].delta == 100

    def test_split_data(self):
        data = [OHLC(time=f"t{i}", open=1, high=2, low=0, close=1, volume=10) for i in range(10)]
        
        split = split_data(data, train_ratio=0.6, val_ratio=0.2)
        
        assert isinstance(split, DataSplit)
        assert len(split.train) == 6
        assert len(split.validation) == 2
        assert len(split.test) == 2
        assert split.total == 10
        
        # Verify ordering
        assert split.train[0].time == "t0"
        assert split.test[1].time == "t9"

    def test_load_from_csv_skips_malformed_rows(self, tmp_path):
        csv_file = tmp_path / "bad.csv"
        with open(csv_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["time", "open", "high", "low", "close", "volume"])
            writer.writeheader()
            writer.writerow({"time": "t1", "open": "bad", "high": 105, "low": 95, "close": 102, "volume": 1000})
            writer.writerow({"time": "t2", "open": 102, "high": 106, "low": 101, "close": 104, "volume": 1200})

        candles = load_from_csv(str(csv_file))
        assert len(candles) == 1
        assert candles[0].time == "t2"
