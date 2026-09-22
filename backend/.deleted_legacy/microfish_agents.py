"""
MicroFish Agent System - Replacement for oasis-ai
NO camel-ai, NO oasis-ai dependencies - uses local LLM endpoint directly
"""

import json
import os
import csv
import asyncio
import random
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from llm_client import get_llm_client, LocalLLMClient


# ============================================================
# ActionType - Same as oasis for compatibility
# ============================================================

class ActionType(str, Enum):
    """Action types for Twitter and Reddit"""
    # Common actions
    DO_NOTHING = "do_nothing"
    FOLLOW = "follow"
    MUTE = "mute"
    
    # Twitter actions
    CREATE_POST = "create_post"
    LIKE_POST = "like_post"
    REPOST = "repost"
    QUOTE_POST = "quote_post"
    
    # Reddit actions
    DISLIKE_POST = "dislike_post"
    CREATE_COMMENT = "create_comment"
    LIKE_COMMENT = "like_comment"
    DISLIKE_COMMENT = "dislike_comment"
    SEARCH_POSTS = "search_posts"
    SEARCH_USER = "search_user"
    TREND = "trend"
    REFRESH = "refresh"
    
    # Interview action (manual only)
    INTERVIEW = "interview"


# ============================================================
# Action Classes - Same interface as oasis
# ============================================================

@dataclass
class LLMAction:
    """Action determined by LLM"""
    action_type: ActionType
    action_args: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ManualAction:
    """Manual action (e.g., interview)"""
    action_type: ActionType
    action_args: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# Agent Class - Represents a single agent
# ============================================================

@dataclass
class AgentProfile:
    """Agent profile/identity"""
    agent_id: int
    name: str
    bio: str
    personality_traits: str
    background: str
    posting_style: str
    active_hours: List[int] = field(default_factory=lambda: list(range(8, 23)))
    activity_level: float = 0.5
    entity_name: str = ""  # Optional real entity name from config


