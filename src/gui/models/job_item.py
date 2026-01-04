from enum import Enum, auto
from dataclasses import dataclass, field
from typing import List, Optional

class JobStatus(Enum):
    PENDING = auto()
    MESHING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    ERROR = auto()
    SKIPPED = auto()
    STOPPED = auto()

@dataclass
class JobItem:
    id: str
    name: str
    step_path: str
    status: JobStatus = JobStatus.PENDING
    progress: int = 0
    status_text: str = "Pending"
    vtk_path: Optional[str] = None
    feb_path: Optional[str] = None
    result_path: Optional[str] = None
    error_message: Optional[str] = None
    log_lines: List[str] = field(default_factory=list)
    
    def display_status(self) -> str:
        status_map = {
            JobStatus.PENDING: "Pending",
            JobStatus.MESHING: "Meshing...",
            JobStatus.RUNNING: "Analyzing...",
            JobStatus.COMPLETED: "Completed",
            JobStatus.ERROR: "Error",
            JobStatus.SKIPPED: "Skipped",
            JobStatus.STOPPED: "Stopped"
        }
        return status_map.get(self.status, "Unknown")
