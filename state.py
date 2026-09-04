import json
import time
from pathlib import Path

STEP_ORDER = ["script", "tts", "render", "thumbnail", "upload", "youtube"]

class RunState:
    def __init__(self, run_id, base_dir):
        self.run_id = run_id
        self.dir = Path(base_dir) / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.dir / "state.json"
        self.data = self._load()
    def _load(self):
        if self.state_path.exists():
            with open(self.state_path) as f:
                return json.load(f)
        return {"run_id": self.run_id, "created_at": time.time(), "updated_at": time.time(),
                "steps": {name: {"status": "pending", "attempts": 0, "error": None} for name in STEP_ORDER},
                "artifacts": {}}
    def save(self):
        self.data["updated_at"] = time.time()
        tmp = self.state_path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=2, default=str)
        tmp.replace(self.state_path)
    def is_done(self, step):
        return self.data["steps"][step]["status"] == "completed"
    def mark_running(self, step):
        self.data["steps"][step]["status"] = "running"
        self.data["steps"][step]["attempts"] += 1
        self.save()
    def mark_completed(self, step, artifact=None):
        self.data["steps"][step]["status"] = "completed"
        self.data["steps"][step]["error"] = None
        if artifact is not None:
            self.data["artifacts"][step] = artifact
        self.save()
    def mark_failed(self, step, error):
        self.data["steps"][step]["status"] = "failed"
        self.data["steps"][step]["error"] = str(error)
        self.save()
    def get_artifact(self, step):
        return self.data["artifacts"].get(step)
    def first_failed_step(self):
        for step in STEP_ORDER:
            if self.data["steps"][step]["status"] == "failed":
                return step
        return None