class Agent:
    """Single AI agent that makes decisions via LLM"""
    
    def __init__(
        self,
        profile: AgentProfile,
        available_actions: List[ActionType],
        llm_client: LocalLLMClient = None
    ):
        self.profile = profile
        self.available_actions = available_actions
        self.llm_client = llm_client or get_llm_client()
        
        # Memory
        self.memory: List[Dict[str, Any]] = []  # Recent observations
        self.posts: List[Dict[str, Any]] = []  # Posts made by this agent
        self.likes: List[int] = []  # Post IDs liked
        self.follows: List[int] = []  # Agent IDs followed
    
    @property
    def agent_id(self) -> int:
        return self.profile.agent_id
    
    @property
    def name(self) -> str:
        return self.profile.name
    
    def add_to_memory(self, observation: Dict[str, Any]):
        """Add observation to memory"""
        self.memory.append(observation)
        # Keep only last 50 items
        if len(self.memory) > 50:
            self.memory = self.memory[-50:]
    
    async def decide_action(
        self,
        context: Dict[str, Any],
        temperature: float = 0.7
    ) -> LLMAction:
        """
        Use LLM to decide what action to take
        
        Args:
            context: Current environment context (trending posts, recent activity, etc.)
            temperature: LLM temperature for decision making
            
        Returns:
            LLMAction with action type and arguments
        """
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(context)
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.llm_client.chat(messages, temperature=temperature, max_tokens=2048)
            )
            
            # Parse the response to extract action
            action = self._parse_action_response(response)
            return action
            
        except Exception as e:
            # Fallback: do nothing
            return LLMAction(action_type=ActionType.DO_NOTHING)
    
    def _build_system_prompt(self) -> str:
        """Build system prompt with agent identity"""
        return f"""You are {self.profile.name}, an AI agent simulating a social media user.

Your Profile:
- Bio: {self.profile.bio}
- Personality: {self.profile.personality_traits}
- Background: {self.profile.background}
- Posting Style: {self.profile.posting_style}

Available Actions:
{self._format_available_actions()}

You must choose ONE action from the available actions above.
Respond in JSON format with this exact structure:
{{
    "action": "<action_name>",
    "args": {{ ... action-specific arguments ... }}
}}

Be authentic to your character. Don't explain your reasoning - just output the JSON."""
    
    def _format_available_actions(self) -> str:
        """Format available actions for prompt"""
        action_descriptions = {
            ActionType.CREATE_POST: "CREATE_POST - Create a new post. Args: {content: string}",
            ActionType.LIKE_POST: "LIKE_POST - Like a post. Args: {post_id: int}",
            ActionType.REPOST: "REPOST - Repost existing post. Args: {post_id: int}",
            ActionType.QUOTE_POST: "QUOTE_POST - Quote post with comment. Args: {post_id: int, content: string}",
            ActionType.FOLLOW: "FOLLOW - Follow another user. Args: {follow_id: int}",
            ActionType.DO_NOTHING: "DO_NOTHING - Skip this turn",
            ActionType.CREATE_COMMENT: "CREATE_COMMENT - Create a comment. Args: {post_id: int, content: string}",
            ActionType.LIKE_COMMENT: "LIKE_COMMENT - Like a comment. Args: {comment_id: int}",
            ActionType.SEARCH_POSTS: "SEARCH_POSTS - Search for posts. Args: {query: string}",
        }
        
        lines = []
        for action in self.available_actions:
            if action in action_descriptions:
                lines.append(f"- {action_descriptions[action]}")
        return "\n".join(lines)
    
    def _build_user_prompt(self, context: Dict[str, Any]) -> str:
        """Build user prompt with current context"""
        parts = []
        
        # Current time context
        hour = context.get("simulated_hour", 12)
        parts.append(f"Current simulated time: Hour {hour} of the day.")
        
        # Recent trending posts
        trending = context.get("trending_posts", [])
        if trending:
            parts.append("\nTrending Posts:")
            for i, post in enumerate(trending[:5], 1):
                parts.append(f"{i}. [Post #{post.get('id', i)}] by @{post.get('author', 'unknown')}: \"{post.get('content', '')[:100]}\"")
        
        # Recent memory
        if self.memory:
            parts.append("\nYour recent observations:")
            for obs in self.memory[-10:]:
                if obs.get("type") == "post":
                    parts.append(f"- Saw post by @{obs.get('author')}: {obs.get('content', '')[:80]}")
                elif obs.get("type") == "like":
                    parts.append(f"- Your post got a like!")
                elif obs.get("type") == "follow":
                    parts.append(f"- You gained a new follower!")
        
        # Agent's own recent posts
        if self.posts:
            parts.append("\nYour recent posts:")
            for post in self.posts[-3:]:
                parts.append(f"- \"{post.get('content', '')[:60]}\"")
        
        parts.append("\nWhat action will you take next? Choose ONE action from your available actions.")
        
        return "\n".join(parts)
    
    def _parse_action_response(self, response: str) -> LLMAction:
        """Parse LLM response into action"""
        try:
            # Try to extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                data = json.loads(json_match.group())
                action_name = data.get("action", "").upper()
                
                # Find matching ActionType
                for action_type in ActionType:
                    if action_type.value.upper() == action_name or action_type.name.upper() == action_name:
                        if action_type in self.available_actions:
                            return LLMAction(
                                action_type=action_type,
                                action_args=data.get("args", {})
                            )
        except Exception:
            pass
        
        # Fallback
        return LLMAction(action_type=ActionType.DO_NOTHING)


# ============================================================
# AgentGraph - Manages collection of agents
# ============================================================

