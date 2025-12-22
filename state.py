# state.py
"""
Shared in-memory state for background processing jobs.

This module exposes:
  - `JobRecord`: minimal metadata about a submitted job (owner, system ID, paths).
  - `process_output`: a mapping of job_id -> list of progress/log lines (for SSE or polling).
  - `jobs`: a mapping of job_id -> JobRecord (for quick lookup and lifecycle management).

Notes
-----
- This is intentionally lightweight and framework-agnostic; the web layer (Flask, FastAPI,
  etc.) should *own* concurrency concerns. If multiple threads/processes will mutate these
  structures, wrap access with appropriate locks (e.g., `threading.RLock`) or move to a
  process-safe store (Redis, database, etc.).
- `process_output` is an append-only log for each job; consumers can stream or poll and
  render these lines to users.
"""

from typing import Dict, List
from dataclasses import dataclass
from pathlib import Path


@dataclass
class JobRecord:
    """
    Minimal metadata for a background job.

    Attributes
    ----------
    owner : str
        Authenticated username or principal who owns the job.
    system_id : int
        Numeric identifier for the target system/context being processed.
    job_dir : Path
        Filesystem directory dedicated to this job (e.g., uploads, artifacts).
    json_path : Path
        Path to the primary JSON result file produced by the worker.
    """
    owner: str
    system_id: int
    job_dir: Path
    json_path: Path


# -----------------------------------------------------------------------------
# Global in-memory registries
# -----------------------------------------------------------------------------

# Maps each job_id to its incremental progress/output lines.
# Example usage:
#   process_output[job_id] = []
#   process_output[job_id].append("[INFO] Starting...")
#
# Consider replacing `List[str]` with `collections.deque[str]` and a maxlen
# if we want to bound memory for long-running jobs.
process_output: Dict[str, List[str]] = {}

# Tracks active jobs by their job_id, allowing quick lookups for ownership,
# filesystem locations, and result paths during and after processing.
jobs: Dict[str, JobRecord] = {}
