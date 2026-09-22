"""
Simulation Configuration Intelligence Generator
Use LLM to automatically generate detailed simulation parameters based on simulation requirements, document content, and graph information
Implement full program automation, no need for manual parameter settings

Adopt step-by-step generation strategy to avoid failure caused by generating too long content at once:
1. Generate Time Configuration
2. Generate Event Configuration
3. Batch Generate Agent Configuration
4. Generate Platform Configuration
"""

import json
import math
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime

from openai import OpenAI

from ..config import Config
from ..utils.logger import get_logger
from .zep_entity_reader import EntityNode, ZepEntityReader

logger = get_logger('mirofish.simulation_config')

# Default daily activity rhythm (local time)
DEFAULT_ACTIVITY_RHYTHM = {
    # Late night hour segment (few people active)
    "dead_hours": [0, 1, 2, 3, 4, 5],
    # morning hours (gradually waking up)
    "morning_hours": [6, 7, 8],
    # work hour segment
    "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
    # evening peak (most active)
    "peak_hours": [19, 20, 21, 22],
    # Night hour segment (activity level downgrades)
    "night_hours": [23],
    # Activity level multiplier
    "activity_multipliers": {
        "dead": 0.05,      # Late night few people
        "morning": 0.4,    # Morning gradually active
        "work": 0.7,       # work hour segment medium activity
        "peak": 1.5,       # evening peak
        "night": 0.5       # Late night downgrade
    }
}


@dataclass
class AgentActivityConfig:
    """Single agent activity configuration"""
    agent_id: int
    entity_uuid: str
    entity_name: str
    entity_type: str
    
    # Activity level configuration (0.0-1.0)
    activity_level: float = 0.5  # Overall activity depth
    
    # Speaking frequency (expected number of speeches per hour)
    posts_per_hour: float = 1.0
    comments_per_hour: float = 2.0
    
    # Active time segment (24 hour format, 0-23)
    active_hours: List[int] = field(default_factory=lambda: list(range(8, 23)))
    
    # Response speed (reaction delay to hot point events, unit: simulation minutes)
    response_delay_min: int = 5
    response_delay_max: int = 60
    
    # Emotional tendency (-1.0 to 1.0, negative to positive)
    sentiment_bias: float = 0.0
    
    # Stance (depth toward specific chat question)
    stance: str = "neutral"  # supportive, opposing, neutral, observer
    
    # Influence power weight (determines probability its speech is seen by other agents)
    influence_weight: float = 1.0


@dataclass  
class TimeSimulationConfig:
    """Time simulation configuration (based on a generic daily rhythm)"""
    # Simulation total hours (simulation hour count)
    total_simulation_hours: int = 72  # Default simulate 72 hours (3 days)
    
    # Each round represents time (simulation minutes) - Default 60 minutes (1 hour), add fast time flow
    minutes_per_round: int = 60
    
    # Per hour activate agent number range
    agents_per_hour_min: int = 5
    agents_per_hour_max: int = 20
    
    # Peak hour segment (evening 19-22, typically most active)
    peak_hours: List[int] = field(default_factory=lambda: [19, 20, 21, 22])
    peak_activity_multiplier: float = 1.5
    
    # Low valley hour segment (early morning 0-5, few people active)
    off_peak_hours: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5])
    off_peak_activity_multiplier: float = 0.05  # Early morning activity multiplier very low
    
    # morning hours
    morning_hours: List[int] = field(default_factory=lambda: [6, 7, 8])
    morning_activity_multiplier: float = 0.4
    
    # work hours
    work_hours: List[int] = field(default_factory=lambda: [9, 10, 11, 12, 13, 14, 15, 16, 17, 18])
    work_activity_multiplier: float = 0.7


@dataclass
class EventConfig:
    """Event Configuration"""
    # Initial event (triggered at simulation start hour)
    initial_posts: List[Dict[str, Any]] = field(default_factory=list)
    
    # Must hour event (triggered at specific time)
    scheduled_events: List[Dict[str, Any]] = field(default_factory=list)
    
    # Hot point chat question keyword
    hot_topics: List[str] = field(default_factory=list)
    
    # Sentiment guidance direction
    narrative_direction: str = ""


