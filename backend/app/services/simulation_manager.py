"""
OASISsimulatemanageer
manageTwittersumRedditdoublePlatformandgosimulate
usepresetfootthis + LLMIntelligenceGenerateConfigurationParameter
"""

import os
import json
import shutil
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..config import Config
from ..utils.logger import get_logger
from .zep_entity_reader import ZepEntityReader, FilteredEntities
from .oasis_profile_generator import OasisProfileGenerator, OasisAgentProfile
from .simulation_config_generator import SimulationConfigGenerator, SimulationParameters
from .domain_designer import DomainDesigner
from .domain_profile_adapter import write_profile_artifacts

logger = get_logger('mirofish.simulation')


class SimulationStatus(str, Enum):
    """simulateStatus"""
    CREATED = "created"
    PREPARING = "preparing"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"      # simulatebyhandmovestop
    COMPLETED = "completed"  # simulateselfthencomplete
    FAILED = "failed"


class PlatformType(str, Enum):
    """PlatformType"""
    TWITTER = "twitter"
    REDDIT = "reddit"


@dataclass
class SimulationState:
    """simulateStatus"""
    simulation_id: str
    project_id: str
    graph_id: str
    domain: str = "social"
    domain_source: str = "builtin"
    domain_reasoning: str = ""
    
    # Compatibility aliases for the old two-track UI
    enable_twitter: bool = True
    enable_reddit: bool = True
    
    # Status
    status: SimulationStatus = SimulationStatus.CREATED
    
    # allowpreparestageData
    entities_count: int = 0
    profiles_count: int = 0
    entity_types: List[str] = field(default_factory=list)
    
    # ConfigurationGenerateinformation
    config_generated: bool = False
    config_reasoning: str = ""
    
    # RunhourData
    current_round: int = 0
    twitter_status: str = "not_started"
    reddit_status: str = "not_started"
    
    # Timestamp
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Errorinformation
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Complete status dict (for internal use)."""
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "domain": self.domain,
            "domain_source": self.domain_source,
            "domain_reasoning": self.domain_reasoning,
            "enable_twitter": self.enable_twitter,
            "enable_reddit": self.enable_reddit,
            "status": self.status.value,
            "entities_count": self.entities_count,
            "profiles_count": self.profiles_count,
            "entity_types": self.entity_types,
            "config_generated": self.config_generated,
            "config_reasoning": self.config_reasoning,
            "current_round": self.current_round,
            "twitter_status": self.twitter_status,
            "reddit_status": self.reddit_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
        }
    
    def to_simple_dict(self) -> Dict[str, Any]:
        """Simplified status dict (for API responses)."""
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "status": self.status.value,
            "entities_count": self.entities_count,
            "profiles_count": self.profiles_count,
            "entity_types": self.entity_types,
            "config_generated": self.config_generated,
            "error": self.error,
        }


class SimulationManager:
    """
    simulatemanageer
    
    coreFeatures:
    1. fromZepGraphReadEntityandfilter
    2. GenerateOASIS Agent Profile
    3. useLLMIntelligenceGeneratesimulateConfigurationParameter
    4. allowpreparepresetfootthisplaceneedhasFile
    """
    
    # simulateDatastorestorageDirectory
    SIMULATION_DATA_DIR = os.path.join(
        os.path.dirname(__file__), 
        '../../uploads/simulations'
    )
    
    def __init__(self):
        # keepDirectory exists
        os.makedirs(self.SIMULATION_DATA_DIR, exist_ok=True)
        
        # InternalstoreMiddlesimulateStatusslowstore
        self._simulations: Dict[str, SimulationState] = {}
    
    def _get_simulation_dir(self, simulation_id: str) -> str:
        """GetsimulateDataDirectory"""
        sim_dir = os.path.join(self.SIMULATION_DATA_DIR, simulation_id)
        os.makedirs(sim_dir, exist_ok=True)
        return sim_dir
    
    def _save_simulation_state(self, state: SimulationState):
        """SavesimulateStatustoFile"""
        sim_dir = self._get_simulation_dir(state.simulation_id)
        state_file = os.path.join(sim_dir, "state.json")
        
        state.updated_at = datetime.now().isoformat()
        
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
        
        self._simulations[state.simulation_id] = state
    
    def _load_simulation_state(self, simulation_id: str) -> Optional[SimulationState]:
        """fromFileLoadsimulateStatus"""
        if simulation_id in self._simulations:
            return self._simulations[simulation_id]
        
        sim_dir = self._get_simulation_dir(simulation_id)
        state_file = os.path.join(sim_dir, "state.json")
        
        if not os.path.exists(state_file):
            return None
        
        with open(state_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        state = SimulationState(
            simulation_id=simulation_id,
            project_id=data.get("project_id", ""),
            graph_id=data.get("graph_id", ""),
            domain=data.get("domain", "social"),
            domain_source=data.get("domain_source", "builtin"),
            domain_reasoning=data.get("domain_reasoning", ""),
            enable_twitter=data.get("enable_twitter", True),
            enable_reddit=data.get("enable_reddit", True),
            status=SimulationStatus(data.get("status", "created")),
            entities_count=data.get("entities_count", 0),
            profiles_count=data.get("profiles_count", 0),
            entity_types=data.get("entity_types", []),
            config_generated=data.get("config_generated", False),
            config_reasoning=data.get("config_reasoning", ""),
            current_round=data.get("current_round", 0),
            twitter_status=data.get("twitter_status", "not_started"),
            reddit_status=data.get("reddit_status", "not_started"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            error=data.get("error"),
        )
        
        self._simulations[simulation_id] = state
        return state
    
    def create_simulation(
        self,
        project_id: str,
        graph_id: str,
        enable_twitter: bool = True,
        enable_reddit: bool = True,
    ) -> SimulationState:
        """
        createNewsimulate
        
        Args:
            project_id: itemitemID
            graph_id: ZepGraphID
            enable_twitter: whetherEnableTwittersimulate
            enable_reddit: whetherEnableRedditsimulate
            
        Returns:
            SimulationState
        """
        import uuid
        simulation_id = f"sim_{uuid.uuid4().hex[:12]}"
        
        state = SimulationState(
            simulation_id=simulation_id,
            project_id=project_id,
            graph_id=graph_id,
            enable_twitter=enable_twitter,
            enable_reddit=enable_reddit,
            status=SimulationStatus.CREATED,
        )
        
        self._save_simulation_state(state)
        logger.info(f"createsimulate: {simulation_id}, project={project_id}, graph={graph_id}")
        
        return state
    
    def prepare_simulation(
        self,
        simulation_id: str,
        simulation_requirement: str,
        document_text: str,
        defined_entity_types: Optional[List[str]] = None,
        use_llm_for_profiles: bool = True,
        progress_callback: Optional[callable] = None,
        parallel_profile_count: int = 3,
        force_domain: Optional[str] = None
    ) -> SimulationState:
        """
        Prepare the simulation environment (fully automated pipeline).
        
        Steps:
        1. fromZepGraphReadandfilterEntity
        2. Generate an OASIS agent profile for each entity (optional LLM enhancement, supports parallel generation)
        3. Use the LLM to intelligently generate simulation configuration parameters (time, activity level, posting frequency, etc.)
        4. SaveConfigurationFilesumProfileFile
        5. copypresetfootthistosimulateDirectory
        
        Args:
            simulation_id: simulateID
            simulation_requirement: description of the simulation requirement (used by the LLM to generate configuration)
            document_text: original document content (used by the LLM to understand the context)
            defined_entity_types: predefined entity types (optional)
            use_llm_for_profiles: whetheruseLLMGeneratedetailedpersonset
            progress_callback: enterdepthreturnFunction (stage, progress, message)
            parallel_profile_count: number of profiles to generate in parallel, default 3
            
        Returns:
            SimulationState
        """
        state = self._load_simulation_state(simulation_id)
        if not state:
            raise ValueError(f"simulateNot Exist: {simulation_id}")
        
        try:
            state.status = SimulationStatus.PREPARING
            self._save_simulation_state(state)
            
            sim_dir = self._get_simulation_dir(simulation_id)

            # Choose the simulation domain before generating profiles. The same
            # graph entities can participate in a market, allocation, social,
            # or LLM-designed world; the domain controls actions and metrics.
            if progress_callback:
                progress_callback("domain", 0, "Selecting simulation domain...")
            domain_result = DomainDesigner().design(
                simulation_requirement=simulation_requirement,
                document_text=document_text,
                force_domain=force_domain,
            )
            state.domain = domain_result["domain"]
            state.domain_source = domain_result["source"]
            state.domain_reasoning = domain_result.get("reasoning", "")
            domain_pack_path = os.path.join(sim_dir, "domain_pack.json")
            with open(domain_pack_path, "w", encoding="utf-8") as f:
                json.dump(domain_result["pack"], f, ensure_ascii=False, indent=2)
            self._save_simulation_state(state)
            if progress_callback:
                progress_callback("domain", 100, f"Using {state.domain} domain ({state.domain_source})")
            
            # ========== stage1: ReadandfilterEntity ==========
            if progress_callback:
                progress_callback("reading", 0, "positiveatlinkconnectZepGraph...")
            
            reader = ZepEntityReader()
            
            if progress_callback:
                progress_callback("reading", 30, "positiveatReadnodeData...")
            
            filtered = reader.filter_defined_entities(
                graph_id=state.graph_id,
                defined_entity_types=defined_entity_types,
                enrich_with_edges=True
            )
            
            state.entities_count = filtered.filtered_count
            state.entity_types = list(filtered.entity_types)
            
            if progress_callback:
                progress_callback(
                    "reading", 100, 
                    f"Completed, {filtered.filtered_count} entities",
                    current=filtered.filtered_count,
                    total=filtered.filtered_count
                )
            
            if filtered.filtered_count == 0:
                state.status = SimulationStatus.FAILED
                state.error = "No entities matching the criteria were found; please verify the graph was built correctly"
                self._save_simulation_state(state)
                return state
            
            # ========== stage2: GenerateAgent Profile ==========
            total_entities = len(filtered.entities)
            
            if progress_callback:
                progress_callback(
                    "generating_profiles", 0, 
                    "startGenerate...",
                    current=0,
                    total=total_entities
                )
            
            # Pass in graph_id to enable Zep retrieval and obtain richer context
            generator = OasisProfileGenerator(graph_id=state.graph_id)
            
            def profile_progress(current, total, msg):
                if progress_callback:
                    progress_callback(
                        "generating_profiles", 
                        int(current / total * 100), 
                        msg,
                        current=current,
                        total=total,
                        item_name=msg
                    )
            
            # Set the real-time save file path (prefer the Reddit JSON format)
            realtime_output_path = None
            realtime_platform = "reddit"
            if state.enable_reddit:
                realtime_output_path = os.path.join(sim_dir, "reddit_profiles.json")
                realtime_platform = "reddit"
            elif state.enable_twitter:
                realtime_output_path = os.path.join(sim_dir, "twitter_profiles.csv")
                realtime_platform = "twitter"
            
            profiles = generator.generate_profiles_from_entities(
                entities=filtered.entities,
                use_llm=use_llm_for_profiles,
                progress_callback=profile_progress,
                graph_id=state.graph_id,  # transferingraph_iduseatZepretrieve
                parallel_count=parallel_profile_count,  # andgoGeneratenumbermeasure
                realtime_output_path=realtime_output_path,  # Real-timeSavePath
                output_platform=realtime_platform  # outputformat
            )
            
            state.profiles_count = len(profiles)

            # The generic engine consumes one stable JSON profile file. Keep the
            # legacy platform files too because existing API clients use them.
            write_profile_artifacts(profiles, sim_dir, legacy_generator=generator)
            
            # Save profile files (Twitter uses CSV format, Reddit uses JSON format)
            # Reddit profiles are already saved in real time during generation; save once more here for completeness
            if progress_callback:
                progress_callback(
                    "generating_profiles", 95, 
                    "SaveProfileFile...",
                    current=total_entities,
                    total=total_entities
                )
            
            if state.enable_reddit:
                generator.save_profiles(
                    profiles=profiles,
                    file_path=os.path.join(sim_dir, "reddit_profiles.json"),
                    platform="reddit"
                )
            
            if state.enable_twitter:
                # Twitter uses CSV format! This is required by OASIS
                generator.save_profiles(
                    profiles=profiles,
                    file_path=os.path.join(sim_dir, "twitter_profiles.csv"),
                    platform="twitter"
                )
            
            if progress_callback:
                progress_callback(
                    "generating_profiles", 100, 
                    f"Completed, {len(profiles)} profiles",
                    current=len(profiles),
                    total=len(profiles)
                )
            
            # ========== stage3: LLMIntelligenceGeneratesimulateConfiguration ==========
            if progress_callback:
                progress_callback(
                    "generating_config", 0, 
                    "positiveatanalyzesimulaterequirement...",
                    current=0,
                    total=3
                )
            
            config_generator = SimulationConfigGenerator()
            
            if progress_callback:
                progress_callback(
                    "generating_config", 30, 
                    "positiveatinvokeLLMGenerateConfiguration...",
                    current=1,
                    total=3
                )
            
            sim_params = config_generator.generate_config(
                simulation_id=simulation_id,
                project_id=state.project_id,
                graph_id=state.graph_id,
                simulation_requirement=simulation_requirement,
                document_text=document_text,
                entities=filtered.entities,
                enable_twitter=state.enable_twitter,
                enable_reddit=state.enable_reddit,
                domain=state.domain,
                domain_pack_path=domain_pack_path,
                domain_reasoning=state.domain_reasoning,
                tracks=(json.load(open(domain_pack_path, "r", encoding="utf-8")).get("tracks") or ["main"])
            )
            
            if progress_callback:
                progress_callback(
                    "generating_config", 70, 
                    "positiveatSaveConfigurationFile...",
                    current=2,
                    total=3
                )
            
            # SaveConfigurationFile
            config_path = os.path.join(sim_dir, "simulation_config.json")
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(sim_params.to_json())
            
            state.config_generated = True
            state.config_reasoning = sim_params.generation_reasoning
            
            if progress_callback:
                progress_callback(
                    "generating_config", 100, 
                    "ConfigurationGeneratecomplete",
                    current=3,
                    total=3
                )
            
            # Note: runner scripts remain in the backend/scripts/ directory and are NOT copied to the simulation directory
            # When the simulation is launched, simulation_runner will run the scripts from the scripts/ directory
            
            # moreNewStatus
            state.status = SimulationStatus.READY
            self._save_simulation_state(state)
            
            logger.info(f"simulateallowpreparecomplete: {simulation_id}, "
                       f"entities={state.entities_count}, profiles={state.profiles_count}")
            
            return state
            
        except Exception as e:
            logger.error(f"simulateallowpreparefail: {simulation_id}, error={str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            state.status = SimulationStatus.FAILED
            state.error = str(e)
            self._save_simulation_state(state)
            raise
    
    def get_simulation(self, simulation_id: str) -> Optional[SimulationState]:
        """GetsimulateStatus"""
        return self._load_simulation_state(simulation_id)
    
    def list_simulations(self, project_id: Optional[str] = None) -> List[SimulationState]:
        """columnouthassimulate"""
        simulations = []
        
        if os.path.exists(self.SIMULATION_DATA_DIR):
            for sim_id in os.listdir(self.SIMULATION_DATA_DIR):
                # Skip hidden files (e.g. .DS_Store) and non-directory entries
                sim_path = os.path.join(self.SIMULATION_DATA_DIR, sim_id)
                if sim_id.startswith('.') or not os.path.isdir(sim_path):
                    continue
                
                state = self._load_simulation_state(sim_id)
                if state:
                    if project_id is None or state.project_id == project_id:
                        simulations.append(state)
        
        return simulations
    
    def get_profiles(self, simulation_id: str, platform: str = "reddit") -> List[Dict[str, Any]]:
        """GetsimulateAgent Profile"""
        state = self._load_simulation_state(simulation_id)
        if not state:
            raise ValueError(f"simulateNot Exist: {simulation_id}")
        
        sim_dir = self._get_simulation_dir(simulation_id)
        profile_path = os.path.join(sim_dir, f"{platform}_profiles.json")
        
        if not os.path.exists(profile_path):
            return []
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get_simulation_config(self, simulation_id: str) -> Optional[Dict[str, Any]]:
        """GetsimulateConfiguration"""
        sim_dir = self._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        
        if not os.path.exists(config_path):
            return None
        
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get_run_instructions(self, simulation_id: str) -> Dict[str, str]:
        """GetRunsaybright"""
        sim_dir = self._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        scripts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../scripts'))
        
        return {
            "simulation_dir": sim_dir,
            "scripts_dir": scripts_dir,
            "config_file": config_path,
            "commands": {
                "twitter": f"python {scripts_dir}/run_twitter_simulation.py --config {config_path}",
                "reddit": f"python {scripts_dir}/run_reddit_simulation.py --config {config_path}",
                "parallel": f"python {scripts_dir}/run_parallel_simulation.py --config {config_path}",
            },
            "instructions": (
                f"1. activatecondaEnvironment: conda activate MicroFish\n"
                f"2. Runsimulate (footthisbitat {scripts_dir}):\n"
                f"   - aloneRunTwitter: python {scripts_dir}/run_twitter_simulation.py --config {config_path}\n"
                f"   - aloneRunReddit: python {scripts_dir}/run_reddit_simulation.py --config {config_path}\n"
                f"   - andgoRundoublePlatform: python {scripts_dir}/run_parallel_simulation.py --config {config_path}"
            )
        }
