import os
from fastapi import FastAPI
from . import db, routes

app = FastAPI(title="TempSchedPlus Backend")
app.include_router(routes.router, prefix="/api")

@app.on_event("startup")
def startup():
    # Create DB tables
    db.Base.metadata.create_all(bind=db.engine)

@app.get("/")
def root():
    return {"service": "TempSchedPlus Backend"}

def run():
    import uvicorn
    # Dynamically fetch the port for cloud deployment (e.g., Render)
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=False)

if __name__ == "__main__":
    run()
