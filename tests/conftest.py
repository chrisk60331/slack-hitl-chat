from __future__ import annotations

import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Minimal environment for module imports during tests
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("TABLE_NAME", "agentcore-approval-logs")
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("LOCAL_DEV", "true")