@dataclass
class PlatformConfig:
    """Platform Specific Configuration"""
    platform: str  # twitter or reddit
    
    # Recommendation algorithm weights
    recency_weight: float = 0.4  # Time freshness
    popularity_weight: float = 0.3  # Popularity depth
    relevance_weight: float = 0.3  # Relevance
    
    # Viral spread threshold (after reaching how much interaction triggers diffusion)
    viral_threshold: int = 10
    
    # Echo chamber effect strength depth (similar viewpoint aggregation degree)
    echo_chamber_strength: float = 0.5


@dataclass
class SimulationParameters:
    """Complete simulation parameter configuration"""
    # Basic information
    simulation_id: str
    project_id: str
    graph_id: str
    simulation_requirement: str
    domain: str = "social"
    domain_pack_path: str = ""
    domain_reasoning: str = ""
    tracks: List[str] = field(default_factory=lambda: ["main"])
    
    # TimeConfiguration
    time_config: TimeSimulationConfig = field(default_factory=TimeSimulationConfig)
    
    # AgentConfigurationlist
    agent_configs: List[AgentActivityConfig] = field(default_factory=list)
    
    # eventConfiguration
    event_config: EventConfig = field(default_factory=EventConfig)
    
    # PlatformConfiguration
    twitter_config: Optional[PlatformConfig] = None
    reddit_config: Optional[PlatformConfig] = None
    
    # LLMConfiguration
    llm_model: str = ""
    llm_base_url: str = ""
    
    # Generate metadata
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    generation_reasoning: str = ""  # LLM inference explanation
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict"""
        time_dict = asdict(self.time_config)
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "simulation_requirement": self.simulation_requirement,
            "domain": self.domain,
            "domain_pack_path": self.domain_pack_path,
            "domain_reasoning": self.domain_reasoning,
            "tracks": self.tracks,
            "time_config": time_dict,
            "agent_configs": [asdict(a) for a in self.agent_configs],
            "event_config": asdict(self.event_config),
            "twitter_config": asdict(self.twitter_config) if self.twitter_config else None,
            "reddit_config": asdict(self.reddit_config) if self.reddit_config else None,
            "llm_model": self.llm_model,
            "llm_base_url": self.llm_base_url,
            "generated_at": self.generated_at,
            "generation_reasoning": self.generation_reasoning,
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class SimulationConfigGenerator:
    """
    Simulation Configuration Intelligence Generator
    
    Use LLM to analyze simulation requirements, document content, graph entity information,
    Automatically generate optimal simulation parameter configuration
    
    Adopt step-by-step generation strategy:
    1. Generate time configuration and event configuration (lightweight)
    2. Batch generate agent configuration (each batch 10-20)
    3. Generate Platform Configuration
    """
    
    # Context maximum character count
    MAX_CONTEXT_LENGTH = 50000
    # Agents per batch count
    AGENTS_PER_BATCH = 15
    
    # Each step context truncate length (character count)
    TIME_CONFIG_CONTEXT_LENGTH = 10000   # Time Configuration
    EVENT_CONFIG_CONTEXT_LENGTH = 8000   # Event Configuration
    ENTITY_SUMMARY_LENGTH = 300          # Entity summary
    AGENT_SUMMARY_LENGTH = 300           # Agent configuration middle entity summary
    ENTITIES_PER_TYPE_DISPLAY = 20       # Each type entity display count
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model_name = model_name or Config.LLM_MODEL_NAME
        
        if not self.api_key:
            raise ValueError("LLM_API_KEY not configured")
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
    
    def generate_config(
        self,
        simulation_id: str,
        project_id: str,
        graph_id: str,
        simulation_requirement: str,
        document_text: str,
        entities: List[EntityNode],
        enable_twitter: bool = True,
        enable_reddit: bool = True,
        domain: str = "social",
        domain_pack_path: str = "",
        domain_reasoning: str = "",
        tracks: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> SimulationParameters:
        """
        Intelligently generate the complete simulation configuration (generated in steps)
        
        Args:
            simulation_id: simulateID
            project_id: Project ID
            graph_id: GraphID
            simulation_requirement: Simulation requirement description
            document_text: Original document content
            entities: Filtered entity list
            enable_twitter: whetherEnableTwitter
            enable_reddit: whetherEnableReddit
            progress_callback: enterdepthreturnFunction(current_step, total_steps, message)
            
        Returns:
            SimulationParameters: Complete simulation parameters
        """
        logger.info(f"Start intelligently generating simulation configuration: simulation_id={simulation_id}, entity count={len(entities)}")
        
        # Calculate total step count
        num_batches = math.ceil(len(entities) / self.AGENTS_PER_BATCH)
        total_steps = 3 + num_batches  # TimeConfiguration + eventConfiguration + NbatchAgent + PlatformConfiguration
        current_step = 0
        
        def report_progress(step: int, message: str):
            nonlocal current_step
            current_step = step
            if progress_callback:
                progress_callback(step, total_steps, message)
            logger.info(f"[{step}/{total_steps}] {message}")
        
        # 1. buildbaseUpunderdocinformation
        context = self._build_context(
            simulation_requirement=simulation_requirement,
            document_text=document_text,
            entities=entities
        )
        
        reasoning_parts = []
        
        # ========== Step 1: Generate Time Configuration ==========
        report_progress(1, "GenerateTimeConfiguration...")
        num_entities = len(entities)
        time_config_result = self._generate_time_config(context, num_entities)
        time_config = self._parse_time_config(time_config_result, num_entities)
        reasoning_parts.append(f"TimeConfiguration: {time_config_result.get('reasoning', 'success')}")
        
        # ========== step2: GenerateeventConfiguration ==========
        report_progress(2, "GenerateeventConfigurationsumhotpointchatquestion...")
        event_config_result = self._generate_event_config(context, simulation_requirement, entities)
        event_config = self._parse_event_config(event_config_result)
        reasoning_parts.append(f"eventConfiguration: {event_config_result.get('reasoning', 'success')}")
        
        # ========== step3-N: minutebatchGenerateAgentConfiguration ==========
        all_agent_configs = []
        for batch_idx in range(num_batches):
            start_idx = batch_idx * self.AGENTS_PER_BATCH
            end_idx = min(start_idx + self.AGENTS_PER_BATCH, len(entities))
            batch_entities = entities[start_idx:end_idx]
            
            report_progress(
                3 + batch_idx,
                f"GenerateAgentConfiguration ({start_idx + 1}-{end_idx}/{len(entities)})..."
            )
            
            batch_configs = self._generate_agent_configs_batch(
                context=context,
                entities=batch_entities,
                start_idx=start_idx,
                simulation_requirement=simulation_requirement
            )
            all_agent_configs.extend(batch_configs)
        
        reasoning_parts.append(f"AgentConfiguration: successGenerate {len(all_agent_configs)} ")
        
        # ========== Assign initial post publisher agents ==========
        logger.info("Assign appropriate publisher agents for initial posts...")
        event_config = self._assign_initial_post_agents(event_config, all_agent_configs)
        assigned_count = len([p for p in event_config.initial_posts if p.get("poster_agent_id") is not None])
        reasoning_parts.append(f"Initialstudentminutematch: {assigned_count} studentminutematchsendclother")
        
        # ========== Lastone: GeneratePlatformConfiguration ==========
        report_progress(total_steps, "GeneratePlatformConfiguration...")
        twitter_config = None
        reddit_config = None
        
        if enable_twitter:
            twitter_config = PlatformConfig(
                platform="twitter",
                recency_weight=0.4,
                popularity_weight=0.3,
                relevance_weight=0.3,
                viral_threshold=10,
                echo_chamber_strength=0.5
            )
        
        if enable_reddit:
            reddit_config = PlatformConfig(
                platform="reddit",
                recency_weight=0.3,
                popularity_weight=0.4,
                relevance_weight=0.3,
                viral_threshold=15,
                echo_chamber_strength=0.6
            )
        
        # Build final parameters
        params = SimulationParameters(
            simulation_id=simulation_id,
            project_id=project_id,
            graph_id=graph_id,
            simulation_requirement=simulation_requirement,
            domain=domain,
            domain_pack_path=domain_pack_path,
            domain_reasoning=domain_reasoning,
            tracks=tracks or (["twitter", "reddit"] if domain == "social" else ["main"]),
            time_config=time_config,
            agent_configs=all_agent_configs,
            event_config=event_config,
            twitter_config=twitter_config,
            reddit_config=reddit_config,
            llm_model=self.model_name,
            llm_base_url=self.base_url,
            generation_reasoning=" | ".join(reasoning_parts)
        )
        
        logger.info(f"simulateConfigurationGeneratecomplete: {len(params.agent_configs)} AgentConfiguration")
        
        return params
    
    def _build_context(
        self,
        simulation_requirement: str,
        document_text: str,
        entities: List[EntityNode]
    ) -> str:
        """Build the LLM context, truncated to the maximum length."""
        
        # Entitywant
        entity_summary = self._summarize_entities(entities)
        
        # buildUpunderdoc
        context_parts = [
            f"## simulaterequirement\n{simulation_requirement}",
            f"\n## Entityinformation ({len(entities)})\n{entity_summary}",
        ]
        
        current_length = sum(len(p) for p in context_parts)
        remaining_length = self.MAX_CONTEXT_LENGTH - current_length - 500  # keep500characterremaindermeasure
        
        if remaining_length > 0 and document_text:
            doc_text = document_text[:remaining_length]
            if len(document_text) > remaining_length:
                doc_text += "\n...(Document truncated)"
            context_parts.append(f"\n## Original document content\n{doc_text}")
        
        return "\n".join(context_parts)
    
    def _summarize_entities(self, entities: List[EntityNode]) -> str:
        """GenerateEntitywant"""
        lines = []
        
        # Typegroup
        by_type: Dict[str, List[EntityNode]] = {}
        for e in entities:
            t = e.get_entity_type() or "Unknown"
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(e)
        
        for entity_type, type_entities in by_type.items():
            lines.append(f"\n### {entity_type} ({len(type_entities)})")
            # useConfigurationnumbermeasuresumwantLongdepth
            display_count = self.ENTITIES_PER_TYPE_DISPLAY
            summary_len = self.ENTITY_SUMMARY_LENGTH
            for e in type_entities[:display_count]:
                summary_preview = (e.summary[:summary_len] + "...") if len(e.summary) > summary_len else e.summary
                lines.append(f"- {e.name}: {summary_preview}")
            if len(type_entities) > display_count:
                lines.append(f"  ... alsohave {len(type_entities) - display_count} ")
        
        return "\n".join(lines)
    
    def _call_llm_with_retry(self, prompt: str, system_prompt: str) -> Dict[str, Any]:
        """LLM invocation with retry, includes JSON fix logic"""
        import re
        
        max_attempts = 3
        last_error = None
        
        for attempt in range(max_attempts):
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.7 - (attempt * 0.1)  # each timeheavytestdowngradeLowwarmdepth
                    # No max_tokens setting, let LLM generate freely
                )
                
                content = response.choices[0].message.content
                finish_reason = response.choices[0].finish_reason
                
                # checkwhetherbytruncate
                if finish_reason == 'length':
                    logger.warning(f"LLMoutputbytruncate (attempt {attempt+1})")
                    content = self._fix_truncated_json(content)
                
                # Try to parse JSON
                try:
                    return json.loads(content)
                except json.JSONDecodeError as e:
                    logger.warning(f"JSONparsefail (attempt {attempt+1}): {str(e)[:80]}")
                    
                    # testfixrepeatJSON
                    fixed = self._try_fix_config_json(content)
                    if fixed:
                        return fixed
                    
                    last_error = e
                    
            except Exception as e:
                logger.warning(f"LLMinvokefail (attempt {attempt+1}): {str(e)[:80]}")
                last_error = e
                import time
                time.sleep(2 * (attempt + 1))
        
        raise last_error or Exception("LLMinvokefail")
    
    def _fix_truncated_json(self, content: str) -> str:
        """Fix truncated JSON"""
        content = content.strip()
        
        # Calculate unclosed brackets
        open_braces = content.count('{') - content.count('}')
        open_brackets = content.count('[') - content.count(']')
        
        # checkwhetherhavenotcombinecharacterstring
        if content and content[-1] not in '",}]':
            content += '"'
        
        # Close brackets
        content += ']' * open_brackets
        content += '}' * open_braces
        
        return content
    
    def _try_fix_config_json(self, content: str) -> Optional[Dict[str, Any]]:
        """Try to fix configuration JSON"""
        import re
        
        # Fix truncated situation
        content = self._fix_truncated_json(content)
        
        # extractJSONpartial
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            json_str = json_match.group()
            
            # removecharacterstringMiddleswapgo
            def fix_string(match):
                s = match.group(0)
                s = s.replace('\n', ' ').replace('\r', ' ')
                s = re.sub(r'\s+', ' ', s)
                return s
            
            json_str = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', fix_string, json_str)
            
            try:
                return json.loads(json_str)
            except:
                # testremovehascontrolcharacter
                json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', json_str)
                json_str = re.sub(r'\s+', ' ', json_str)
                try:
                    return json.loads(json_str)
                except:
                    pass
        
        return None
    
    def _generate_time_config(self, context: str, num_entities: int) -> Dict[str, Any]:
        """GenerateTimeConfiguration"""
        # useConfigurationUpunderdoctruncateLongdepth
        context_truncated = context[:self.TIME_CONFIG_CONTEXT_LENGTH]
        
        # Calculate the maximum allowed value (90% of agent count)
        max_agents_allowed = max(1, int(num_entities * 0.9))
        
        prompt = f"""Based on the following simulation requirements, generate the time simulation configuration.

