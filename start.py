import os
import subprocess
import sys

port = os.environ.get("PORT", "8080")
cmd = [
    "gunicorn",
    "flask_bridge_final:app",
    "--bind", f"0.0.0.0:{port}",
    "--workers", "2",
    "--timeout", "300",
]
sys.exit(subprocess.call(cmd))
