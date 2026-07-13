from __future__ import annotations

import os
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="luerjia-tests-"))
os.environ.setdefault("LIGHTWEIGHT_ANALYSIS", "true")
os.environ.setdefault("BROWSER_HEADLESS", "true")
