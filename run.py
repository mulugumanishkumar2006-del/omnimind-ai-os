import os
import sys
import time
import subprocess
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("OmniMindLauncher")

def terminate_process(proc, name):
    """Cleanly terminates a subprocess with timeout and fallback to kill."""
    if proc and proc.poll() is None:
        logger.info(f"Stopping {name} (PID: {proc.pid})...")
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning(f"{name} did not terminate within timeout. Forcing kill...")
                proc.kill()
                proc.wait(timeout=2)
        except Exception as e:
            logger.error(f"Error stopping {name}: {e}")

def run_workspace():
    """Starts both FastAPI backend and Streamlit frontend, monitoring their lifecycles."""
    logger.info("[*] Initializing OmniMind AI OS Platform...")
    logger.info("-> Backend API & HTML Workspace: http://127.0.0.1:8000")
    logger.info("-> Interactive Documentation:    http://127.0.0.1:8000/docs")
    logger.info("-> Streamlit Studio Client:       http://127.0.0.1:8501")
    logger.info("Press Ctrl+C to terminate both services.\n")

    env = os.environ.copy()
    if "API_BASE_URL" not in env:
        env["API_BASE_URL"] = "http://127.0.0.1:8000/api/v1"

    backend_cmd = [
        sys.executable, "-m", "uvicorn",
        "backend.app.main:app",
        "--host", "127.0.0.1",
        "--port", "8000"
    ]

    frontend_cmd = [
        sys.executable, "-m", "streamlit",
        "run", "frontend/app.py",
        "--server.port=8501",
        "--server.address=127.0.0.1",
        "--server.headless=true"
    ]

    backend_proc = None
    frontend_proc = None

    try:
        backend_proc = subprocess.Popen(backend_cmd, env=env)
        time.sleep(1)
        if backend_proc.poll() is not None:
            logger.error(f"Backend failed to start immediately (exit code: {backend_proc.returncode}).")
            sys.exit(backend_proc.returncode or 1)

        frontend_proc = subprocess.Popen(frontend_cmd, env=env)

        while True:
            time.sleep(0.5)
            backend_code = backend_proc.poll()
            frontend_code = frontend_proc.poll()

            if backend_code is not None:
                logger.error(f"Backend process terminated unexpectedly with exit code {backend_code}.")
                terminate_process(frontend_proc, "Frontend")
                sys.exit(backend_code if backend_code != 0 else 1)

            if frontend_code is not None:
                logger.error(f"Frontend process terminated unexpectedly with exit code {frontend_code}.")
                terminate_process(backend_proc, "Backend")
                sys.exit(frontend_code if frontend_code != 0 else 1)

    except KeyboardInterrupt:
        logger.info("\nShutdown signal received (Ctrl+C). Terminating OmniMind AI OS...")
    finally:
        terminate_process(frontend_proc, "Frontend")
        terminate_process(backend_proc, "Backend")
        logger.info("OmniMind AI OS stopped cleanly. Goodbye!")

if __name__ == "__main__":
    run_workspace()