{context_truncated}

## task
Please generate the time configuration JSON.

### Basic principles (for reference only; adjust flexibly according to the specific event and population):
- Infer the user population and their timezone from the simulation requirements and seed document
- 0-5 o'clock: almost no activity (activity level multiplier 0.05)
- 6-8 o'clock: gradually active (activity level multiplier 0.4)
- Work time 9-18 point medium activity (Activity level multiplier 0.7)
- 19-22 o'clock: evening peak period (activity level multiplier 1.5)
- 23 point after activity level downgrades (Activity level multiplier 0.5)
- General pattern: low activity, morning gradual increase, medium activity during work hours, evening peak
- **Important**: the example values below are for reference only; adjust the specific hours according to the nature of the event and the population characteristics
  - For example: student populations may peak at 21-23; media may be active all day; official institutions only during work hours
  - For example: breaking hot topics may trigger late-night discussions, so off_peak_hours can be shortened accordingly

### Return JSON format (do not markdown)

Example:
{{
    "total_simulation_hours": 72,
    "minutes_per_round": 60,
    "agents_per_hour_min": 5,
    "agents_per_hour_max": 50,
    "peak_hours": [19, 20, 21, 22],
    "off_peak_hours": [0, 1, 2, 3, 4, 5],
    "morning_hours": [6, 7, 8],
    "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
    "reasoning": "time configuration reasoning for this event"
}}

