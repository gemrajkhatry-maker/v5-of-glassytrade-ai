"""D-26/D-27: generated and throwaway paths must not be tracked."""

import subprocess

FORBIDDEN_PREFIXES = (
    "backend/graphify-out/",
    ".freebuff/",
    "runtime_audit/",
    "scratch/",
    ".kilo/",
    ".commandcode/",
    "quantv2/",
)


def _tracked():
    out = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    return out


def test_no_generated_or_throwaway_paths_are_tracked():
    offenders = [p for p in _tracked() if p.startswith(FORBIDDEN_PREFIXES)]
    assert not offenders, f"{len(offenders)} tracked artifact paths, e.g. {offenders[:5]}"
