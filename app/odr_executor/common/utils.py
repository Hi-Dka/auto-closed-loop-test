import os
from pathlib import Path
from app.odr_executor.core.logger import base_log, TaskLoggerAdapter

log = TaskLoggerAdapter(base_log, {"tag": "Utils"})


def ensure_fifo(fifo_path: str) -> None:
    fifo = Path(fifo_path)

    if not fifo.exists():
        try:
            log.info(f"Creating FIFO at {fifo_path}...")
            fifo.parent.mkdir(parents=True, exist_ok=True)
            os.mkfifo(str(fifo))
        except OSError as e:
            log.error(f"Error creating FIFO at {fifo_path}: {e}")
            raise RuntimeError(f"Could not create FIFO: {e}") from e
    else:
        if not fifo.is_fifo():
            log.error(f"Path {fifo_path} exists but is NOT a FIFO")
            raise TypeError(f"{fifo_path} is not a FIFO")

        log.info(f"FIFO already exists at {fifo_path}")

    if not os.access(str(fifo), os.R_OK | os.W_OK):
        log.error(f"FIFO at {fifo_path} is not accessible for R/W")
        raise PermissionError(f"Insufficient permissions for {fifo_path}")