Field explanations:
- total_simulation_hours (int): total simulation hours, 24-168 hours; shorter for breaking events, longer for sustained topics
- minutes_per_round (int): Each round minutes, 30-120 minutes, suggest 60 minutes
- agents_per_hour_min (int): minimum number of agents activated per hour (value range: 1-{max_agents_allowed})
- agents_per_hour_max (int): maximum number of agents activated per hour (value range: 1-{max_agents_allowed})
- peak_hours (list of int): peak hour segment, adjusted according to the event and population
- off_peak_hours (list of int): off-peak hours, usually late night/early morning
- morning_hours (list of int): morning hours
- work_hours (list of int): work hours
- reasoning (string): brief reasoning for this configuration"""

        system_prompt = (
            "You are a social media simulation specialist. Return pure JSON format. "
            "Infer the appropriate timezone and daily rhythm from the population "
            "described in the simulation requirements. Write all output in English."
        )
        
        try:
            return self._call_llm_with_retry(prompt, system_prompt)
        except Exception as e:
            logger.warning(f"TimeConfigurationLLMGeneratefail: {e}, Use default configuration")
            return self._get_default_time_config(num_entities)
    
    def _get_default_time_config(self, num_entities: int) -> Dict[str, Any]:
        """Get the default time configuration (generic daily rhythm)."""
        return {
            "total_simulation_hours": 72,
            "minutes_per_round": 60,  # Each round 1 hour, add fast time flow
            "agents_per_hour_min": max(1, num_entities // 15),
            "agents_per_hour_max": max(5, num_entities // 5),
            "peak_hours": [19, 20, 21, 22],
            "off_peak_hours": [0, 1, 2, 3, 4, 5],
            "morning_hours": [6, 7, 8],
            "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
            "reasoning": "Using the default daily activity rhythm (1 hour per round)"
        }
    
    def _parse_time_config(self, result: Dict[str, Any], num_entities: int) -> TimeSimulationConfig:
        """Parse time configuration result, and verify agents_per_hour values do not exceed total agent count"""
        # Get original values
        agents_per_hour_min = result.get("agents_per_hour_min", max(1, num_entities // 15))
        agents_per_hour_max = result.get("agents_per_hour_max", max(5, num_entities // 5))
        
        # Verify and fix: ensure does not exceed total agent count
        if agents_per_hour_min > num_entities:
            logger.warning(f"agents_per_hour_min ({agents_per_hour_min}) exceeds total agent count ({num_entities}); fixed")
            agents_per_hour_min = max(1, num_entities // 10)
        
        if agents_per_hour_max > num_entities:
            logger.warning(f"agents_per_hour_max ({agents_per_hour_max}) exceeds total agent count ({num_entities}); fixed")
            agents_per_hour_max = max(agents_per_hour_min + 1, num_entities // 2)
        
        # Ensure min < max
        if agents_per_hour_min >= agents_per_hour_max:
            agents_per_hour_min = max(1, agents_per_hour_max // 2)
            logger.warning(f"agents_per_hour_min >= max; fixed to {agents_per_hour_min}")
        
        return TimeSimulationConfig(
            total_simulation_hours=result.get("total_simulation_hours", 72),
            minutes_per_round=result.get("minutes_per_round", 60),  # Default each round 1 hour
            agents_per_hour_min=agents_per_hour_min,
            agents_per_hour_max=agents_per_hour_max,
            peak_hours=result.get("peak_hours", [19, 20, 21, 22]),
            off_peak_hours=result.get("off_peak_hours", [0, 1, 2, 3, 4, 5]),
            off_peak_activity_multiplier=0.05,  # Late night few people
            morning_hours=result.get("morning_hours", [6, 7, 8]),
            morning_activity_multiplier=0.4,
            work_hours=result.get("work_hours", list(range(9, 19))),
            work_activity_multiplier=0.7,
            peak_activity_multiplier=1.5
        )
    
    def _generate_event_config(
        self, 
        context: str, 
        simulation_requirement: str,
        entities: List[EntityNode]
    ) -> Dict[str, Any]:
        """GenerateeventConfiguration"""
        
        # Get available entity type list for LLM reference
        entity_types_available = list(set(
            e.get_entity_type() or "Unknown" for e in entities
        ))
        
        # For each type list representative entity names
        type_examples = {}
        for e in entities:
            etype = e.get_entity_type() or "Unknown"
            if etype not in type_examples:
                type_examples[etype] = []
            if len(type_examples[etype]) < 3:
                type_examples[etype].append(e.name)
        
        type_info = "\n".join([
            f"- {t}: {', '.join(examples)}" 
            for t, examples in type_examples.items()
        ])
        
        # useConfigurationUpunderdoctruncateLongdepth
        context_truncated = context[:self.EVENT_CONFIG_CONTEXT_LENGTH]
        
        prompt = f"""Based on the following simulation requirements, generate event configuration.

