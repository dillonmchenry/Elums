"""GPU/CUDA architecture verification — M3 in IMPLEMENTATION_PLAN_2026-10-03.md.

Guards against the trap named in ELUMS_TECHNICAL_APPROACH.md §11.6:
`torch.cuda.is_available()` returns True on a wheel with no kernels for this
GPU's architecture, and the process doesn't fail until the first real kernel
launch. So this script asserts both halves — arch-list membership AND a
forced kernel launch — and refuses to run at all without an explicit
expected architecture, because "sm_86 locally, sm_120 on the VM" is the
whole point of pinning one torch wheel for both machines (§3.2).

Usage:
    EXPECTED_SM_ARCH=sm_86  python scripts/verify_gpu.py   # local (RTX 3070)
    EXPECTED_SM_ARCH=sm_120 python scripts/verify_gpu.py   # VM (RTX 5060 Ti)
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    expected = os.environ.get("EXPECTED_SM_ARCH")
    if not expected:
        print(
            "EXPECTED_SM_ARCH is not set — refusing to guess which "
            "architecture this run is supposed to require.",
            file=sys.stderr,
        )
        return 2

    import torch  # noqa: PLC0415 — deliberately imported after the env check

    arch_list = torch.cuda.get_arch_list()
    print(f"torch version:      {torch.__version__}")
    print(f"torch.version.cuda: {torch.version.cuda}")
    print(f"cuda.is_available(): {torch.cuda.is_available()}")
    print(f"arch list:           {arch_list}")

    if expected not in arch_list:
        print(
            f"FAIL: expected arch {expected!r} not present in {arch_list}",
            file=sys.stderr,
        )
        return 1

    if not torch.cuda.is_available():
        print("FAIL: is_available() is False", file=sys.stderr)
        return 1

    try:
        x = torch.zeros(8, device="cuda")
        x.add_(1)
        result = x.cpu().tolist()
    except Exception as exc:  # noqa: BLE001 — any exception here is the finding
        print(f"FAIL: forced kernel launch raised {exc!r}", file=sys.stderr)
        return 1

    if result != [1.0] * 8:
        print(f"FAIL: kernel launch produced wrong result: {result}", file=sys.stderr)
        return 1

    print(f"PASS: {expected} present in arch list and kernel launch succeeded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
