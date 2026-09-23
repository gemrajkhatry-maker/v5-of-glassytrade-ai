from automation.cli import main
import sys


def test_cli_scan_command(capsys):
    """CLI scan command works."""
    sys.argv = ["automation-cli", "scan", "automation"]
    try:
        main()
    except SystemExit:
        pass

    captured = capsys.readouterr()
    assert "Quality Scan Report" in captured.out


def test_cli_test_command(capsys):
    """CLI test command works."""
    sys.argv = ["automation-cli", "test", "tests/automation/test_scanner.py"]
    try:
        main()
    except SystemExit:
        pass

    captured = capsys.readouterr()
    assert "Test Report" in captured.out


def test_cli_gate_command(capsys):
    """CLI gate command works."""
    sys.argv = ["automation-cli", "gate", "--source", "automation", "--no-tests"]
    try:
        main()
    except SystemExit:
        pass

    captured = capsys.readouterr()
    assert "Quality Gate Report" in captured.out


def test_cli_fixes_command(capsys):
    """CLI fixes command works."""
    sys.argv = ["automation-cli", "fixes", "automation"]
    try:
        main()
    except SystemExit:
        pass

    captured = capsys.readouterr()
    assert "Total fixable issues" in captured.out


def test_cli_no_command_shows_help(capsys):
    """CLI with no command shows help."""
    sys.argv = ["automation-cli"]
    try:
        result = main()
    except SystemExit as e:
        result = e.code

    captured = capsys.readouterr()
    assert "usage:" in captured.out.lower() or result == 1
