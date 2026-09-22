"""
Configuration Management
Loads configuration from .env file in project root directory
"""

import os
from dotenv import load_dotenv

# Load .env file from project root
# Path: MicroFish/.env (relative to backend/app/config.py)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    # If root directory has no .env, try loading from environment (for production)
    load_dotenv(override=True)


class Config:
    """Flask configuration class"""
    
    # Flask Configuration
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mirofish-secret-key')
    DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    
    # JSON Configuration - Disable ASCII escaping to allow Chinese characters to display directly (instead of \uXXXX format)
    JSON_AS_ASCII = False
    
    # LLM Configuration (unified OpenAI format)
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')
    
    # Zep Configuration
    ZEP_API_KEY = os.environ.get('ZEP_API_KEY')
    
    # File Upload Configuration
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}
    
    # Text Processing Configuration
    DEFAULT_CHUNK_SIZE = 500  # Default chunk size
    DEFAULT_CHUNK_OVERLAP = 50  # Default overlap size
    
    # Simulation Configuration
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')

    # Domain packs define the action space for each simulation. The engine is
    # domain-agnostic: verbs come from the pack, not from this config.
    DOMAINS_DIR = os.path.join(os.path.dirname(__file__), '../domains')
    DEFAULT_DOMAIN = os.environ.get('DEFAULT_DOMAIN', 'social')
    
    # Report Agent Configuration
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))
    
    @classmethod
    def validate(cls):
        """Validate required configuration"""
        errors = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY not configured")
        # ZEP_API_KEY is optional - do not require it
        return errors


