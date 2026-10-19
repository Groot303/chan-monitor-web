"""Keep runtime delivery state outside the git checkout."""
from pathlib import Path
import os
import tempfile


def notification_state_path(repo, data_dir):
    target = Path(data_dir) / "state" / "notified.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    legacy = Path(repo) / "state" / "notified.json"
    if not target.exists() and legacy.exists():
        fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".notify-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(legacy.read_bytes())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return target
