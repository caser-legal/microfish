"""
OASIS Agent Profile Generator
willZepGraphMiddleEntityturnswapforOASISsimulatePlatformplaceneedAgent Profileformat

Optimized modifications:
1. Invoke Zep retrieve function to enrich key point information
2. optimizedpromptwordGenerate notvery detailedpersonset
3. individual person Entitysumabstract Swarm Entity
"""

import json
import random
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

from openai import OpenAI
from zep_cloud.client import Zep

from ..config import Config
from ..utils.logger import get_logger
from .zep_entity_reader import EntityNode, ZepEntityReader

logger = get_logger('mirofish.oasis_profile')


@dataclass
class OasisAgentProfile:
    """OASIS Agent Profile Data structure"""
    # use field
    user_id: int
    user_name: str
    name: str
    bio: str
    persona: str
    
    # Optional field - Redditstyle
    karma: int = 1000
    
    # Optional field - Twitterstyle
    friend_count: int = 100
    follower_count: int = 150
    statuses_count: int = 500
    
    # Additional profile information
    age: Optional[int] = None
    gender: Optional[str] = None
    mbti: Optional[str] = None
    country: Optional[str] = None
    profession: Optional[str] = None
    interested_topics: List[str] = field(default_factory=list)
    
    # Future entity information
    source_entity_uuid: Optional[str] = None
    source_entity_type: Optional[str] = None
    
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    
    def to_reddit_format(self) -> Dict[str, Any]:
        """Convert to Reddit platform format"""
        profile = {
            "user_id": self.user_id,
            "username": self.user_name,  # OASIS requires the field name for username (no underscore)
            "name": self.name,
            "bio": self.bio,
            "persona": self.persona,
            "karma": self.karma,
            "created_at": self.created_at,
        }
        
        # Add additional profile information (if any)
        if self.age:
            profile["age"] = self.age
        if self.gender:
            profile["gender"] = self.gender
        if self.mbti:
            profile["mbti"] = self.mbti
        if self.country:
            profile["country"] = self.country
        if self.profession:
            profile["profession"] = self.profession
        if self.interested_topics:
            profile["interested_topics"] = self.interested_topics
        
        return profile
    
    def to_twitter_format(self) -> Dict[str, Any]:
        """Convert to Twitter platform format"""
        profile = {
            "user_id": self.user_id,
            "username": self.user_name,  # OASIS requires the field name for username (no underscore)
            "name": self.name,
            "bio": self.bio,
            "persona": self.persona,
            "friend_count": self.friend_count,
            "follower_count": self.follower_count,
            "statuses_count": self.statuses_count,
            "created_at": self.created_at,
        }
        
        # addAdditional profile information
        if self.age:
            profile["age"] = self.age
        if self.gender:
            profile["gender"] = self.gender
        if self.mbti:
            profile["mbti"] = self.mbti
        if self.country:
            profile["country"] = self.country
        if self.profession:
            profile["profession"] = self.profession
        if self.interested_topics:
            profile["interested_topics"] = self.interested_topics
        
        return profile
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to complete dict format"""
        return {
            "user_id": self.user_id,
            "user_name": self.user_name,
            "name": self.name,
            "bio": self.bio,
            "persona": self.persona,
            "karma": self.karma,
            "friend_count": self.friend_count,
            "follower_count": self.follower_count,
            "statuses_count": self.statuses_count,
            "age": self.age,
            "gender": self.gender,
            "mbti": self.mbti,
            "country": self.country,
            "profession": self.profession,
            "interested_topics": self.interested_topics,
            "source_entity_uuid": self.source_entity_uuid,
            "source_entity_type": self.source_entity_type,
            "created_at": self.created_at,
        }


class OasisProfileGenerator:
    """
    OASIS Profile Generator
    
    willZepGraphMiddleEntityturnswapforOASISsimulateplaceneedAgent Profile
    
    Excellent features:
    1. Invoke Zep Graph retrieve function to get more rich context
    2. Generate a highly detailed persona (including basic info, background history, traits, social media behavior, etc.)
    3. individual person Entitysumabstract Swarm Entity
    """
    
    # MBTI type list
    MBTI_TYPES = [
        "INTJ", "INTP", "ENTJ", "ENTP",
        "INFJ", "INFP", "ENFJ", "ENFP",
        "ISTJ", "ISFJ", "ESTJ", "ESFJ",
        "ISTP", "ISFP", "ESTP", "ESFP"
    ]
    
    # Common country list
    COUNTRIES = [
        "China", "US", "UK", "Japan", "Germany", "France", 
        "Canada", "Australia", "Brazil", "India", "South Korea"
    ]
    
    # Individual type entity (need to generate specific person settings)
    INDIVIDUAL_ENTITY_TYPES = [
        "student", "alumni", "professor", "person", "publicfigure", 
        "expert", "faculty", "official", "journalist", "activist"
    ]
    
    # Swarm/Organization type entity (need to generate swarm representative person settings)
    GROUP_ENTITY_TYPES = [
        "university", "governmentagency", "organization", "ngo", 
        "mediaoutlet", "company", "institution", "group", "community"
    ]
    
    def __init__(
        self, 
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        zep_api_key: Optional[str] = None,
        graph_id: Optional[str] = None
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
        
        # Zep client used to retrieve rich context
        self.zep_api_key = zep_api_key or Config.ZEP_API_KEY
        self.zep_client = None
        self.graph_id = graph_id
        
        if self.zep_api_key:
            try:
                self.zep_client = Zep(api_key=self.zep_api_key)
            except Exception as e:
                logger.warning(f"ZepclientendInitializefail: {e}")
    
    def generate_profile_from_entity(
        self, 
        entity: EntityNode, 
        user_id: int,
        use_llm: bool = True
    ) -> OasisAgentProfile:
        """
        fromZepEntityGenerateOASIS Agent Profile
        
        Args:
            entity: ZepEntitynode
            user_id: User ID (used for OASIS)
            use_llm: whether use LLM to generate detailed person settings
            
        Returns:
            OasisAgentProfile
        """
        entity_type = entity.get_entity_type() or "Entity"
        
        # Basic information
        name = entity.name
        user_name = self._generate_username(name)
        
        # Build context information
        context = self._build_entity_context(entity)
        
        if use_llm:
            # useLLMGeneratedetailedpersonset
            profile_data = self._generate_profile_with_llm(
                entity_name=name,
                entity_type=entity_type,
                entity_summary=entity.summary,
                entity_attributes=entity.attributes,
                context=context
            )
        else:
            # Use rules to generate basic person settings
            profile_data = self._generate_profile_rule_based(
                entity_name=name,
                entity_type=entity_type,
                entity_summary=entity.summary,
                entity_attributes=entity.attributes
            )
        
        return OasisAgentProfile(
            user_id=user_id,
            user_name=user_name,
            name=name,
            bio=profile_data.get("bio", f"{entity_type}: {name}"),
            persona=profile_data.get("persona", entity.summary or f"A {entity_type} named {name}."),
            karma=profile_data.get("karma", random.randint(500, 5000)),
            friend_count=profile_data.get("friend_count", random.randint(50, 500)),
            follower_count=profile_data.get("follower_count", random.randint(100, 1000)),
            statuses_count=profile_data.get("statuses_count", random.randint(100, 2000)),
            age=profile_data.get("age"),
            gender=profile_data.get("gender"),
            mbti=profile_data.get("mbti"),
            country=profile_data.get("country"),
            profession=profile_data.get("profession"),
            interested_topics=self._normalize_topics(profile_data.get("interested_topics")),
            source_entity_uuid=entity.uuid,
            source_entity_type=entity_type,
        )

    @staticmethod
    def _normalize_topics(value: Any) -> List[str]:
        """
        Normalize interested_topics into a list of strings.

        The LLM sometimes returns a comma-separated string instead of an array.
        Without this, the string is treated as an iterable of characters and the
        UI renders one "topic" per character.
        """
        if value is None:
            return []
        if isinstance(value, str):
            return [topic.strip() for topic in value.split(",") if topic.strip()]
        if isinstance(value, list):
            return [str(topic).strip() for topic in value if str(topic).strip()]
        return []
    
    def _generate_username(self, name: str) -> str:
        """Generateusername"""
        # Remove special characters and convert to lowercase
        username = name.lower().replace(" ", "_")
        username = ''.join(c for c in username if c.isalnum() or c == '_')
        
        # addrandomafter heavyrepeat
        suffix = random.randint(100, 999)
        return f"{username}_{suffix}"
    
    def _search_zep_for_entity(self, entity: EntityNode) -> Dict[str, Any]:
        """
        useZepGraphmixsearchfunctionGetEntityrelevantabundantrichinformation
        
        Zep has no built-in hybrid search interface; you need to search edges and nodes separately and then merge the results.
        Use concurrent requests to search in parallel for higher efficiency.
        
        Args:
            entity: Entitynodeobject
            
        Returns:
            containfacts, node_summaries, contextdict
        """
        import concurrent.futures
        
        if not self.zep_client:
            return {"facts": [], "node_summaries": [], "context": ""}
        
        entity_name = entity.name
        
        results = {
            "facts": [],
            "node_summaries": [],
            "context": ""
        }
        
        # musthavegraph_idcanentergosearch
        if not self.graph_id:
            logger.debug(f"Skipping Zep retrieval: graph_id is not set")
            return results
        
        comprehensive_query = f"information, activity, events, relations, and background about {entity_name}"
        
        def search_edges():
            """Search edges (facts/relations) - with a retry mechanism."""
            max_retries = 3
            last_exception = None
            delay = 2.0
            
            for attempt in range(max_retries):
                try:
                    return self.zep_client.graph.search(
                        query=comprehensive_query,
                        graph_id=self.graph_id,
                        limit=30,
                        scope="edges",
                        reranker="rrf"
                    )
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.debug(f"Zepedgesearch# {attempt + 1} fail: {str(e)[:80]}, heavytestMiddle...")
                        time.sleep(delay)
                        delay *= 2
                    else:
                        logger.debug(f"Zepedgesearchat {max_retries} testAfterstillfail: {e}")
            return None
        
        def search_nodes():
            """Search nodes (entity summaries) - with a retry mechanism."""
            max_retries = 3
            last_exception = None
            delay = 2.0
            
            for attempt in range(max_retries):
                try:
                    return self.zep_client.graph.search(
                        query=comprehensive_query,
                        graph_id=self.graph_id,
                        limit=20,
                        scope="nodes",
                        reranker="rrf"
                    )
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.debug(f"Zepnodesearch# {attempt + 1} fail: {str(e)[:80]}, heavytestMiddle...")
                        time.sleep(delay)
                        delay *= 2
                    else:
                        logger.debug(f"Zepnodesearchat {max_retries} testAfterstillfail: {e}")
            return None
        
        try:
            # andgoexecuteedgessumnodessearch
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                edge_future = executor.submit(search_edges)
                node_future = executor.submit(search_nodes)
                
                # Getresult
                edge_result = edge_future.result(timeout=30)
                node_result = node_future.result(timeout=30)
            
            # Processedgesearchresult
            all_facts = set()
            if edge_result and hasattr(edge_result, 'edges') and edge_result.edges:
                for edge in edge_result.edges:
                    if hasattr(edge, 'fact') and edge.fact:
                        all_facts.add(edge.fact)
            results["facts"] = list(all_facts)
            
            # Processnodesearchresult
            all_summaries = set()
            if node_result and hasattr(node_result, 'nodes') and node_result.nodes:
                for node in node_result.nodes:
                    if hasattr(node, 'summary') and node.summary:
                        all_summaries.add(node.summary)
                    if hasattr(node, 'name') and node.name and node.name != entity_name:
                        all_summaries.add(f"relevantEntity: {node.name}")
            results["node_summaries"] = list(all_summaries)
            
            # buildcombineUpunderdoc
            context_parts = []
            if results["facts"]:
                context_parts.append("factinformation:\n" + "\n".join(f"- {f}" for f in results["facts"][:20]))
            if results["node_summaries"]:
                context_parts.append("relevantEntity:\n" + "\n".join(f"- {s}" for s in results["node_summaries"][:10]))
            results["context"] = "\n\n".join(context_parts)
            
            logger.info(f"Zepmixretrievecomplete: {entity_name}, Get {len(results['facts'])} edgefact, {len(results['node_summaries'])} relevantnode")
            
        except concurrent.futures.TimeoutError:
            logger.warning(f"Zepretrievehour ({entity_name})")
        except Exception as e:
            logger.warning(f"Zepretrievefail ({entity_name}): {e}")
        
        return results
    
    def _build_entity_context(self, entity: EntityNode) -> str:
        """
        buildEntitycompleteUpunderdocinformation
        
        Includes:
        1. The entity's own edge information (facts)
        2. relationnodedetailedinformation
        3. Zepmixretrievetoabundantrichinformation
        """
        context_parts = []
        
        # 1. addEntityattributeinformation
        if entity.attributes:
            attrs = []
            for key, value in entity.attributes.items():
                if value and str(value).strip():
                    attrs.append(f"- {key}: {value}")
            if attrs:
                context_parts.append("### Entityattribute\n" + "\n".join(attrs))
        
        # 2. Add relevant edge information (facts/relations)
        existing_facts = set()
        if entity.related_edges:
            relationships = []
            for edge in entity.related_edges:  # nolimitnumbermeasure
                fact = edge.get("fact", "")
                edge_name = edge.get("edge_name", "")
                direction = edge.get("direction", "")
                
                if fact:
                    relationships.append(f"- {fact}")
                    existing_facts.add(fact)
                elif edge_name:
                    if direction == "outgoing":
                        relationships.append(f"- {entity.name} --[{edge_name}]--> (relevantEntity)")
                    else:
                        relationships.append(f"- (relevantEntity) --[{edge_name}]--> {entity.name}")
            
            if relationships:
                context_parts.append("### relevantfactsumRelation\n" + "\n".join(relationships))
        
        # 3. addrelationnodedetailedinformation
        if entity.related_nodes:
            related_info = []
            for node in entity.related_nodes:  # nolimitnumbermeasure
                node_name = node.get("name", "")
                node_labels = node.get("labels", [])
                node_summary = node.get("summary", "")
                
                # filterdropDefault
                custom_labels = [l for l in node_labels if l not in ["Entity", "Node"]]
                label_str = f" ({', '.join(custom_labels)})" if custom_labels else ""
                
                if node_summary:
                    related_info.append(f"- **{node_name}**{label_str}: {node_summary}")
                else:
                    related_info.append(f"- **{node_name}**{label_str}")
            
            if related_info:
                context_parts.append("### relationEntityinformation\n" + "\n".join(related_info))
        
        # 4. useZepmixretrieveGetmoreabundantrichinformation
        zep_results = self._search_zep_for_entity(entity)
        
        if zep_results.get("facts"):
            # Deduplicate: split rows of existing facts
            new_facts = [f for f in zep_results["facts"] if f not in existing_facts]
            if new_facts:
                context_parts.append("### Zepretrievetofactinformation\n" + "\n".join(f"- {f}" for f in new_facts[:15]))
        
        if zep_results.get("node_summaries"):
            context_parts.append("### Zepretrievetorelevantnode\n" + "\n".join(f"- {s}" for s in zep_results["node_summaries"][:10]))
        
        return "\n\n".join(context_parts)
    
    def _is_individual_entity(self, entity_type: str) -> bool:
        """cutwhetherarepersonTypeEntity"""
        return entity_type.lower() in self.INDIVIDUAL_ENTITY_TYPES
    
    def _is_group_entity(self, entity_type: str) -> bool:
        """cutwhetherareSwarm/agencyTypeEntity"""
        return entity_type.lower() in self.GROUP_ENTITY_TYPES
    
    def _generate_profile_with_llm(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str
    ) -> Dict[str, Any]:
        """
        useLLMGenerate notvery detailedpersonset
        
        By entity type:
        - Person entities: generate a specific individual persona
        - Group/organization entities: generate an organizational profile
        """
        
        is_individual = self._is_individual_entity(entity_type)
        
        if is_individual:
            prompt = self._build_individual_persona_prompt(
                entity_name, entity_type, entity_summary, entity_attributes, context
            )
        else:
            prompt = self._build_group_persona_prompt(
                entity_name, entity_type, entity_summary, entity_attributes, context
            )

        # Retry generation until success or the max retry count is reached
        max_attempts = 3
        last_error = None
        
        for attempt in range(max_attempts):
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": self._get_system_prompt(is_individual)},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.7 - (attempt * 0.1)  # each timeheavytestdowngradeLowwarmdepth
                    # Do not set max_tokens; let the LLM generate freely
                )
                
                content = response.choices[0].message.content
                
                # Check whether the output was truncated (finish_reason is not 'stop')
                finish_reason = response.choices[0].finish_reason
                if finish_reason == 'length':
                    logger.warning(f"LLMoutputbytruncate (attempt {attempt+1}), testfixrepeat...")
                    content = self._fix_truncated_json(content)
                
                # testparseJSON
                try:
                    result = json.loads(content)
                    
                    # verifymustneedwordsegment
                    if "bio" not in result or not result["bio"]:
                        result["bio"] = entity_summary[:200] if entity_summary else f"{entity_type}: {entity_name}"
                    if "persona" not in result or not result["persona"]:
                        result["persona"] = entity_summary or f"{entity_name} is a {entity_type}."
                    
                    return result
                    
                except json.JSONDecodeError as je:
                    logger.warning(f"JSONparsefail (attempt {attempt+1}): {str(je)[:80]}")
                    
                    # testfixrepeatJSON
                    result = self._try_fix_json(content, entity_name, entity_type, entity_summary)
                    if result.get("_fixed"):
                        del result["_fixed"]
                        return result
                    
                    last_error = je
                    
            except Exception as e:
                logger.warning(f"LLMinvokefail (attempt {attempt+1}): {str(e)[:80]}")
                last_error = e
                import time
                time.sleep(1 * (attempt + 1))  # numberexit
        
        logger.warning(f"LLM persona generation failed ({max_attempts} attempts): {last_error}; generating by rule")
        return self._generate_profile_rule_based(
            entity_name, entity_type, entity_summary, entity_attributes
        )
    
    def _fix_truncated_json(self, content: str) -> str:
        """Repair truncated JSON (output truncated by the max_tokens limit)."""
        import re
        
        # If the JSON is truncated, try to repair it
        content = content.strip()
        
        # calculatenotcombine
        open_braces = content.count('{') - content.count('}')
        open_brackets = content.count('[') - content.count(']')
        
        # checkwhetherhavenotcombinecharacterstring
        # Simple check: if there is no closing brace/bracket at the end, the string may be truncated
        if content and content[-1] not in '",}]':
            # testcombinecharacterstring
            content += '"'
        
        # combine
        content += ']' * open_brackets
        content += '}' * open_braces
        
        return content
    
    def _try_fix_json(self, content: str, entity_name: str, entity_type: str, entity_summary: str = "") -> Dict[str, Any]:
        """testfixrepeatbadJSON"""
        import re
        
        # 1. firsttestfixrepeatbytruncatesituation
        content = self._fix_truncated_json(content)
        
        # 2. testextractJSONpartial
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            json_str = json_match.group()
            
            # 3. ProcesscharacterstringMiddleswapgoquestion
            # foundhascharacterstringvalueandreplaceswapitsMiddleswapgo
            def fix_string_newlines(match):
                s = match.group(0)
                # replaceswapcharacterstringInternalactualswapgoforEmpty
                s = s.replace('\n', ' ').replace('\r', ' ')
                # replaceswapmanyremainderEmpty
                s = re.sub(r'\s+', ' ', s)
                return s
            
            # matchJSONcharacterstringvalue
            json_str = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', fix_string_newlines, json_str)
            
            # 4. testparse
            try:
                result = json.loads(json_str)
                result["_fixed"] = True
                return result
            except json.JSONDecodeError as e:
                # 5. If it still fails, try further repair
                try:
                    # removehascontrolcharacter
                    json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', json_str)
                    # replaceswaphaslinkcontinueEmpty
                    json_str = re.sub(r'\s+', ' ', json_str)
                    result = json.loads(json_str)
                    result["_fixed"] = True
                    return result
                except:
                    pass
        
        # 6. testfromcontentMiddleextractpartialinformation
        bio_match = re.search(r'"bio"\s*:\s*"([^"]*)"', content)
        persona_match = re.search(r'"persona"\s*:\s*"([^"]*)', content)  # cancanbytruncate
        
        bio = bio_match.group(1) if bio_match else (entity_summary[:200] if entity_summary else f"{entity_type}: {entity_name}")
        persona = persona_match.group(1) if persona_match else (entity_summary or f"{entity_name} is a {entity_type}.")
        
        # If meaningful content was extracted, mark for repair
        if bio_match or persona_match:
            logger.info(f"frombadJSONMiddleextractpartialinformation")
            return {
                "bio": bio,
                "persona": persona,
                "_fixed": True
            }
        
        # 7. If everything fails, return the base structure
        logger.warning(f"JSON repair failed; returning the base structure")
        return {
            "bio": entity_summary[:200] if entity_summary else f"{entity_type}: {entity_name}",
            "persona": entity_summary or f"{entity_name} is a {entity_type}."
        }
    
    def _get_system_prompt(self, is_individual: bool) -> str:
        """Get the system prompt."""
        base_prompt = (
            "You are a social media user persona generation expert. Generate a detailed, "
            "realistic persona for sentiment simulation, as comprehensive and realistic as "
            "possible. You must return valid JSON format; string values must not contain "
            "newlines. Write all output in English."
        )
        return base_prompt
    
    def _build_individual_persona_prompt(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str
    ) -> str:
        """Build the detailed persona prompt for an individual entity."""

        attrs_str = json.dumps(entity_attributes, ensure_ascii=False) if entity_attributes else "none"
        context_str = context[:3000] if context else "No additional context available"

        return f"""Generate a detailed social media user persona for the entity, as comprehensive and realistic as possible.

