import sys
import subprocess

def run_workspace():
    print("[*] Initializing OmniMind AI OS Platform...")
    print("-> Starting Single-Port Server on http://127.0.0.1:8000")
    print("Press Ctrl+C to terminate the process.")
    
    cmd = [
        sys.executable, "-m", "uvicorn", 
        "backend.app.main:app", 
        "--host", "127.0.0.1", 
        "--port", "8000"
    ]
    
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\nOmniMind AI OS stopped. Goodbye!")

if __name__ == "__main__":
    run_workspace()