class AgentGraph:
    """Manages a graph of agents and their relationships"""
    
    def __init__(self):
        self.agents: Dict[int, Agent] = {}
        self.relationships: Dict[Tuple[int, int], str] = {}  # (agent1, agent2) -> relationship type
    
    def add_agent(self, agent_id: int, agent: Agent):
        """Add agent to graph"""
        self.agents[agent_id] = agent
    
    def get_agent(self, agent_id: int) -> Agent:
        """Get agent by ID"""
        if agent_id not in self.agents:
            raise KeyError(f"Agent {agent_id} not found")
        return self.agents[agent_id]
    
    def get_agents(self) -> List[Tuple[int, Agent]]:
        """Get all agents as (id, agent) pairs"""
        return list(self.agents.items())
    
    def add_relationship(self, agent1_id: int, agent2_id: int, relationship: str = "follows"):
        """Add relationship between agents"""
        self.relationships[(agent1_id, agent2_id)] = relationship
    
    def get_followers(self, agent_id: int) -> List[int]:
        """Get list of agent IDs that follow this agent"""
        return [a1 for (a1, a2), rel in self.relationships.items() 
                if a2 == agent_id and rel == "follows"]
    
    def get_following(self, agent_id: int) -> List[int]:
        """Get list of agent IDs this agent follows"""
        return [a2 for (a1, a2), rel in self.relationships.items() 
                if a1 == agent_id and rel == "follows"]


# ============================================================
# Agent Graph Generation Functions (replaces oasis functions)
# ============================================================

async def generate_twitter_agent_graph(
    profile_path: str,
    model: Any = None,  # Kept for API compatibility but unused
    available_actions: List[ActionType] = None
) -> AgentGraph:
    """
    Generate agent graph from Twitter profiles CSV
    
    Args:
        profile_path: Path to CSV file with agent profiles
        model: Unused (kept for API compatibility)
        available_actions: List of allowed actions
        
    Returns:
        AgentGraph with all agents
    """
    if available_actions is None:
        available_actions = [
            ActionType.CREATE_POST,
            ActionType.LIKE_POST,
            ActionType.REPOST,
            ActionType.FOLLOW,
            ActionType.DO_NOTHING,
            ActionType.QUOTE_POST,
        ]
    
    agent_graph = AgentGraph()
    llm_client = get_llm_client()
    
    # Read profiles from CSV
    if not os.path.exists(profile_path):
        raise FileNotFoundError(f"Profile file not found: {profile_path}")
    
    with open(profile_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            agent_id = int(row.get('agent_id', 0))
            
            profile = AgentProfile(
                agent_id=agent_id,
                name=row.get('name', f'Agent_{agent_id}'),
                bio=row.get('bio', ''),
                personality_traits=row.get('personality', ''),
                background=row.get('background', ''),
                posting_style=row.get('posting_style', ''),
                active_hours=json.loads(row.get('active_hours', '[8,9,10,11,12,13,14,15,16,17,18,19,20,21,22]')),
                activity_level=float(row.get('activity_level', '0.5')),
                entity_name=row.get('entity_name', '')
            )
            
            agent = Agent(profile=profile, available_actions=available_actions, llm_client=llm_client)
            agent_graph.add_agent(agent_id, agent)
    
    return agent_graph


async def generate_reddit_agent_graph(
    profile_path: str,
    model: Any = None,
    available_actions: List[ActionType] = None
) -> AgentGraph:
    """
    Generate agent graph from Reddit profiles CSV
    
    Args:
        profile_path: Path to CSV file with agent profiles
        model: Unused (kept for API compatibility)
        available_actions: List of allowed actions
        
    Returns:
        AgentGraph with all agents
    """
    if available_actions is None:
        available_actions = [
            ActionType.LIKE_POST,
            ActionType.DISLIKE_POST,
            ActionType.CREATE_POST,
            ActionType.CREATE_COMMENT,
            ActionType.LIKE_COMMENT,
            ActionType.DISLIKE_COMMENT,
            ActionType.SEARCH_POSTS,
            ActionType.SEARCH_USER,
            ActionType.TREND,
            ActionType.REFRESH,
            ActionType.DO_NOTHING,
            ActionType.FOLLOW,
            ActionType.MUTE,
        ]
    
    return await generate_twitter_agent_graph(
        profile_path=profile_path,
        model=model,
        available_actions=available_actions
    )
