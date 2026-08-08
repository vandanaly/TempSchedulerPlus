import os
from pathlib import Path
from threading import Event, Lock, Thread
import time

import cold_pipeline
import supabase_backend as cloud_backend
import prediction
import scheduler
from fastapi import FastAPI
import uvicorn

app = FastAPI(title="TempSched+ API")
_runner_thread: Thread | None = None
_runner_lock = Lock()
_stop_event = Event()

def run_service(delay_seconds: int = 10):
    print("TempSched+ started")
    while not _stop_event.is_set():
        scan_cycle = cold_pipeline.process_files()
        actions = scheduler.schedule()
        current_temp = prediction.current_temperature(scheduler.snapshot()["temperature_store"])
        print("Scan/compression cycle:", scan_cycle)
        print("Scheduling actions:", actions)
        print("Current temperature:", current_temp)
        _stop_event.wait(delay_seconds)

def _start_background_service(delay_seconds: int = 10):
    global _runner_thread
    with _runner_lock:
        if _runner_thread and _runner_thread.is_alive():
            return
        _stop_event.clear()
        _runner_thread = Thread(target=run_service, kwargs={"delay_seconds": delay_seconds}, daemon=True)
        _runner_thread.start()

@app.on_event("startup")
def _on_startup():
    _start_background_service()

@app.on_event("shutdown")
def _on_shutdown():
    _stop_event.set()

@app.get("/files")
def get_files_api():
    docs = cloud_backend.list_metadata()
    if docs:
        return docs
    recent = cold_pipeline.get_pipeline_stats().get("recent", [])
    return [
        {
            "name": Path(item.get("original_path", "")).name,
            "size": int(item.get("compressed_size", item.get("size", 0))),
            "tier": item.get("decision", "cold"),
        }
        for item in recent
    ]

if __name__ == "__main__":
    # Dynamically pull PORT for cloud deployment (Render, Heroku, etc.)
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