Entity name: {entity_name}
Entity type: {entity_type}
Entity summary: {entity_summary}
Entity attributes: {attrs_str}

Context information:
{context_str}

Please generate JSON containing the following fields:

1. bio: social media bio, 200 words
2. persona: detailed persona description (2000 words of plain text), must include:
      - basic information (age, education background, geographic location)
      - personal background (relevant history, relationship to the event, relationships with others)
      - traits (MBTI type, core values, emotional expression style)
      - social media behavior (posting frequency, content preferences, communication style, tone)
      - stance and viewpoints (depth of stance on key questions; can be expressed through pro/con or emotional content)
      - distinctive features (personality, special background history, personal preferences)
      - personal memory (a key part of the persona; should relate this person to the event, showing this person's actions and reactions within the event)
3. age: age in years (must be a whole number)
4. gender: must be one of: "male" or "female"
5. mbti: MBTI type (e.g. INTJ, ENFP, etc.)
6. country: Country name in English (e.g. "United States")
7. profession: the person's occupation
8. interested_topics: an array of topics this person cares about

Requirements:
- All field values must be strings or numbers; do not use newlines
- persona must be a single continuous block of text
- Write all output in English (the gender field must use male/female)
- Content must stay consistent with the entity information provided above
- age must be a valid whole number; gender must be "male" or "female"
"""

    def _build_group_persona_prompt(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str
    ) -> str:
        """Build the detailed profile prompt for a group/organization entity."""

        attrs_str = json.dumps(entity_attributes, ensure_ascii=False) if entity_attributes else "none"
        context_str = context[:3000] if context else "No additional context available"

        return f"""Generate a detailed social media profile for a group/organization entity, as comprehensive and realistic as possible.

Entity name: {entity_name}
Entity type: {entity_type}
Entity summary: {entity_summary}
Entity attributes: {attrs_str}

Context information:
{context_str}

Please generate JSON containing the following fields:

1. bio: official bio, 200 words, professionally worded
2. persona: detailed profile description (2000 words of plain text), must include:
      - organization basic info (official name, organization type, founding background, main functions)
      - key features (type, target audience, core functions)
      - posting style (tone, daily expression habits, forbidden topics)
      - posting content focus (content types, posting frequency, active time segments)
      - stance depth (official stance on core questions, attitude toward the process)
      - special notes (overall group character, operational habits)
      - organizational memory (a key part of the profile; should relate this organization to the event, showing this organization's actions and reactions within the event)
3. age: fixed at 30 (the organization's virtual age)
4. gender: fixed as "other" (organizations use "other" instead of a person's gender)
5. mbti: MBTI type, used to describe style (e.g. ISTJ indicates strict and conservative)
6. country: Country name in English (e.g. "United States")
7. profession: a short description of what the organization does
8. interested_topics: an array of topics this organization focuses on

Requirements:
- All field values must be strings or numbers; null values are not allowed
- persona must be a single coherent text description; do not use newlines
- Write all output in English (the gender field must use "other")
- age must be the whole number 30; gender must be the string "other"
- The organization's messaging must stay consistent with its stated position"""
    
    def _generate_profile_rule_based(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Use rules to generate basic person settings"""
        
        # according toEntityTypeGeneratedifferentpersonset
        entity_type_lower = entity_type.lower()
        
        if entity_type_lower in ["student", "alumni"]:
            return {
                "bio": f"{entity_type} with interests in academics and social issues.",
                "persona": f"{entity_name} is a {entity_type.lower()} who is actively engaged in academic and social discussions. They enjoy sharing perspectives and connecting with peers.",
                "age": random.randint(18, 30),
                "gender": random.choice(["male", "female"]),
                "mbti": random.choice(self.MBTI_TYPES),
                "country": random.choice(self.COUNTRIES),
                "profession": "Student",
                "interested_topics": ["Education", "Social Issues", "Technology"],
            }
        
        elif entity_type_lower in ["publicfigure", "expert", "faculty"]:
            return {
                "bio": f"Expert and thought leader in their field.",
                "persona": f"{entity_name} is a recognized {entity_type.lower()} who shares insights and opinions on important matters. They are known for their expertise and influence in public discourse.",
                "age": random.randint(35, 60),
                "gender": random.choice(["male", "female"]),
                "mbti": random.choice(["ENTJ", "INTJ", "ENTP", "INTP"]),
                "country": random.choice(self.COUNTRIES),
                "profession": entity_attributes.get("occupation", "Expert"),
                "interested_topics": ["Politics", "Economics", "Culture & Society"],
            }
        
        elif entity_type_lower in ["mediaoutlet", "socialmediaplatform"]:
            return {
                "bio": f"Official account for {entity_name}. News and updates.",
                "persona": f"{entity_name} is a media entity that reports news and facilitates public discourse. The account shares timely updates and engages with the audience on current events.",
                "age": 30,  # agencyvirtualyear
                "gender": "other",  # agencyuseother
                "mbti": "ISTJ",  # organization style: strict and conservative
                "country": "middle",
                "profession": "Media",
                "interested_topics": ["General News", "Current Events", "Public Affairs"],
            }
        
        elif entity_type_lower in ["university", "governmentagency", "ngo", "organization"]:
            return {
                "bio": f"Official account of {entity_name}.",
                "persona": f"{entity_name} is an institutional entity that communicates official positions, announcements, and engages with stakeholders on relevant matters.",
                "age": 30,  # agencyvirtualyear
                "gender": "other",  # agencyuseother
                "mbti": "ISTJ",  # organization style: strict and conservative
                "country": "middle",
                "profession": entity_type,
                "interested_topics": ["Public Policy", "Community", "Official Announcements"],
            }
        
        else:
            # Defaultpersonset
            return {
                "bio": entity_summary[:150] if entity_summary else f"{entity_type}: {entity_name}",
                "persona": entity_summary or f"{entity_name} is a {entity_type.lower()} participating in social discussions.",
                "age": random.randint(25, 50),
                "gender": random.choice(["male", "female"]),
                "mbti": random.choice(self.MBTI_TYPES),
                "country": random.choice(self.COUNTRIES),
                "profession": entity_type,
                "interested_topics": ["General", "Social Issues"],
            }
    
    def set_graph_id(self, graph_id: str):
        """SettingsGraphIDuseatZepretrieve"""
        self.graph_id = graph_id
    
    def generate_profiles_from_entities(
        self,
        entities: List[EntityNode],
        use_llm: bool = True,
        progress_callback: Optional[callable] = None,
        graph_id: Optional[str] = None,
        parallel_count: int = 5,
        realtime_output_path: Optional[str] = None,
        output_platform: str = "reddit"
    ) -> List[OasisAgentProfile]:
        """
        Batch-generate agent profiles from entities (supports parallel generation)
        
        Args:
            entities: Entitylist
            use_llm: whether use LLM to generate detailed person settings
            progress_callback: enterdepthreturnFunction (current, total, message)
            graph_id: graph ID, used for Zep retrieval to obtain richer context
            parallel_count: number to generate in parallel, default 5
            realtime_output_path: real-time output file path (if set, writes one entry per generated profile)
            output_platform: outputPlatformformat ("reddit" or "twitter")
            
        Returns:
            Agent Profilelist
        """
        import concurrent.futures
        from threading import Lock
        
        # Settingsgraph_iduseatZepretrieve
        if graph_id:
            self.graph_id = graph_id
        
        total = len(entities)
        profiles = [None] * total  # preminutematchlistkeepmaintainsequence
        completed_count = [0]  # uselisttoatpackMiddlemodify
        lock = Lock()
        
        # Real-timeWriteFilehelpFunction
        def save_profiles_realtime():
            """Real-timeSaveGenerate profiles toFile"""
            if not realtime_output_path:
                return
            
            with lock:
                # filteroutGenerate profiles
                existing_profiles = [p for p in profiles if p is not None]
                if not existing_profiles:
                    return
                
                try:
                    if output_platform == "reddit":
                        # Reddit JSON format
                        profiles_data = [p.to_reddit_format() for p in existing_profiles]
                        with open(realtime_output_path, 'w', encoding='utf-8') as f:
                            json.dump(profiles_data, f, ensure_ascii=False, indent=2)
                    else:
                        # Twitter CSV format
                        import csv
                        profiles_data = [p.to_twitter_format() for p in existing_profiles]
                        if profiles_data:
                            fieldnames = list(profiles_data[0].keys())
                            with open(realtime_output_path, 'w', encoding='utf-8', newline='') as f:
                                writer = csv.DictWriter(f, fieldnames=fieldnames)
                                writer.writeheader()
                                writer.writerows(profiles_data)
                except Exception as e:
                    logger.warning(f"Real-timeSave profiles fail: {e}")
        
        def generate_single_profile(idx: int, entity: EntityNode) -> tuple:
            """GeneratesingleprofileworkFunction"""
            entity_type = entity.get_entity_type() or "Entity"
            
            try:
                profile = self.generate_profile_from_entity(
                    entity=entity,
                    user_id=idx,
                    use_llm=use_llm
                )
                
                # Real-timeoutputGeneratepersonsettocontrolsumlog
                self._print_generated_profile(entity.name, entity_type, profile)
                
                return idx, profile, None
                
            except Exception as e:
                logger.error(f"GenerateEntity {entity.name} personsetfail: {str(e)}")
                # createabaseprofile
                fallback_profile = OasisAgentProfile(
                    user_id=idx,
                    user_name=self._generate_username(entity.name),
                    name=entity.name,
                    bio=f"{entity_type}: {entity.name}",
                    persona=entity.summary or f"A participant in social discussions.",
                    source_entity_uuid=entity.uuid,
                    source_entity_type=entity_type,
                )
                return idx, fallback_profile, str(e)
        
        logger.info(f"Starting parallel generation of {total} agent personas (parallel count: {parallel_count})...")
        print(f"\n{'='*60}")
        print(f"Starting agent persona generation - {total} entities, parallel count: {parallel_count}")
        print(f"{'='*60}\n")
        
        # usethreadprogramandgoexecute
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_count) as executor:
            # givehastask
            future_to_entity = {
                executor.submit(generate_single_profile, idx, entity): (idx, entity)
                for idx, entity in enumerate(entities)
            }
            
            # acceptcollectresult
            for future in concurrent.futures.as_completed(future_to_entity):
                idx, entity = future_to_entity[future]
                entity_type = entity.get_entity_type() or "Entity"
                
                try:
                    result_idx, profile, error = future.result()
                    profiles[result_idx] = profile
                    
                    with lock:
                        completed_count[0] += 1
                        current = completed_count[0]
                    
                    # Real-timeWriteFile
                    save_profiles_realtime()
                    
                    if progress_callback:
                        progress_callback(
                            current, 
                            total, 
                            f"completed {current}/{total}: {entity.name} ({entity_type})"
                        )
                    
                    if error:
                        logger.warning(f"[{current}/{total}] {entity.name} useprepareusepersonset: {error}")
                    else:
                        logger.info(f"[{current}/{total}] successGeneratepersonset: {entity.name} ({entity_type})")
                        
                except Exception as e:
                    logger.error(f"ProcessEntity {entity.name} hourhappenException: {str(e)}")
                    with lock:
                        completed_count[0] += 1
                    profiles[idx] = OasisAgentProfile(
                        user_id=idx,
                        user_name=self._generate_username(entity.name),
                        name=entity.name,
                        bio=f"{entity_type}: {entity.name}",
                        persona=entity.summary or "A participant in social discussions.",
                        source_entity_uuid=entity.uuid,
                        source_entity_type=entity_type,
                    )
                    # Write to file in real time (even for fallback personas)
                    save_profiles_realtime()
        
        print(f"\n{'='*60}")
        print(f"Persona generation complete! Generated {len([p for p in profiles if p])} agents")
        print(f"{'='*60}\n")
        
        return profiles
    
    def _print_generated_profile(self, entity_name: str, entity_type: str, profile: OasisAgentProfile):
        """Output the generated persona to the console in real time (complete content, not truncated)."""
        separator = "-" * 70
        
        # Build the complete output content (not truncated)
        topics_str = ', '.join(profile.interested_topics) if profile.interested_topics else 'none'
        
        output_lines = [
            f"\n{separator}",
            f"[Generate] {entity_name} ({entity_type})",
            f"{separator}",
            f"username: {profile.user_name}",
            f"",
            f"[Profile]",
            f"{profile.bio}",
            f"",
            f"[Detailed Persona]",
            f"{profile.persona}",
            f"",
            f"[Basic Attributes]",
            f"year: {profile.age} | part: {profile.gender} | MBTI: {profile.mbti}",
            f": {profile.profession} | Country: {profile.country}",
            f"chatquestion: {topics_str}",
            separator
        ]
        
        output = "\n".join(output_lines)
        
        # Only output to the console (repeatedly; the logger does not output the full content again)
        print(output)
    
    def save_profiles(
        self,
        profiles: List[OasisAgentProfile],
        file_path: str,
        platform: str = "reddit"
    ):
        """
        Save profiles to a file (select the correct format based on the platform)
        
        OASIS platform format requirements:
        - Twitter: CSVformat
        - Reddit: JSONformat
        
        Args:
            profiles: Profilelist
            file_path: FilePath
            platform: PlatformType ("reddit" or "twitter")
        """
        if platform == "twitter":
            self._save_twitter_csv(profiles, file_path)
        else:
            self._save_reddit_json(profiles, file_path)
    
    def _save_twitter_csv(self, profiles: List[OasisAgentProfile], file_path: str):
        """
        Save Twitter profiles in CSV format (per the official OASIS requirements)
        
        OASIS Twitter-required CSV fields:
        - user_id: user ID (sequential from 0 based on CSV order)
        - name: userrealactualsurnamename
        - username: SystemMiddleusername
        - user_char: detailed persona description (injected into the LLM system prompt to guide agent behavior)
        - description: short public bio (shown on the user's profile page)
        
        user_char vs description distinction:
        - user_char: for internal use, in the LLM system prompt; determines how the agent thinks and acts
        - description: for external use; visible to other users
        """
        import csv
        
        # keepFilenameare.csv
        if not file_path.endswith('.csv'):
            file_path = file_path.replace('.json', '.csv')
        
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # WriteOASISwantrequesttablehead
            headers = ['user_id', 'name', 'username', 'user_char', 'description']
            writer.writerow(headers)
            
            # WriteDatago
            for idx, profile in enumerate(profiles):
                # user_char: complete persona (bio + persona), used for the LLM system prompt
                user_char = profile.bio
                if profile.persona and profile.persona != profile.bio:
                    user_char = f"{profile.bio} {profile.persona}"
                # Process newlines (replace with spaces in the CSV)
                user_char = user_char.replace('\n', ' ').replace('\r', ' ')
                
                # description: short, for external use
                description = profile.bio.replace('\n', ' ').replace('\r', ' ')
                
                row = [
                    idx,                    # user_id: from0startsequenceID
                    profile.name,           # name: realactualsurnamename
                    profile.user_name,      # username: username
                    user_char,              # user_char: complete persona (internal LLM use)
                    description             # description: short (external use)
                ]
                writer.writerow(row)
        
        logger.info(f"Save {len(profiles)} Twitter Profileto {file_path} (OASIS CSVformat)")
    
    def _normalize_gender(self, gender: Optional[str]) -> str:
        """
        allowchemgenderwordsegmentforOASISwantrequestdocformat
        
        OASISwantrequest: male, female, other
        """
        if not gender:
            return "other"
        
        gender_lower = gender.lower().strip()
        
        # Middledoc
        gender_map = {
            "": "male",
            "daughter": "female",
            "agency": "other",
            "itshe": "other",
            # dochave
            "male": "male",
            "female": "female",
            "other": "other",
        }
        
        return gender_map.get(gender_lower, "other")
    
    def _save_reddit_json(self, profiles: List[OasisAgentProfile], file_path: str):
        """
        SaveReddit ProfileforJSONformat
        
        Use the to_reddit_format() method to unify the format so OASIS can read it correctly.
        Must contain the user_id field; this is the match key for OASIS agent_graph.get_agent()!
        
        Required fields:
        - user_id: user ID (whole number, used to match poster_agent_id in initial_posts)
        - username: username
        - name: Name
        - bio: 
        - persona: detailedpersonset
        - age: age in years (whole number)
        - gender: "male", "female", or "other"
        - mbti: MBTIType
        - country: Country
        """
        data = []
        for idx, profile in enumerate(profiles):
            # useand to_reddit_format() oneformat
            item = {
                "user_id": profile.user_id if profile.user_id is not None else idx,  # key: must contain user_id
                "username": profile.user_name,
                "name": profile.name,
                "bio": profile.bio[:150] if profile.bio else f"{profile.name}",
                "persona": profile.persona or f"{profile.name} is a participant in social discussions.",
                "karma": profile.karma if profile.karma else 1000,
                "created_at": profile.created_at,
                # OASISmustneedwordsegment - keephaveDefaultvalue
                "age": profile.age if profile.age else 30,
                "gender": self._normalize_gender(profile.gender),
                "mbti": profile.mbti if profile.mbti else "ISTJ",
                "country": profile.country if profile.country else "middle",
            }
            
            # Optional field
            if profile.profession:
                item["profession"] = profile.profession
            if profile.interested_topics:
                item["interested_topics"] = profile.interested_topics
            
            data.append(item)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Saved {len(profiles)} Reddit profiles to {file_path} (JSON format, includes user_id field)")
    
    # Keep the old method name as an alias for backward compatibility
    def save_profiles_to_json(
        self,
        profiles: List[OasisAgentProfile],
        file_path: str,
        platform: str = "reddit"
    ):
        """[abandon] pleaseuse save_profiles() method"""
        logger.warning("save_profiles_to_json is deprecated; please use the save_profiles method")
        self.save_profiles(profiles, file_path, platform)

