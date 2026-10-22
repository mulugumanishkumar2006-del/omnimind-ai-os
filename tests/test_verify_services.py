import sys
import subprocess
import pytest

def test_verify_services_re_raises_on_failure():
    """Verify that verify_services.py fails with a nonzero exit code when a test assertion fails."""
    # Run a test harness in a subprocess that simulates a failure in verify_services
    code = """
import asyncio
import verify_services

# Deliberately mock execute_llm_call to return success = False
async def mock_failing_llm(*args, **kwargs):
    return {"success": False, "output": "simulated failure"}

verify_services.execute_llm_call = mock_failing_llm

try:
    asyncio.run(verify_services.run_tests())
except Exception:
    import sys
    sys.exit(42)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True
    )
    # The script should have raised and exited with code 42 (nonzero)
    assert result.returncode == 42
    assert "System Verification Failure" in result.stderr or "System Verification Failure" in result.stdout

def test_verify_services_normal_execution():
    """Verify verify_services.py runs and completes without uncaught runtime errors."""
    result = subprocess.run(
        [sys.executable, "verify_services.py"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    assert "All programmatic system components verified successfully!" in result.stdout or "All programmatic system components verified successfully!" in result.stderr
