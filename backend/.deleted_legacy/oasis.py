"""
OASIS Compatibility Layer
Maps oasis-ai API to our local implementation
NO external dependencies - uses microfish_agents and microfish_env
"""

# Re-export everything from our modules
from microfish_agents import (
    ActionType,
    LLMAction,
    ManualAction,
    Agent,
    AgentProfile,
    AgentGraph,
    generate_twitter_agent_graph,
    generate_reddit_agent_graph,
)

from microfish_env import (
    make,
    MicroFishEnv,
    DefaultPlatformType,
)

# Module version for compatibility
__version__ = "1.0.0-microfish"
