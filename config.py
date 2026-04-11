import os
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=dotenv_path)

BOT_TOKEN = os.getenv('BOT_TOKEN', '')
DATABASE_URL = os.getenv('DATABASE_URL', '')  # postgresql://user:pass@host:5432/dbname