simulaterequirement: {simulation_requirement}

{context_truncated}

## Available entity types with examples
{type_info}

## task
Please generate the event configuration JSON:
- Extract hot topic keywords
- Description sentiment development direction
- Design initial post content, **each post must specify poster_type (publisher type)**

**Important**: poster_type must be selected from the "available entity types" listed above, so that each initial post can be matched to a suitable agent to publish it.
For example: official announcements should be posted by Official/University types, news by MediaOutlet, and student opinions by Student.

Return JSON format (do not markdown):
{{
    "hot_topics": ["keyword1", "keyword2", ...],
    "narrative_direction": "<Sentiment development direction description>",
    "initial_posts": [
        {{"content": "Post content", "poster_type": "EntityType (must be selected from the available types)"}},
        ...
    ],
    "reasoning": "<wantsaybright>"
}}"""

        system_prompt = "You are a sentiment analysis specialist. Return pure JSON format. poster_type must match the available entity types."
        
        try:
            return self._call_llm_with_retry(prompt, system_prompt)
        except Exception as e:
            logger.warning(f"Event configuration LLM generation failed: {e}, Use default configuration")
            return {
                "hot_topics": [],
                "narrative_direction": "",
                "initial_posts": [],
                "reasoning": "Use default configuration"
            }
    
    def _parse_event_config(self, result: Dict[str, Any]) -> EventConfig:
        """Parse event configuration result"""
        return EventConfig(
            initial_posts=result.get("initial_posts", []),
            scheduled_events=[],
            hot_topics=result.get("hot_topics", []),
            narrative_direction=result.get("narrative_direction", "")
        )
    
    def _assign_initial_post_agents(
        self,
        event_config: EventConfig,
        agent_configs: List[AgentActivityConfig]
    ) -> EventConfig:
        """
        Assign appropriate publisher agents for initial posts
        
        Match the most suitable agent_id according to each post poster_type
        """
        if not event_config.initial_posts:
            return event_config
        
        # EntityTypeestablish agent index
        agents_by_type: Dict[str, List[AgentActivityConfig]] = {}
        for agent in agent_configs:
            etype = agent.entity_type.lower()
            if etype not in agents_by_type:
                agents_by_type[etype] = []
            agents_by_type[etype].append(agent)
        
        # Type mapping table (process LLM can output different formats)
        type_aliases = {
            "official": ["official", "university", "governmentagency", "government"],
            "university": ["university", "official"],
            "mediaoutlet": ["mediaoutlet", "media"],
            "student": ["student", "person"],
            "professor": ["professor", "expert", "teacher"],
            "alumni": ["alumni", "person"],
            "organization": ["organization", "ngo", "company", "group"],
            "person": ["person", "student", "alumni"],
        }
        
        # Track the next agent index to use per type, to avoid reusing the same agent
        used_indices: Dict[str, int] = {}
        
        updated_posts = []
        for post in event_config.initial_posts:
            poster_type = post.get("poster_type", "").lower()
            content = post.get("content", "")
            
            # Try to find matching agent
            matched_agent_id = None
            
            # 1. connectmatch
            if poster_type in agents_by_type:
                agents = agents_by_type[poster_type]
                idx = used_indices.get(poster_type, 0) % len(agents)
                matched_agent_id = agents[idx].agent_id
                used_indices[poster_type] = idx + 1
            else:
                # 2. Use alias match
                for alias_key, aliases in type_aliases.items():
                    if poster_type in aliases or alias_key == poster_type:
                        for alias in aliases:
                            if alias in agents_by_type:
                                agents = agents_by_type[alias]
                                idx = used_indices.get(alias, 0) % len(agents)
                                matched_agent_id = agents[idx].agent_id
                                used_indices[alias] = idx + 1
                                break
                    if matched_agent_id is not None:
                        break
            
            # 3. If still not found, use the agent with the highest influence weight
            if matched_agent_id is None:
                logger.warning(f"No agent matching type '{poster_type}' found; using the highest-influence agent")
                if agent_configs:
                    # Sort by influence weight, select the highest-influence agent
                    sorted_agents = sorted(agent_configs, key=lambda a: a.influence_weight, reverse=True)
                    matched_agent_id = sorted_agents[0].agent_id
                else:
                    matched_agent_id = 0
            
            updated_posts.append({
                "content": content,
                "poster_type": post.get("poster_type", "Unknown"),
                "poster_agent_id": matched_agent_id
            })
            
            logger.info(f"Initialstudentminutematch: poster_type='{poster_type}' -> agent_id={matched_agent_id}")
        
        event_config.initial_posts = updated_posts
        return event_config
    
    def _generate_agent_configs_batch(
        self,
        context: str,
        entities: List[EntityNode],
        start_idx: int,
        simulation_requirement: str
    ) -> List[AgentActivityConfig]:
        """minutebatchGenerateAgentConfiguration"""
        
        # Build entity information (use the desired length)
        entity_list = []
        summary_len = self.AGENT_SUMMARY_LENGTH
        for i, e in enumerate(entities):
            entity_list.append({
                "agent_id": start_idx + i,
                "entity_name": e.name,
                "entity_type": e.get_entity_type() or "Unknown",
                "summary": e.summary[:summary_len] if e.summary else ""
            })
        
        prompt = f"""Based on the information below, generate social media activity configuration for each entity.

