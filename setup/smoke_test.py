import importlib
import sys

IMPORT_MODULES = [
    "http.client",
    "http.cookiejar",
    "json",
    "os",
    "socket",
    "sys",
    "time",
    "urllib.error",
    "urllib.parse",
    "urllib.request",
]


def main() -> int:
    failures = []
    for module in IMPORT_MODULES:
        try:
            importlib.import_module(module)
        except Exception as exc:
            failures.append((module, exc))

    if failures:
        print("Smoke test failed: some imports could not be loaded.")
        for module, exc in failures:
            print(f"- {module}: {exc}")
        return 1

    print("Smoke test passed: all import checks succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
