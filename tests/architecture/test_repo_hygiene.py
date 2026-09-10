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

# runtime_audit/ is throwaway probe/fixture output *except* for the helper
# modules live tracked tests import. tests/e2e/test_cross_process_injection.py
# does `sys.path.insert(.../runtime_audit/e2e)` + `from boot_helper import ...`
# at module scope, so that subtree must survive a fresh clone.
RUNTIME_AUDIT_ALLOWED_PREFIXES = ("runtime_audit/e2e/",)


def _tracked():
    out = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    return out


def test_no_generated_or_throwaway_paths_are_tracked():
    offenders = [
        p
        for p in _tracked()
        if p.startswith(FORBIDDEN_PREFIXES)
        and not p.startswith(RUNTIME_AUDIT_ALLOWED_PREFIXES)
    ]
    assert not offenders, f"{len(offenders)} tracked artifact paths, e.g. {offenders[:5]}"
