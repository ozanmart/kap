from __future__ import annotations

import sys
import time
import inspect
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import test_models
import test_parsing
import test_event_extractor
import test_client
import test_tools

MODULES = [
    ("Models", test_models),
    ("Parsing", test_parsing),
    ("Event Extractor", test_event_extractor),
    ("Client & Storage", test_client),
    ("Agent Tools & Schemas", test_tools),
]

def main():
    total_passed = 0
    total_failed = 0
    start_time = time.time()

    print("=" * 60)
    print(" Running KAP SDK Test Suite")
    print("=" * 60)

    for mod_name, mod in MODULES:
        print(f"\n📂 Suite: {mod_name}")
        for attr_name in dir(mod):
            if attr_name.startswith("test_"):
                fn = getattr(mod, attr_name)
                if callable(fn):
                    t0 = time.time()
                    try:
                        fn()
                        elapsed = (time.time() - t0) * 1000
                        print(f"  ✅ PASS: {attr_name:<35} ({elapsed:.1f}ms)")
                        total_passed += 1
                    except Exception as e:
                        elapsed = (time.time() - t0) * 1000
                        print(f"  ❌ FAIL: {attr_name:<35} ({elapsed:.1f}ms)")
                        print(f"     Error: {e}")
                        total_failed += 1

    total_time = (time.time() - start_time) * 1000
    print("\n" + "=" * 60)
    print(f" Test Results: {total_passed} Passed | {total_failed} Failed | Total Time: {total_time:.1f}ms")
    print("=" * 60)

    if total_failed > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
