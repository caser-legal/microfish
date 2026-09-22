"""
MicroFish Simulation Environment - Replacement for oasis.make()
NO camel-ai, NO oasis-ai dependencies - uses local LLM endpoint directly
"""

import json
import os
import asyncio
import sqlite3
import random
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from microfish_agents import (
    AgentGraph, Agent, AgentProfile,
    ActionType, LLMAction, ManualAction,
    generate_twitter_agent_graph, generate_reddit_agent_graph
)
from llm_client import get_llm_client


# ============================================================
# DefaultPlatformType - Same as oasis for compatibility
# ============================================================

class DefaultPlatformType:
    TWITTER = "twitter"
    REDDIT = "reddit"


# ============================================================
# Mock Post/Content Database Tables
# ============================================================

TWITTER_TABLES = """
-- Users table
CREATE TABLE IF NOT EXISTS user (
    user_id INTEGER PRIMARY KEY,
    agent_id INTEGER,
    name TEXT,
    user_name TEXT,
    bio TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Posts table
CREATE TABLE IF NOT EXISTS post (
    post_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    content TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    original_post_id INTEGER,  -- For reposts/quotes
    quoted_content TEXT,       -- For quote posts
    FOREIGN KEY (user_id) REFERENCES user(user_id)
);

-- Likes table
CREATE TABLE IF NOT EXISTS like (
    like_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    post_id INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES user(user_id),
    FOREIGN KEY (post_id) REFERENCES post(post_id)
);

-- Follows table
CREATE TABLE IF NOT EXISTS follow (
    follower_id INTEGER,
    following_id INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (follower_id, following_id),
    FOREIGN KEY (follower_id) REFERENCES user(user_id),
    FOREIGN KEY (following_id) REFERENCES user(user_id)
);

-- Trace table for action logging (compatible with oasis format)
CREATE TABLE IF NOT EXISTS trace (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT,
    info TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES user(user_id)
);
"""

REDDIT_TABLES = """
-- Same structure as Twitter plus Reddit-specific tables
""" + TWITTER_TABLES + """

-- Comments table (Reddit-specific)
CREATE TABLE IF NOT EXISTS comment (
    comment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    post_id INTEGER,
    content TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    parent_comment_id INTEGER,
    FOREIGN KEY (user_id) REFERENCES user(user_id),
    FOREIGN KEY (post_id) REFERENCES post(post_id)
);

-- Upvotes/Downvotes table
CREATE TABLE IF NOT EXISTS vote (
    vote_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    post_id INTEGER,
    comment_id INTEGER,
    vote_type INTEGER,  -- 1 = upvote, -1 = downvote
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES user(user_id),
    FOREIGN KEY (post_id) REFERENCES post(post_id),
    FOREIGN KEY (comment_id) REFERENCES comment(comment_id)
);
"""


# ============================================================
# Simulation Environment
# ============================================================

