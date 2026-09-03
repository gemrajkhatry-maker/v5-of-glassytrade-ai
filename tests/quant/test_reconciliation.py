"""Unit tests for the single reconciliation service helpers.

Supersedes the retired ``quant.reconciliation.Reconciliation`` raw-compare
contract: presence/size outcomes now live in
``quant.reconciliation_service`` (QUARANTINE default), and the matrix
outcomes are pinned in ``test_reconciliation_service_matrix.py``.
"""
from quant.reconciliation_service import (
    ReconcilePolicy,
    canonical_key,
    extract_symbol,
    index_rows,
    partition_keys,
)


class TestCanonicalKey:
    def test_upper_and_strip(self):
        assert canonical_key("  nifty aug fut ") == "NIFTY AUG FUT"

    def test_empty_safe(self):
        assert canonical_key("") == ""
        assert canonical_key(None) == ""


class TestExtractSymbol:
    def test_dict_trading_symbol_wins(self):
        assert extract_symbol({"trading_symbol": "X", "symbol": "Y"}) == "X"

    def test_dict_symbol_fallback(self):
        assert extract_symbol({"symbol": "Y"}) == "Y"

    def test_attr_symbol(self):
        class _P:
            symbol = "Z"
        assert extract_symbol(_P()) == "Z"

    def test_unknown_shape(self):
        assert extract_symbol(object()) == ""


class TestIndexRows:
    def test_skips_blank_keys(self):
        assert index_rows([{"symbol": ""}, {"symbol": "A"}]) == {"A": None}

    def test_size_of(self):
        rows = index_rows([{"symbol": "A", "size": 3}], size_of=lambda r: r["size"])
        assert rows == {"A": 3}


class TestPartitionKeys:
    def test_split(self):
        left_only, both, right_only = partition_keys({"a": 1, "b": 2}, {"b": 3, "c": 4})
        assert left_only == frozenset({"a"})
        assert both == frozenset({"b"})
        assert right_only == frozenset({"c"})


class TestPolicy:
    def test_quarantine_is_default(self):
        import inspect

        from quant.reconciliation_service import reconcile_sets

        assert (
            inspect.signature(reconcile_sets).parameters["policy"].default
            is ReconcilePolicy.QUARANTINE
        )
