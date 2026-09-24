from backend.scripts.generate_contracts import generate_typescript


def test_contract_generation_is_deterministic(tmp_path):
    output = tmp_path / "ws_v1.ts"
    first = generate_typescript(output)
    second = generate_typescript(output)
    assert first == second
    assert "ProjectionEnvelope" in output.read_text(encoding="utf-8")
