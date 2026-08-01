#!/usr/bin/env python3
"""
Test runner script for OtelMS API.
Run with: python scripts/run_tests.py
"""
import subprocess
import sys
import os

# Ensure we run from project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)


def run_command(cmd, description):
    """Run a command and return success status."""
    print(f"\n{'='*60}")
    print(f"Running: {description}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'='*60}")
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    
    success = result.returncode == 0
    print(f"\n{'✓ SUCCESS' if success else '✗ FAILED'} - {description}")
    return success


def main():
    """Run all tests."""
    print("OtelMS API - Test Suite")
    print("=" * 60)
    
    all_passed = True
    
    # 1. Lint checks
    all_passed &= run_command(
        ["uv", "run", "ruff", "check", "."],
        "Ruff lint check"
    )
    
    all_passed &= run_command(
        ["uv", "run", "ruff", "format", "--check", "."],
        "Ruff format check"
    )
    
    all_passed &= run_command(
        ["uv", "run", "mypy", "src/otelms"],
        "MyPy type check"
    )
    
    # 2. Unit tests
    all_passed &= run_command(
        ["uv", "run", "pytest", "tests/unit", "-v", "--tb=short"],
        "Unit tests"
    )
    
    # 3. Integration tests (require database - skip if no test DB)
    # all_passed &= run_command(
    #     ["uv", "run", "pytest", "tests/integration", "-v", "--tb=short"],
    #     "Integration tests"
    # )
    
    # 4. Coverage
    all_passed &= run_command(
        ["uv", "run", "pytest", "tests/unit", "--cov=src/otelms", "--cov-report=term-missing"],
        "Unit tests with coverage"
    )
    
    print("\n" + "=" * 60)
    if all_passed:
        print("ALL TESTS PASSED ✓")
        return 0
    else:
        print("SOME TESTS FAILED ✗")
        return 1


if __name__ == "__main__":
    sys.exit(main())