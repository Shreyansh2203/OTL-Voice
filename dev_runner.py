import os
import subprocess
import sys
import threading

# Windows-specific flag to isolate processes from the main terminal's Ctrl+C signals
# This prevents Uvicorn's hot-reload from crashing the entire script.
CREATE_NEW_PROCESS_GROUP = 0x00000200 if os.name == 'nt' else 0

class Color:
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    RESET = '\033[0m'

def pipe_output(pipe, prefix, color):
    """Reads from a process pipe and prints to the main terminal with a colored prefix."""
    try:
        for line in iter(pipe.readline, b''):
            if not line:
                break
            # Decode safely, strip trailing newlines, and print with prefix
            decoded = line.decode('utf-8', errors='replace').rstrip('\r\n')
            print(f"{color}{prefix}{Color.RESET} {decoded}", flush=True)
    except Exception:
        pass

def main():
    print("===================================================")
    print("Starting OTL Voice Assistant (Unified Orchestrator)")
    print("===================================================\n")

    # Prepare environment variables
    env = os.environ.copy()
    env['UV_PROJECT_ENVIRONMENT'] = '.venv2'
    
    # 1. Start the Backend
    # Using raw commands to bypass .cmd wrappers
    backend_cmd = ['uv', 'run', 'uvicorn', 'backend.main:app', '--reload', '--reload-include', '.env']
    backend_proc = subprocess.Popen(
        backend_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=CREATE_NEW_PROCESS_GROUP,
        env=env
    )

    # 2. Start the Frontend
    # shell=True is used to safely resolve the 'pnpm' executable path on Windows
    frontend_cmd = 'pnpm run dev'
    frontend_proc = subprocess.Popen(
        frontend_cmd,
        cwd='frontend',
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=CREATE_NEW_PROCESS_GROUP,
        shell=True,
        env=env
    )

    # 3. Attach output streaming threads
    threading.Thread(target=pipe_output, args=(backend_proc.stdout, '[BACKEND] ', Color.BLUE), daemon=True).start()
    threading.Thread(target=pipe_output, args=(frontend_proc.stdout, '[FRONTEND]', Color.GREEN), daemon=True).start()

    try:
        # Keep the main orchestrator alive while children run
        backend_proc.wait()
        frontend_proc.wait()
    except KeyboardInterrupt:
        print("\nShutting down services gracefully...")
        # Cleanly terminate the isolated process groups
        backend_proc.terminate()
        frontend_proc.terminate()
        sys.exit(0)

if __name__ == '__main__':
    main()
