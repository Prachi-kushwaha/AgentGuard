import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
TAVILY_API_KEY = os.getenv('TAVILY_API_KEY', '')
MAX_SOURCES = int(os.getenv('MAX_SOURCES', '6'))
SIMULATE_TRANSIENT_SEARCH = os.getenv('SIMULATE_TRANSIENT_SEARCH', '0') == '1'
