from glassytrade.application.commands.promote_runtime import promote_runtime


def test_promote_runtime_requires_execute_flag():
    result = promote_runtime({"target_release_id": "release-1"}, execute=False)
    assert result.executed is False
    assert result.allowed is True
