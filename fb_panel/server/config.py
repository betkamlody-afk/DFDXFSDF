"""Server configuration constants"""

from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
KEYS_FILE = DATA_DIR / "keys.json"
LOGS_FILE = DATA_DIR / "logs.json"

DATA_DIR.mkdir(exist_ok=True)

# Rate limiting
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 120  # requests per window

# Server
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080
PORT_RANGE = 100

# Engine
try:
    from engine import CheckerEngine, EngineConfig, HAS_SELENIUM, HAS_UC
    ENGINE_AVAILABLE = HAS_SELENIUM
except ImportError:
    ENGINE_AVAILABLE = False
    CheckerEngine = None
    EngineConfig = None
    HAS_UC = False