class MicroFishEnv:
    """
    MicroFish simulation environment
    Replaces oasis.make() functionality
    """
    
    def __init__(
        self,
        agent_graph: AgentGraph,
        platform: str = DefaultPlatformType.TWITTER,
        database_path: str = None,
        semaphore: int = 30  # Max concurrent LLM requests
    ):
        self.agent_graph = agent_graph
        self.platform = platform
        self.database_path = database_path or ":memory:"
        self.semaphore = asyncio.Semaphore(semaphore)
        
        self.db_conn: Optional[sqlite3.Connection] = None
        self.simulated_hour = 0
        self.current_round = 0
        
        # Content pools
        self.posts: Dict[int, Dict[str, Any]] = {}  # post_id -> post data
        self.comments: Dict[int, Dict[str, Any]] = {}  # comment_id -> comment data
        
        # Initialize database
        self._init_database()
    
    def _init_database(self):
        """Initialize SQLite database with schema"""
        self.db_conn = sqlite3.connect(self.database_path)
        cursor = self.db_conn.cursor()
        
        # Create tables based on platform
        if self.platform == DefaultPlatformType.TWITTER:
            cursor.executescript(TWITTER_TABLES)
        else:
            cursor.executescript(REDDIT_TABLES)
        
        # Register agents in user table
        for agent_id, agent in self.agent_graph.get_agents():
            cursor.execute("""
                INSERT OR REPLACE INTO user (user_id, agent_id, name, user_name, bio)
                VALUES (?, ?, ?, ?, ?)
            """, (
                agent_id,
                agent_id,
                agent.profile.name,
                agent.profile.name.replace(' ', '_').lower(),
                agent.profile.bio
            ))
        
        self.db_conn.commit()
    
    async def reset(self):
        """Reset environment to initial state"""
        cursor = self.db_conn.cursor()
        
        # Clear existing data but keep users
        cursor.execute("DELETE FROM post")
        cursor.execute("DELETE FROM like")
        cursor.execute("DELETE FROM follow")
        cursor.execute("DELETE FROM trace")
        
        if self.platform == DefaultPlatformType.REDDIT:
            cursor.execute("DELETE FROM comment")
            cursor.execute("DELETE FROM vote")
        
        self.db_conn.commit()
        
        self.simulated_hour = 0
        self.current_round = 0
        self.posts.clear()
        self.comments.clear()
        
        # Reset agent memories
        for _, agent in self.agent_graph.get_agents():
            agent.memory.clear()
            agent.posts.clear()
            agent.likes.clear()
            agent.follows.clear()
    
    async def step(
        self,
        actions: Dict[Agent, Any]
    ) -> Dict[int, Any]:
        """
        Execute one step of simulation
        
        Args:
            actions: Dict mapping agents to their actions (LLMAction or ManualAction)
            
        Returns:
            Dict of results by agent_id
        """
        results = {}
        
        async def process_single_action(agent: Agent, action: Any):
            """Process single agent action with semaphore"""
            async with self.semaphore:
                return await self._execute_action(agent, action)
        
        # Process all actions concurrently (limited by semaphore)
        tasks = [process_single_action(agent, action) 
                 for agent, action in actions.items()]
        
        action_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Map results back to agents
        agents_list = list(actions.keys())
        for i, result in enumerate(action_results):
            agent = agents_list[i]
            if isinstance(result, Exception):
                results[agent.agent_id] = {"success": False, "error": str(result)}
            else:
                results[agent.agent_id] = result
        
        return results
    
    async def _execute_action(
        self,
        agent: Agent,
        action: Any
    ) -> Dict[str, Any]:
        """Execute single agent action"""
        action_type = action.action_type
        action_args = action.action_args if hasattr(action, 'action_args') else {}
        
        cursor = self.db_conn.cursor()
        result = {"success": True, "action": action_type.value}
        
        try:
            if action_type == ActionType.CREATE_POST:
                result = await self._do_create_post(agent, action_args, cursor)
            
            elif action_type == ActionType.LIKE_POST:
                result = await self._do_like_post(agent, action_args, cursor)
            
            elif action_type == ActionType.REPOST:
                result = await self._do_repost(agent, action_args, cursor)
            
            elif action_type == ActionType.QUOTE_POST:
                result = await self._do_quote_post(agent, action_args, cursor)
            
            elif action_type == ActionType.FOLLOW:
                result = await self._do_follow(agent, action_args, cursor)
            
            elif action_type == ActionType.DO_NOTHING:
                result = {"success": True, "action": "do_nothing"}
            
            elif action_type == ActionType.INTERVIEW:
                result = await self._do_interview(agent, action_args, cursor)
            
            # Reddit-specific actions
            elif action_type == ActionType.DISLIKE_POST:
                result = await self._do_dislike_post(agent, action_args, cursor)
            
            elif action_type == ActionType.CREATE_COMMENT:
                result = await self._do_create_comment(agent, action_args, cursor)
            
            elif action_type == ActionType.LIKE_COMMENT:
                result = await self._do_like_comment(agent, action_args, cursor)
            
            elif action_type == ActionType.DISLIKE_COMMENT:
                result = await self._do_dislike_comment(agent, action_args, cursor)
            
            elif action_type == ActionType.SEARCH_POSTS:
                result = await self._do_search_posts(agent, action_args, cursor)
            
            elif action_type == ActionType.SEARCH_USER:
                result = await self._do_search_user(agent, action_args, cursor)
            
            elif action_type == ActionType.TREND:
                result = await self._do_trend(agent, action_args, cursor)
            
            elif action_type == ActionType.REFRESH:
                result = {"success": True, "action": "refresh"}
            
            elif action_type == ActionType.MUTE:
                result = await self._do_mute(agent, action_args, cursor)
            
            # Log action to trace table
            cursor.execute("""
                INSERT INTO trace (user_id, action, info)
                VALUES (?, ?, ?)
            """, (
                agent.agent_id,
                action_type.value,
                json.dumps(result)
            ))
            
            self.db_conn.commit()
            
            # Add to agent's memory
            agent.add_to_memory({
                "type": "action",
                "action": action_type.value,
                "result": result,
                "hour": self.simulated_hour
            })
            
        except Exception as e:
            result = {"success": False, "error": str(e)}
        
        return result
    
    async def _do_create_post(
        self,
        agent: Agent,
        args: Dict[str, Any],
        cursor
    ) -> Dict[str, Any]:
        """Create a new post"""
        content = args.get("content", "")
        
        if not content:
            # Generate content using LLM if not provided
            prompt = f"Write a short social media post (under 280 characters) as {agent.profile.name}. {agent.profile.posting_style}"
            messages = [{"role": "user", "content": prompt}]
            llm_client = get_llm_client()
            content = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: llm_client.chat(messages, temperature=0.8, max_tokens=100)
            )
        
        cursor.execute("""
            INSERT INTO post (user_id, content)
            VALUES (?, ?)
        """, (agent.agent_id, content))
        
        post_id = cursor.lastrowid
        self.posts[post_id] = {
            "id": post_id,
            "author_id": agent.agent_id,
            "author": agent.profile.name,
            "content": content,
            "created_at": datetime.now().isoformat()
        }
        
        agent.posts.append({"id": post_id, "content": content})
        
        # Notify followers
        followers = self.agent_graph.get_followers(agent.agent_id)
        for follower_id in followers:
            try:
                follower = self.agent_graph.get_agent(follower_id)
                follower.add_to_memory({
                    "type": "post",
                    "author": agent.profile.name,
                    "content": content,
                    "post_id": post_id
                })
            except KeyError:
                pass
        
        return {
            "success": True,
            "action": "create_post",
            "post_id": post_id,
            "content": content
        }
    
    async def _do_like_post(
        self,
        agent: Agent,
        args: Dict[str, Any],
        cursor
    ) -> Dict[str, Any]:
        """Like a post"""
        post_id = args.get("post_id")
        
        if not post_id:
            # Pick a random post to like
            if self.posts:
                post_id = random.choice(list(self.posts.keys()))
            else:
                return {"success": False, "error": "No posts available to like"}
        
        cursor.execute("""
            INSERT OR IGNORE INTO like (user_id, post_id)
            VALUES (?, ?)
        """, (agent.agent_id, post_id))
        
        agent.likes.append(post_id)
        
        # Notify post author
        post = self.posts.get(post_id)
        if post:
            try:
                author = self.agent_graph.get_agent(post["author_id"])
                author.add_to_memory({
                    "type": "like",
                    "post_id": post_id,
                    "liked_by": agent.profile.name
                })
            except KeyError:
                pass
        
        return {
            "success": True,
            "action": "like_post",
            "post_id": post_id
        }
    
    async def _do_repost(
        self,
        agent: Agent,
        args: Dict[str, Any],
        cursor
    ) -> Dict[str, Any]:
        """Repost an existing post"""
        post_id = args.get("post_id")
        
        if not post_id or post_id not in self.posts:
            return {"success": False, "error": "Invalid post_id"}
        
        original = self.posts[post_id]
        
        cursor.execute("""
            INSERT INTO post (user_id, content, original_post_id)
            VALUES (?, ?, ?)
        """, (agent.agent_id, original["content"], post_id))
        
        new_post_id = cursor.lastrowid
        self.posts[new_post_id] = {
            "id": new_post_id,
            "author_id": agent.agent_id,
            "author": agent.profile.name,
            "content": original["content"],
            "original_post_id": post_id,
            "created_at": datetime.now().isoformat()
        }
        
        return {
            "success": True,
            "action": "repost",
            "new_post_id": new_post_id,
            "original_post_id": post_id
        }
    
    async def _do_quote_post(
        self,
        agent: Agent,
        args: Dict[str, Any],
        cursor
    ) -> Dict[str, Any]:
        """Quote post with comment"""
        post_id = args.get("post_id")
        content = args.get("content", "")
        
        if not post_id or post_id not in self.posts:
            return {"success": False, "error": "Invalid post_id"}
        
        if not content:
            # Generate quote content
            original = self.posts[post_id]
            prompt = f"Write a short comment (under 100 chars) quoting this post: \"{original['content'][:50]}...\" as {agent.profile.name}"
            messages = [{"role": "user", "content": prompt}]
            llm_client = get_llm_client()
            content = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: llm_client.chat(messages, temperature=0.7, max_tokens=50)
            )
        
        cursor.execute("""
            INSERT INTO post (user_id, content, original_post_id, quoted_content)
            VALUES (?, ?, ?, ?)
        """, (agent.agent_id, content, post_id, original["content"]))
        
        new_post_id = cursor.lastrowid
        self.posts[new_post_id] = {
            "id": new_post_id,
            "author_id": agent.agent_id,
            "author": agent.profile.name,
            "content": content,
            "original_post_id": post_id,
            "quoted_content": original["content"],
            "created_at": datetime.now().isoformat()
        }
        
        return {
            "success": True,
            "action": "quote_post",
            "new_post_id": new_post_id,
            "quoted_post_id": post_id,
            "content": content
        }
    
    async def _do_follow(
        self,
        agent: Agent,
        args: Dict[str, Any],
        cursor
    ) -> Dict[str, Any]:
        """Follow another user"""
        follow_id = args.get("follow_id")
        
        if not follow_id:
            # Pick a random agent to follow
            agents = list(self.agent_graph.agents.keys())
            if len(agents) > 1:
                candidates = [a for a in agents if a != agent.agent_id]
                follow_id = random.choice(candidates)
            else:
                return {"success": False, "error": "No users available to follow"}
        
        cursor.execute("""
            INSERT OR IGNORE INTO follow (follower_id, following_id)
            VALUES (?, ?)
        """, (agent.agent_id, follow_id))
        
        agent.follows.append(follow_id)
        self.agent_graph.add_relationship(agent.agent_id, follow_id, "follows")
        
        # Notify followed user
        try:
            followed = self.agent_graph.get_agent(follow_id)
            followed.add_to_memory({
                "type": "follow",
                "followed_by": agent.profile.name
            })
        except KeyError:
            pass
        
        return {
            "success": True,
            "action": "follow",
            "follow_id": follow_id
        }
    
    async def _do_interview(
        self,
        agent: Agent,
        args: Dict[str, Any],
        cursor
    ) -> Dict[str, Any]:
        """Interview agent (manual action)"""
        prompt = args.get("prompt", "")
        
        # Use LLM to generate response as the agent
        system_prompt = f"You are {agent.profile.name}. {agent.profile.bio}\nPersonality: {agent.profile.personality_traits}\n\nAnswer the following question in character:"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        llm_client = get_llm_client()
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: llm_client.chat(messages, temperature=0.5, max_tokens=500)
        )
        
        return {
            "success": True,
            "action": "interview",
            "prompt": prompt,
            "response": response
        }
    
    # ============================================================
    # Reddit-specific action handlers
    # ============================================================
    
    async def _do_dislike_post(
        self,
        agent: Agent,
        args: Dict[str, Any],
        cursor
    ) -> Dict[str, Any]:
        """Dislike a post (Reddit downvote)"""
        post_id = args.get("post_id")
        
        if not post_id:
            if self.posts:
                post_id = random.choice(list(self.posts.keys()))
            else:
                return {"success": False, "error": "No posts available"}
        
        cursor.execute("""
            INSERT INTO vote (user_id, post_id, vote_type)
            VALUES (?, ?, -1)
        """, (agent.agent_id, post_id))
        
        return {
            "success": True,
            "action": "dislike_post",
            "post_id": post_id
        }
    
    async def _do_create_comment(
        self,
        agent: Agent,
        args: Dict[str, Any],
        cursor
    ) -> Dict[str, Any]:
        """Create a comment on a post"""
        post_id = args.get("post_id")
        content = args.get("content", "")
        parent_comment_id = args.get("parent_comment_id")
        
        if not post_id:
            if self.posts:
                post_id = random.choice(list(self.posts.keys()))
            else:
                return {"success": False, "error": "No posts available"}
        
        if not content:
            # Generate comment using LLM
            post = self.posts.get(post_id)
            if post:
                prompt = f"Write a short comment (under 100 chars) replying to this post: \"{post['content'][:80]}...\" as {agent.profile.name}"
                messages = [{"role": "user", "content": prompt}]
                llm_client = get_llm_client()
                content = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: llm_client.chat(messages, temperature=0.7, max_tokens=50)
                )
            else:
                return {"success": False, "error": "Post not found"}
        
        cursor.execute("""
            INSERT INTO comment (user_id, post_id, content, parent_comment_id)
            VALUES (?, ?, ?, ?)
        """, (agent.agent_id, post_id, content, parent_comment_id))
        
        comment_id = cursor.lastrowid
        self.comments[comment_id] = {
            "id": comment_id,
            "author_id": agent.agent_id,
            "author": agent.profile.name,
            "content": content,
            "post_id": post_id,
            "created_at": datetime.now().isoformat()
        }
        
        return {
            "success": True,
            "action": "create_comment",
            "comment_id": comment_id,
            "content": content
        }
    
    async def _do_like_comment(
        self,
        agent: Agent,
        args: Dict[str, Any],
        cursor
    ) -> Dict[str, Any]:
        """Like a comment"""
        comment_id = args.get("comment_id")
        
        if not comment_id:
            if self.comments:
                comment_id = random.choice(list(self.comments.keys()))
            else:
                return {"success": False, "error": "No comments available"}
        
        cursor.execute("""
            INSERT INTO vote (user_id, comment_id, vote_type)
            VALUES (?, ?, 1)
        """, (agent.agent_id, comment_id))
        
        return {
            "success": True,
            "action": "like_comment",
            "comment_id": comment_id
        }
    
    async def _do_dislike_comment(
        self,
        agent: Agent,
        args: Dict[str, Any],
        cursor
    ) -> Dict[str, Any]:
        """Dislike a comment"""
        comment_id = args.get("comment_id")
        
        if not comment_id:
            if self.comments:
                comment_id = random.choice(list(self.comments.keys()))
            else:
                return {"success": False, "error": "No comments available"}
        
        cursor.execute("""
            INSERT INTO vote (user_id, comment_id, vote_type)
            VALUES (?, ?, -1)
        """, (agent.agent_id, comment_id))
        
        return {
            "success": True,
            "action": "dislike_comment",
            "comment_id": comment_id
        }
    
    async def _do_search_posts(
        self,
        agent: Agent,
        args: Dict[str, Any],
        cursor
    ) -> Dict[str, Any]:
        """Search for posts"""
        query = args.get("query", "")
        
        # Simple search - find posts containing the query
        results = []
        for post_id, post in self.posts.items():
            if query.lower() in post["content"].lower():
                results.append({"post_id": post_id, "content": post["content"]})
        
        return {
            "success": True,
            "action": "search_posts",
            "query": query,
            "results": results[:10]  # Limit to 10 results
        }
    
    async def _do_search_user(
        self,
        agent: Agent,
        args: Dict[str, Any],
        cursor
    ) -> Dict[str, Any]:
        """Search for users"""
        query = args.get("query", "")
        
        results = []
        for agent_id, other_agent in self.agent_graph.get_agents():
            if query.lower() in other_agent.profile.name.lower():
                results.append({
                    "agent_id": agent_id,
                    "name": other_agent.profile.name
                })
        
        return {
            "success": True,
            "action": "search_user",
            "query": query,
            "results": results[:10]
        }
    
    async def _do_trend(
        self,
        agent: Agent,
        args: Dict[str, Any],
        cursor
    ) -> Dict[str, Any]:
        """Get trending posts"""
        # Return top posts by engagement (likes + comments)
        trending = []
        for post_id, post in list(self.posts.items())[-20:]:  # Recent posts
            cursor.execute("SELECT COUNT(*) FROM like WHERE post_id = ?", (post_id,))
            like_count = cursor.fetchone()[0]
            trending.append({
                "post_id": post_id,
                "content": post["content"],
                "engagement": like_count
            })
        
        trending.sort(key=lambda x: x["engagement"], reverse=True)
        
        return {
            "success": True,
            "action": "trend",
            "trending": trending[:5]
        }
    
    async def _do_mute(
        self,
        agent: Agent,
        args: Dict[str, Any],
        cursor
    ) -> Dict[str, Any]:
        """Mute another user"""
        mute_id = args.get("mute_id")
        
        if not mute_id:
            return {"success": False, "error": "No user specified"}
        
        return {
            "success": True,
            "action": "mute",
            "mute_id": mute_id
        }
    
    def close(self):
        """Close environment and cleanup"""
        if self.db_conn:
            self.db_conn.close()
            self.db_conn = None


# ============================================================
# make() function - Replaces oasis.make()
# ============================================================

def make(
    agent_graph: AgentGraph,
    platform: str = DefaultPlatformType.TWITTER,
    database_path: str = None,
    semaphore: int = 30
) -> MicroFishEnv:
    """
    Create simulation environment
    
    Args:
        agent_graph: Agent graph from generate_*_agent_graph
        platform: Platform type ("twitter" or "reddit")
        database_path: Path to SQLite database
        semaphore: Max concurrent LLM requests
        
    Returns:
        MicroFishEnv instance
    """
    return MicroFishEnv(
        agent_graph=agent_graph,
        platform=platform,
        database_path=database_path,
        semaphore=semaphore
    )
