import os
from pathlib import Path

# Allow routing to a persistent disk for Render/Cloud deployment
_persistent_path = os.getenv("TEMPSCHED_PERSISTENT_DISK", "").strip()
BASE_DIR = Path(_persistent_path).resolve() if _persistent_path else Path(__file__).resolve().parent

def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        os.environ[key] = value

_load_env_file(BASE_DIR / ".env")

def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default

DEVICE = BASE_DIR / "device"
EDGE = BASE_DIR / "edge"
CLOUD = BASE_DIR / "cloud"
COMPRESSED = BASE_DIR / "compressed"
ENCRYPTED = BASE_DIR / "encrypted"
LOGS = BASE_DIR / "logs"
MODELS = BASE_DIR / "models"
UPLOADS = BASE_DIR / "uploads"

# --- AUTO PARAMETER TUNING & ADAPTIVE SCHEDULING ---
# Instead of hardcoded limits, we allow the system to tune these dynamically.
HOT_THRESHOLD_BASE = 600
WARM_THRESHOLD_BASE = 400
AUTO_TUNE_ENABLED = os.getenv("TEMPSCHED_AUTO_TUNE", "1").strip().lower() in {"1", "true", "yes", "on"}

# Newton-style hotness cooling parameters.
TEMP_AMBIENT = float(os.getenv("TEMPSCHED_TEMP_AMBIENT", "350.0"))
TEMP_DECAY_RATE_PER_HOUR = float(os.getenv("TEMPSCHED_TEMP_DECAY_RATE_PER_HOUR", "0.25"))

SCAN_DEFAULT_PATHS = [Path.home() / "Documents", Path.home() / "Downloads"]
SCAN_PATHS_ENV = os.getenv("TEMPSCHED_SCAN_PATHS", "")
SCAN_PATHS = [Path(part.strip()) for part in SCAN_PATHS_ENV.split(";") if part.strip()] or SCAN_DEFAULT_PATHS
SCAN_MAX_FILES = int(os.getenv("TEMPSCHED_SCAN_MAX_FILES", "1500"))
SCHEDULER_MAX_FILES = int(os.getenv("TEMPSCHED_SCHEDULER_MAX_FILES", "500"))
SCAN_MIN_SIZE_BYTES = int(os.getenv("TEMPSCHED_SCAN_MIN_SIZE_BYTES", "4096"))
SCAN_MAX_DEPTH = int(os.getenv("TEMPSCHED_SCAN_MAX_DEPTH", "4"))
SCAN_MAX_STAGE_BYTES = int(os.getenv("TEMPSCHED_SCAN_MAX_STAGE_BYTES", str(500 * 1024 * 1024)))

SKIP_DIRS = {
    ".git", ".venv", "node_modules", "__pycache__", ".pytest_cache",
    ".vscode", ".idea", "dist", "build", ".env", ".git-lfs"
}

# Firebase Config
FIREBASE_KEY_FILE = os.getenv("FIREBASE_KEY_FILE", "firebase_key.json")
FIREBASE_KEY_PATH = Path(FIREBASE_KEY_FILE) if Path(FIREBASE_KEY_FILE).is_absolute() else BASE_DIR / FIREBASE_KEY_FILE
FIREBASE_STORAGE_BUCKET = os.getenv("FIREBASE_STORAGE_BUCKET", "")
FIREBASE_METADATA_COLLECTION = os.getenv("FIREBASE_METADATA_COLLECTION", "files")

# Supabase Config
SUPABASE_URL = _env("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = _env("SUPABASE_SERVICE_ROLE_KEY", "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY")
SUPABASE_BUCKET_NAME = _env("SUPABASE_BUCKET_NAME", default="cold-storage")
SUPABASE_BUCKET_PREFIX = os.getenv("SUPABASE_BUCKET_PREFIX", "cold_data").strip() or "cold_data"

ENABLE_UPLOAD_ENCRYPTION = os.getenv("TEMPSCHED_ENABLE_UPLOAD_ENCRYPTION", "1").strip().lower() in {"1", "true", "yes", "on"}
DELETE_AFTER_UPLOAD = os.getenv("TEMPSCHED_DELETE_AFTER_UPLOAD", "0").strip().lower() in {"1", "true", "yes", "on"}

SKIP_EXTENSIONS = {
    ".exe", ".dll", ".sys", ".msi", ".bat", ".cmd", ".ps1", ".lnk",
    ".tmp", ".cache", ".log", ".pid", ".lock", ".sock",
    ".iso", ".img", ".dmg", ".tar", ".zip",
}

ALL_DIRECTORIES = [DEVICE, EDGE, CLOUD, COMPRESSED, ENCRYPTED, LOGS, MODELS, UPLOADS]

def ensure_directories():
    for directory in ALL_DIRECTORIES:
        directory.mkdir(parents=True, exist_ok=True)

ensure_directories()
