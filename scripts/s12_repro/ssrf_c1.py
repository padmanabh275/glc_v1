"""C1 SSRF repro — /v1/vision must reject private/link-local and non-allowlisted hosts.

Uses the in-process URL guard directly (no live provider required).
"""

from __future__ import annotations

import sys


def main() -> int:
    from glc.security.url_fetch import UrlFetchError, assert_safe_image_url, host_on_allowlist

    cases = [
        ("http://127.0.0.1/secret", True),
        ("http://169.254.169.254/latest/meta-data/", True),
        ("http://[::1]/", True),
        ("https://evil.example.com/img.png", True),
    ]
    fails = 0
    for url, expect_block in cases:
        blocked = False
        try:
            assert_safe_image_url(url, resolve_dns=False)
        except UrlFetchError:
            blocked = True
        ok = blocked == expect_block
        print(f"[{'PASS' if ok else 'FAIL'}] {url} blocked={blocked} expect_block={expect_block}")
        if not ok:
            fails += 1

    # Allowlist membership (no DNS)
    allowed = host_on_allowlist("storage.googleapis.com")
    print(f"[{'PASS' if allowed else 'FAIL'}] storage.googleapis.com on allowlist")
    if not allowed:
        fails += 1
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
