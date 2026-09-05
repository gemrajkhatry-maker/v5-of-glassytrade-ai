# tests/quant/test_type_unification.py
"""Identity guarantees: sanctioned single definitions. Every re-export shim
must be the SAME object as its canonical home — equality is not enough."""

import quant.bars as bars
import quant.state_machine as state_machine


def test_bar_is_single_definition():
    assert state_machine.Bar is bars.Bar


def test_ibroker_single_home():
    import quant.contracts.ports.broker as cpb
    import brokers.broker.ports as bbp
    assert cpb.IBroker is bbp.IBroker


def test_dhan_entities_split_preserves_identity():
    import brokers.broker.dhan.domain.entities as ents
    import brokers.broker.dhan.domain.instrument as instrument
    import brokers.broker.dhan.domain.market_data as market_data
    import brokers.broker.dhan.domain.orders as orders

    for name, module in [
        ("DhanInstrument", instrument),
        ("DhanQuote", market_data),
        ("DhanTick", market_data),
        ("DhanOption", market_data),
        ("DhanOptionChain", market_data),
        ("DhanOrder", orders),
        ("DhanPosition", orders),
    ]:
        assert getattr(ents, name) is getattr(module, name)
