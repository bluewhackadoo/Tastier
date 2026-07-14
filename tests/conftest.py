import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from app.config import ENV_PATH as _ENV_PATH
load_dotenv(_ENV_PATH)
