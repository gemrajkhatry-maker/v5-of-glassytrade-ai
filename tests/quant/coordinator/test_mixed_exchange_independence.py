from quant.multi_engine import QuantCoordinator


class _MarketData:
    pass


def test_nse_future_and_option_have_independent_contract_identity(tmp_path):
    coordinator = QuantCoordinator(
        _MarketData(),
        config={"exchange": "NSE", "contracts_file": str(tmp_path / "nse.json")},
    )
    future = coordinator._contract_for("NIFTY AUG FUT")
    option = coordinator._contract_for("NIFTY 30 SEP 25000 CE")

    assert future.exchange in {"NSE", "NFO"}
    assert option.exchange == "NFO"
    assert future.symbol != option.symbol
    assert option.option_type == "CE"


def test_mcx_future_and_option_have_independent_contract_identity(tmp_path):
    coordinator = QuantCoordinator(
        _MarketData(),
        config={"exchange": "MCX", "contracts_file": str(tmp_path / "mcx.json")},
    )
    future = coordinator._contract_for("CRUDEOIL AUG FUT")
    option = coordinator._contract_for("CRUDEOIL 30 SEP 6000 PUT")

    assert future.exchange == "MCX"
    assert option.exchange == "MCX"
    assert future.symbol != option.symbol
    assert option.option_type == "PE"


def test_coordinator_defaults_to_independent_topology_for_mixed_universe(tmp_path):
    coordinator = QuantCoordinator(
        _MarketData(),
        config={"contracts_file": str(tmp_path / "mixed.json")},
    )
    assert coordinator.config["execution_model"] == "independent"
    assert coordinator._underlying_gateways == {}
