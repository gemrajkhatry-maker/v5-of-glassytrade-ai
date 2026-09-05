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
