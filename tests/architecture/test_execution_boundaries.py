"""Approved execution-boundary ratchets.

These tests protect the architecture without prescribing implementation details
outside the public contracts.
"""

import ast
import pathlib

from quant.contracts.execution_vocabulary import EconomicOperationId
from quant.execution.execution_state_machine import ExecutionStateMachine
from quant.execution.flow_provenance import (
    FlowProvenance,
    InferredFlowRejected,
    require_exact_l2_for_paper,
)


ROOT = pathlib.Path(__file__).resolve().parents[2]
_TRANSPORT_FILES = (
    "backend/app/api/websocket/gameloop.py",
    "backend/app/api/routers/health.py",
    "backend/app/api/routers/trading.py",
)


def test_transport_does_not_import_engine_implementations():
    forbidden = {"quant.multi_engine", "quant.runtime"}
    violations = []
    for rel in _TRANSPORT_FILES:
        tree = ast.parse((ROOT / rel).read_text(), filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                names = {node.module or ""}
            else:
                continue
            violations.extend((rel, name) for name in names if name in forbidden)
    assert violations == []


def test_inferred_flow_cannot_be_upgraded_to_exact_for_paper():
    try:
        require_exact_l2_for_paper(FlowProvenance.INFERRED_AMT_TICK)
    except InferredFlowRejected:
        pass
    else:
        raise AssertionError("inferred order flow must remain blocked")


def test_execution_identity_remains_stable_across_lifecycle_transitions():
    operation_id = EconomicOperationId("close-identity-1")
    machine = ExecutionStateMachine(operation_id)

    machine.submit()
    machine.unknown()
    machine.reconciliation_required()
    machine.reconciled()

    assert machine.operation_id == operation_id
    assert machine.operation_id.value == "close-identity-1"