Simulation requirement: {simulation_requirement}

## Entity list
```json
{json.dumps(entity_list, ensure_ascii=False, indent=2)}
```

## Task
For each entity, generate activity configuration. Note:
- **Follow a realistic daily rhythm for this population**: little activity from 0-5, most active in the evening 19-22
- **Official institutions** (University/GovernmentAgency): low activity level (0.1-0.3), active during work hours (9-17), slow response (60-240 minutes), high influence (2.5-3.0)
- **Media** (MediaOutlet): medium activity level (0.4-0.6), active all day (8-23), fast response (5-30 minutes), high influence (2.0-2.5)
- **Individuals** (Student/Person/Alumni): high activity level (0.6-0.9), mainly active in the evening (18-23), fast response (1-15 minutes), low influence (0.8-1.2)
- **Public figures/Experts**: Medium activity depth (0.4-0.6), medium-high influence power (1.5-2.0)

Return JSON format (do not markdown):
{{
    "agent_configs": [
        {{
            "agent_id": <must match the input agent_id>,
            "activity_level": <0.0-1.0>,
            "posts_per_hour": <posting frequency>,
            "comments_per_hour": <comment frequency>,
            "active_hours": [<list of active hours for this entity>],
            "response_delay_min": <minimum response delay in minutes>,
            "response_delay_max": <maximum response delay in minutes>,
            "sentiment_bias": <-1.0 to 1.0>,
            "stance": "<supportive/opposing/neutral/observer>",
            "influence_weight": <influence weight>
        }},
        ...
    ]
}}"""

        system_prompt = (
            "You are a social media behavior analysis specialist. Return pure JSON. "
            "Infer each entity's daily rhythm from its role and the population described "
            "in the simulation requirements. Write all output in English."
        )
        
        try:
            result = self._call_llm_with_retry(prompt, system_prompt)
            llm_configs = {cfg["agent_id"]: cfg for cfg in result.get("agent_configs", [])}
        except Exception as e:
            logger.warning(f"Agent configuration batch LLM generation failed: {e}, Use rules to generate")
            llm_configs = {}
        
        # Build AgentActivityConfig object
        configs = []
        for i, entity in enumerate(entities):
            agent_id = start_idx + i
            cfg = llm_configs.get(agent_id, {})
            
            # If the LLM did not generate one, generate it by rule
            if not cfg:
                cfg = self._generate_agent_config_by_rule(entity)
            
            config = AgentActivityConfig(
                agent_id=agent_id,
                entity_uuid=entity.uuid,
                entity_name=entity.name,
                entity_type=entity.get_entity_type() or "Unknown",
                activity_level=cfg.get("activity_level", 0.5),
                posts_per_hour=cfg.get("posts_per_hour", 0.5),
                comments_per_hour=cfg.get("comments_per_hour", 1.0),
                active_hours=cfg.get("active_hours", list(range(9, 23))),
                response_delay_min=cfg.get("response_delay_min", 5),
                response_delay_max=cfg.get("response_delay_max", 60),
                sentiment_bias=cfg.get("sentiment_bias", 0.0),
                stance=cfg.get("stance", "neutral"),
                influence_weight=cfg.get("influence_weight", 1.0)
            )
            configs.append(config)
        
        return configs
    
    def _generate_agent_config_by_rule(self, entity: EntityNode) -> Dict[str, Any]:
        """Generate a single agent configuration by rule (generic daily rhythm)."""
        entity_type = (entity.get_entity_type() or "Unknown").lower()
        
        if entity_type in ["university", "governmentagency", "ngo"]:
            # Official institutions: active during work hours, low frequency, high influence
            return {
                "activity_level": 0.2,
                "posts_per_hour": 0.1,
                "comments_per_hour": 0.05,
                "active_hours": list(range(9, 18)),  # 9:00-17:59
                "response_delay_min": 60,
                "response_delay_max": 240,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 3.0
            }
        elif entity_type in ["mediaoutlet"]:
            # Media: all-day activity, medium frequency, high influence
            return {
                "activity_level": 0.5,
                "posts_per_hour": 0.8,
                "comments_per_hour": 0.3,
                "active_hours": list(range(7, 24)),  # 7:00-23:59
                "response_delay_min": 5,
                "response_delay_max": 30,
                "sentiment_bias": 0.0,
                "stance": "observer",
                "influence_weight": 2.5
            }
        elif entity_type in ["professor", "expert", "official"]:
            # Experts/teachers: active during work and evening hours, medium frequency
            return {
                "activity_level": 0.4,
                "posts_per_hour": 0.3,
                "comments_per_hour": 0.5,
                "active_hours": list(range(8, 22)),  # 8:00-21:59
                "response_delay_min": 15,
                "response_delay_max": 90,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 2.0
            }
        elif entity_type in ["student"]:
            # Students: mainly evening, high frequency
            return {
                "activity_level": 0.8,
                "posts_per_hour": 0.6,
                "comments_per_hour": 1.5,
                "active_hours": [8, 9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],  # Up+lateBetween
                "response_delay_min": 1,
                "response_delay_max": 15,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 0.8
            }
        elif entity_type in ["alumni"]:
            # Alumni: mainly evening
            return {
                "activity_level": 0.6,
                "posts_per_hour": 0.4,
                "comments_per_hour": 0.8,
                "active_hours": [12, 13, 19, 20, 21, 22, 23],  # rest+lateBetween
                "response_delay_min": 5,
                "response_delay_max": 30,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 1.0
            }
        else:
            # Regular people: evening peak
            return {
                "activity_level": 0.7,
                "posts_per_hour": 0.5,
                "comments_per_hour": 1.2,
                "active_hours": [9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],  # day+lateBetween
                "response_delay_min": 2,
                "response_delay_max": 20,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 1.0
            }
    

