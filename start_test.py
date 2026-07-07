"""Start server for testing — no reload, correct CWD."""
import os, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import uvicorn
uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=False)
