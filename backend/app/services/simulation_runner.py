"""
OASISsimulateRuner
Runs the simulation and records each agent action, with real-time status monitoring
"""

import os
import sys
import json
import time
import asyncio
import threading
import subprocess
import signal
import atexit
import shutil
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from queue import Queue

from ..config import Config
from ..utils.logger import get_logger
from .zep_graph_memory_updater import ZepGraphMemoryManager
from .simulation_ipc import SimulationIPCClient, CommandType, IPCResponse

logger = get_logger('mirofish.simulation_runner')

# MarkwhetherregisterCleanupFunction
_cleanup_registered = False

# PlatformDetect
IS_WINDOWS = sys.platform == 'win32'


class RunnerStatus(str, Enum):
    """RunerStatus"""
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentAction:
    """AgentActionRecord"""
    round_num: int
    timestamp: str
    platform: str  # compatibility alias; generic runs use the track name
    agent_id: int
    agent_name: str
    action_type: str  # domain-pack verb
    action_args: Dict[str, Any] = field(default_factory=dict)
    result: Optional[str] = None
    success: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "round_num": self.round_num,
            "timestamp": self.timestamp,
            "platform": self.platform,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "action_type": self.action_type,
            "action_args": self.action_args,
            "result": self.result,
            "success": self.success,
        }


@dataclass
class RoundSummary:
    """eachroundwant"""
    round_num: int
    start_time: str
    end_time: Optional[str] = None
    simulated_hour: int = 0
    twitter_actions: int = 0
    reddit_actions: int = 0
    active_agents: List[int] = field(default_factory=list)
    actions: List[AgentAction] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "round_num": self.round_num,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "simulated_hour": self.simulated_hour,
            "twitter_actions": self.twitter_actions,
            "reddit_actions": self.reddit_actions,
            "active_agents": self.active_agents,
            "actions_count": len(self.actions),
            "actions": [a.to_dict() for a in self.actions],
        }


@dataclass
class SimulationRunState:
    """Simulation run status (real-time)."""
    simulation_id: str
    runner_status: RunnerStatus = RunnerStatus.IDLE
    
    # enterdepthinformation
    current_round: int = 0
    total_rounds: int = 0
    simulated_hours: int = 0
    total_simulation_hours: int = 0
    
    # Independent rounds and simulated time per platform (for dual-platform display)
    twitter_current_round: int = 0
    reddit_current_round: int = 0
    twitter_simulated_hours: int = 0
    reddit_simulated_hours: int = 0
    
    # Generic track status. The old twitter/reddit fields below remain as
    # compatibility aliases for existing API consumers.
    tracks: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    twitter_running: bool = False
    reddit_running: bool = False
    twitter_actions_count: int = 0
    reddit_actions_count: int = 0
    
    # Compatibility completion status (detected via simulation_end events).
    twitter_completed: bool = False
    reddit_completed: bool = False
    
    # Generic action count for the active domain.
    total_domain_actions: int = 0
    
    # eachroundwant
    rounds: List[RoundSummary] = field(default_factory=list)
    
    # Most recent action (for real-time frontend display)
    recent_actions: List[AgentAction] = field(default_factory=list)
    max_recent_actions: int = 50
    
    # Timestamp
    started_at: Optional[str] = None
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    
    # Errorinformation
    error: Optional[str] = None
    
    # Process ID (used for stopping)
    process_pid: Optional[int] = None
    
    def add_action(self, action: AgentAction):
        """addActiontomostnearActionlist"""
        self.recent_actions.insert(0, action)
        if len(self.recent_actions) > self.max_recent_actions:
            self.recent_actions = self.recent_actions[:self.max_recent_actions]
        
        self.total_domain_actions += 1
        track = self.tracks.setdefault(action.platform, {"actions_count": 0})
        track["actions_count"] = track.get("actions_count", 0) + 1

        # Keep the legacy counters meaningful for the original social tracks.
        if action.platform == "twitter":
            self.twitter_actions_count = self.tracks[action.platform]["actions_count"]
        elif action.platform == "reddit":
            self.reddit_actions_count = self.tracks[action.platform]["actions_count"]

        self.updated_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "simulation_id": self.simulation_id,
            "runner_status": self.runner_status.value,
            "current_round": self.current_round,
            "total_rounds": self.total_rounds,
            "simulated_hours": self.simulated_hours,
            "total_simulation_hours": self.total_simulation_hours,
            "progress_percent": round(self.current_round / max(self.total_rounds, 1) * 100, 1),
            # eachPlatformindependentroundsumTime
            "twitter_current_round": self.twitter_current_round,
            "reddit_current_round": self.reddit_current_round,
            "twitter_simulated_hours": self.twitter_simulated_hours,
            "reddit_simulated_hours": self.reddit_simulated_hours,
            "twitter_running": self.twitter_running,
            "reddit_running": self.reddit_running,
            "twitter_completed": self.twitter_completed,
            "reddit_completed": self.reddit_completed,
            "twitter_actions_count": self.twitter_actions_count,
            "reddit_actions_count": self.reddit_actions_count,
            "tracks": self.tracks,
            "total_domain_actions": self.total_domain_actions,
            "total_actions_count": self.total_domain_actions or (self.twitter_actions_count + self.reddit_actions_count),
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "process_pid": self.process_pid,
        }
    
    def to_detail_dict(self) -> Dict[str, Any]:
        """containmostnearActiondetailedinformation"""
        result = self.to_dict()
        result["recent_actions"] = [a.to_dict() for a in self.recent_actions]
        result["rounds_count"] = len(self.rounds)
        return result


class SimulationRunner:
    """
    simulateRuner
    
    Returns:
    1. atAfterenterprogramMiddleRunOASISsimulate
    2. Parse the run log, recording each agent action
    3. Real-timeStatusqueryconnectperson
    4. supportpause/stop/restoreoperate
    """
    
    # RunStatusstorestorageDirectory
    RUN_STATE_DIR = os.path.join(
        os.path.dirname(__file__),
        '../../uploads/simulations'
    )
    
    # footthisDirectory
    SCRIPTS_DIR = os.path.join(
        os.path.dirname(__file__),
        '../../scripts'
    )
    
    # InternalstoreMiddleRunStatus
    _run_states: Dict[str, SimulationRunState] = {}
    _processes: Dict[str, subprocess.Popen] = {}
    _action_queues: Dict[str, Queue] = {}
    _monitor_threads: Dict[str, threading.Thread] = {}
    _stdout_files: Dict[str, Any] = {}  # storestorage stdout Filesentence
    _stderr_files: Dict[str, Any] = {}  # storestorage stderr Filesentence
    
    # GraphmemorymoreNewConfiguration
    _graph_memory_enabled: Dict[str, bool] = {}  # simulation_id -> enabled
    
    @classmethod
    def get_run_state(cls, simulation_id: str) -> Optional[SimulationRunState]:
        """GetRunStatus"""
        if simulation_id in cls._run_states:
            return cls._run_states[simulation_id]
        
        # testfromFileLoad
        state = cls._load_run_state(simulation_id)
        if state:
            cls._run_states[simulation_id] = state
        return state
    
    @classmethod
    def _load_run_state(cls, simulation_id: str) -> Optional[SimulationRunState]:
        """fromFileLoadRunStatus"""
        state_file = os.path.join(cls.RUN_STATE_DIR, simulation_id, "run_state.json")
        if not os.path.exists(state_file):
            return None
        
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            state = SimulationRunState(
                simulation_id=simulation_id,
                runner_status=RunnerStatus(data.get("runner_status", "idle")),
                current_round=data.get("current_round", 0),
                total_rounds=data.get("total_rounds", 0),
                simulated_hours=data.get("simulated_hours", 0),
                total_simulation_hours=data.get("total_simulation_hours", 0),
                # eachPlatformindependentroundsumTime
                twitter_current_round=data.get("twitter_current_round", 0),
                reddit_current_round=data.get("reddit_current_round", 0),
                twitter_simulated_hours=data.get("twitter_simulated_hours", 0),
                reddit_simulated_hours=data.get("reddit_simulated_hours", 0),
                twitter_running=data.get("twitter_running", False),
                reddit_running=data.get("reddit_running", False),
                twitter_completed=data.get("twitter_completed", False),
                reddit_completed=data.get("reddit_completed", False),
                twitter_actions_count=data.get("twitter_actions_count", 0),
                reddit_actions_count=data.get("reddit_actions_count", 0),
                started_at=data.get("started_at"),
                updated_at=data.get("updated_at", datetime.now().isoformat()),
                completed_at=data.get("completed_at"),
                error=data.get("error"),
                process_pid=data.get("process_pid"),
            )
            
            # LoadmostnearAction
            actions_data = data.get("recent_actions", [])
            for a in actions_data:
                state.recent_actions.append(AgentAction(
                    round_num=a.get("round_num", 0),
                    timestamp=a.get("timestamp", ""),
                    platform=a.get("platform", ""),
                    agent_id=a.get("agent_id", 0),
                    agent_name=a.get("agent_name", ""),
                    action_type=a.get("action_type", ""),
                    action_args=a.get("action_args", {}),
                    result=a.get("result"),
                    success=a.get("success", True),
                ))
            
            return state
        except Exception as e:
            logger.error(f"LoadRunStatusfail: {str(e)}")
            return None
    
    @classmethod
    def _save_run_state(cls, state: SimulationRunState):
        """SaveRunStatustoFile"""
        sim_dir = os.path.join(cls.RUN_STATE_DIR, state.simulation_id)
        os.makedirs(sim_dir, exist_ok=True)
        state_file = os.path.join(sim_dir, "run_state.json")
        
        data = state.to_detail_dict()
        
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        cls._run_states[state.simulation_id] = state
    
    @classmethod
    def start_simulation(
        cls,
        simulation_id: str,
        platform: str = "parallel",  # twitter / reddit / parallel
        max_rounds: int = None,  # maximum number of simulation rounds (optional; truncates overly long simulations)
        enable_graph_memory_update: bool = False,  # whetherwilllivemovemoreNewtoZepGraph
        graph_id: str = None  # Zep graph ID (required when enabling graph memory update)
    ) -> SimulationRunState:
        """
        launchsimulate
        
        Args:
            simulation_id: simulateID
            platform: RunPlatform (twitter/reddit/parallel)
            max_rounds: maximum number of simulation rounds (optional; truncates overly long simulations)
            enable_graph_memory_update: whetherwillAgentlivemovemovestatemoreNewtoZepGraph
            graph_id: Zep graph ID (required when enabling graph memory update)
            
        Returns:
            SimulationRunState
        """
        # checkwhetheratRun
        existing = cls.get_run_state(simulation_id)
        if existing and existing.runner_status in [RunnerStatus.RUNNING, RunnerStatus.STARTING]:
            raise ValueError(f"simulateatRunMiddle: {simulation_id}")
        
        # LoadsimulateConfiguration
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        
        if not os.path.exists(config_path):
            raise ValueError(f"Simulation configuration does not exist; please call the /prepare endpoint first")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # InitializeRunStatus
        time_config = config.get("time_config", {})
        total_hours = time_config.get("total_simulation_hours", 72)
        minutes_per_round = time_config.get("minutes_per_round", 30)
        total_rounds = int(total_hours * 60 / minutes_per_round)
        
        # If a maximum round count is specified, truncate
        if max_rounds is not None and max_rounds > 0:
            original_rounds = total_rounds
            total_rounds = min(total_rounds, max_rounds)
            if total_rounds < original_rounds:
                logger.info(f"roundnumbertruncate: {original_rounds} -> {total_rounds} (max_rounds={max_rounds})")
        
        state = SimulationRunState(
            simulation_id=simulation_id,
            runner_status=RunnerStatus.STARTING,
            total_rounds=total_rounds,
            total_simulation_hours=total_hours,
            started_at=datetime.now().isoformat(),
        )
        
        cls._save_run_state(state)
        
        # If graph memory update is enabled, create the updater
        if enable_graph_memory_update:
            if not graph_id:
                raise ValueError("EnableGraphmemorymoreNewhourmust graph_id")
            
            try:
                ZepGraphMemoryManager.create_updater(simulation_id, graph_id)
                cls._graph_memory_enabled[simulation_id] = True
                logger.info(f"EnableGraphmemorymoreNew: simulation_id={simulation_id}, graph_id={graph_id}")
            except Exception as e:
                logger.error(f"createGraphmemorymoreNewerfail: {e}")
                cls._graph_memory_enabled[simulation_id] = False
        else:
            cls._graph_memory_enabled[simulation_id] = False
        
        # One generic runner handles every domain and every track.
        script_path = os.path.join(cls.SCRIPTS_DIR, "run_simulation.py")
        if not os.path.exists(script_path):
            raise ValueError(f"Simulation runner does not exist: {script_path}")

        # Tracks are declared by the selected domain pack. The generic runner
        # writes one <track>/actions.jsonl file per track.
        domain_tracks = config.get("tracks") or (
            ["twitter", "reddit"] if config.get("domain", "social") == "social" else ["main"]
        )
        for track in domain_tracks:
            state.tracks[track] = {"status": "starting", "actions_count": 0}
        state.twitter_running = "twitter" in domain_tracks
        state.reddit_running = "reddit" in domain_tracks
        
        # Generic runs must not inherit a prior actions.jsonl or world DB.
        # A stale simulation_end event would otherwise make the monitor mark a
        # newly launched process complete before it writes its first round.
        for track in domain_tracks:
            track_dir = os.path.join(sim_dir, track)
            if os.path.isdir(track_dir):
                shutil.rmtree(track_dir)
        for artifact in ("main_world.db", "results.json", "main_metrics.json", "simulation.log"):
            artifact_path = os.path.join(sim_dir, artifact)
            if os.path.exists(artifact_path):
                os.remove(artifact_path)

        # createActionteamcolumn
        action_queue = Queue()
        cls._action_queues[simulation_id] = action_queue
        
        # launchsimulateenterprogram
        try:
            # Build the run command using the full path
            # New log structure:
            #   twitter/actions.jsonl - Twitter Actionlog
            #   reddit/actions.jsonl  - Reddit Actionlog
            #   simulation.log        - mainenterprogramlog
            
            cmd = [
                sys.executable,  # Pythonuntiereleaseer
                script_path,
                "--config", config_path,  # usecompleteConfigurationFilePath
            ]
            
            # If a maximum round count is specified, add it to the command parameters
            if max_rounds is not None and max_rounds > 0:
                cmd.extend(["--max-rounds", str(max_rounds)])
            
            # Create the main log file so stdout/stderr are redirected and the program does not block
            main_log_path = os.path.join(sim_dir, "simulation.log")
            main_log_file = open(main_log_path, 'w', encoding='utf-8')
            
            # Set the subprocess environment variable so that UTF-8 encoding is used on Windows
            # This avoids encoding issues when third-party libraries (e.g. OASIS) read files
            env = os.environ.copy()
            env['PYTHONUTF8'] = '1'  # Python 3.7+ support; makes open() use UTF-8 by default
            env['PYTHONIOENCODING'] = 'utf-8'  # keep stdout/stderr use UTF-8
            
            # Set the working directory to the simulation directory (the database and other files are generated there)
            # Use start_new_session=True to create a new process group so the subprocess can be stopped via os.killpg
            process = subprocess.Popen(
                cmd,
                cwd=sim_dir,
                stdout=main_log_file,
                stderr=subprocess.STDOUT,  # stderr alsoWritesameaFile
                text=True,
                encoding='utf-8',  # stylemustencode
                bufsize=1,
                env=env,  # transferdeliverbelthave UTF-8 SettingsEnvironmentchangemeasure
                start_new_session=True,  # Create a new process group so the subprocess can be stopped on server shutdown
            )
            
            # SaveFilesentencetoAftercontinueClose
            cls._stdout_files[simulation_id] = main_log_file
            cls._stderr_files[simulation_id] = None  # noagainneedwantalone stderr
            
            state.process_pid = process.pid
            state.runner_status = RunnerStatus.RUNNING
            cls._processes[simulation_id] = process
            cls._save_run_state(state)
            
            # launchMonitorthreadprogram
            monitor_thread = threading.Thread(
                target=cls._monitor_simulation,
                args=(simulation_id,),
                daemon=True
            )
            monitor_thread.start()
            cls._monitor_threads[simulation_id] = monitor_thread
            
            logger.info(f"simulatelaunchsuccess: {simulation_id}, pid={process.pid}, platform={platform}")
            
        except Exception as e:
            state.runner_status = RunnerStatus.FAILED
            state.error = str(e)
            cls._save_run_state(state)
            raise
        
        return state
    
    @classmethod
    def _monitor_simulation(cls, simulation_id: str):
        """Monitor the simulation process and parse the action log."""
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        
        # Generic log structure: one action log per domain track.
        config_path = os.path.join(sim_dir, "simulation_config.json")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                run_config = json.load(f)
        except Exception:
            run_config = {}
        tracks = run_config.get("tracks") or (
            ["twitter", "reddit"] if run_config.get("domain", "social") == "social" else ["main"]
        )
        track_logs = {
            track: os.path.join(sim_dir, track, "actions.jsonl") for track in tracks
        }
        
        process = cls._processes.get(simulation_id)
        state = cls.get_run_state(simulation_id)
        
        if not process or not state:
            return
        
        positions = {track: 0 for track in tracks}
        
        try:
            while process.poll() is None:
                for track, log_path in track_logs.items():
                    if os.path.exists(log_path):
                        positions[track] = cls._read_action_log(
                            log_path, positions[track], state, track
                        )
                cls._save_run_state(state)
                time.sleep(2)
            
            # After the process ends, read the final logs.
            for track, log_path in track_logs.items():
                if os.path.exists(log_path):
                    cls._read_action_log(log_path, positions[track], state, track)
            
            # enterprogramend
            exit_code = process.returncode
            
            if exit_code == 0:
                state.runner_status = RunnerStatus.COMPLETED
                state.completed_at = datetime.now().isoformat()
                logger.info(f"simulatecomplete: {simulation_id}")
            else:
                state.runner_status = RunnerStatus.FAILED
                # frommainlogFileReadErrorinformation
                main_log_path = os.path.join(sim_dir, "simulation.log")
                error_info = ""
                try:
                    if os.path.exists(main_log_path):
                        with open(main_log_path, 'r', encoding='utf-8') as f:
                            error_info = f.read()[-2000:]  # takeLast2000character
                except Exception:
                    pass
                state.error = f"enterprogramexitout: {exit_code}, Error: {error_info}"
                logger.error(f"simulatefail: {simulation_id}, error={state.error}")
            
            state.twitter_running = False
            state.reddit_running = False
            for track in tracks:
                state.tracks.setdefault(track, {})["status"] = "completed" if exit_code == 0 else "failed"
            cls._save_run_state(state)
            
        except Exception as e:
            logger.error(f"MonitorthreadprogramException: {simulation_id}, error={str(e)}")
            state.runner_status = RunnerStatus.FAILED
            state.error = str(e)
            cls._save_run_state(state)
        
        finally:
            # stopGraphmemorymoreNewer
            if cls._graph_memory_enabled.get(simulation_id, False):
                try:
                    ZepGraphMemoryManager.stop_updater(simulation_id)
                    logger.info(f"stopGraphmemorymoreNew: simulation_id={simulation_id}")
                except Exception as e:
                    logger.error(f"stopGraphmemorymoreNewerfail: {e}")
                cls._graph_memory_enabled.pop(simulation_id, None)
            
            # Cleanupenterprogramresource
            cls._processes.pop(simulation_id, None)
            cls._action_queues.pop(simulation_id, None)
            
            # CloselogFilesentence
            if simulation_id in cls._stdout_files:
                try:
                    cls._stdout_files[simulation_id].close()
                except Exception:
                    pass
                cls._stdout_files.pop(simulation_id, None)
            if simulation_id in cls._stderr_files and cls._stderr_files[simulation_id]:
                try:
                    cls._stderr_files[simulation_id].close()
                except Exception:
                    pass
                cls._stderr_files.pop(simulation_id, None)
    
    @classmethod
    def _read_action_log(
        cls, 
        log_path: str, 
        position: int, 
        state: SimulationRunState,
        platform: str
    ) -> int:
        """
        ReadActionlogFile
        
        Args:
            log_path: logFilePath
            position: UpReadposition
            state: RunStatusobject
            platform: PlatformName (twitter/reddit)
            
        Returns:
            NewReadposition
        """
        # checkwhetherEnableGraphmemorymoreNew
        graph_memory_enabled = cls._graph_memory_enabled.get(state.simulation_id, False)
        graph_updater = None
        if graph_memory_enabled:
            graph_updater = ZepGraphMemoryManager.get_updater(state.simulation_id)
        
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                f.seek(position)
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            action_data = json.loads(line)
                            
                            # ProcesseventTypeedgeitem
                            if "event_type" in action_data:
                                event_type = action_data.get("event_type")
                                
                                # Detected simulation_end event; mark the platform as complete
                                if event_type == "simulation_end":
                                    track_state = state.tracks.setdefault(platform, {})
                                    track_state["status"] = "completed"
                                    track_state["total_actions"] = action_data.get("total_actions", 0)
                                    if platform == "twitter":
                                        state.twitter_completed = True
                                        state.twitter_running = False
                                    elif platform == "reddit":
                                        state.reddit_completed = True
                                        state.reddit_running = False

                                    all_completed = cls._check_all_platforms_completed(state)
                                    if all_completed:
                                        state.runner_status = RunnerStatus.COMPLETED
                                        state.completed_at = datetime.now().isoformat()
                                        logger.info(f"hasPlatformsimulatecomplete: {state.simulation_id}")
                                
                                # Update round info (from the round_end event)
                                elif event_type == "round_end":
                                    round_num = action_data.get("round", 0)
                                    simulated_hours = action_data.get("simulated_hours", 0)
                                    
                                    track_state = state.tracks.setdefault(platform, {})
                                    track_state["current_round"] = max(
                                        round_num, track_state.get("current_round", 0)
                                    )
                                    track_state["simulated_hours"] = simulated_hours
                                    if round_num > state.current_round:
                                        state.current_round = round_num
                                    state.simulated_hours = max(
                                        [
                                            state.simulated_hours,
                                            simulated_hours,
                                        ]
                                    )
                                
                                continue
                            
                            action = AgentAction(
                                round_num=action_data.get("round", 0),
                                timestamp=action_data.get("timestamp", datetime.now().isoformat()),
                                platform=platform,
                                agent_id=action_data.get("agent_id", 0),
                                agent_name=action_data.get("agent_name", ""),
                                action_type=action_data.get("action_type", ""),
                                action_args=action_data.get("action_args", {}),
                                result=action_data.get("result"),
                                success=action_data.get("success", True),
                            )
                            state.add_action(action)
                            
                            # moreNewround
                            if action.round_num and action.round_num > state.current_round:
                                state.current_round = action.round_num
                            
                            # If graph memory update is enabled, send the activity to Zep
                            if graph_updater:
                                graph_updater.add_activity_from_dict(action_data, platform)
                            
                        except json.JSONDecodeError:
                            pass
                return f.tell()
        except Exception as e:
            logger.warning(f"ReadActionlogfail: {log_path}, error={e}")
            return position
    
    @classmethod
    def _check_all_platforms_completed(cls, state: SimulationRunState) -> bool:
        """Compatibility helper: all discovered domain tracks must finish."""
        sim_dir = os.path.join(cls.RUN_STATE_DIR, state.simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception:
            config = {}
        tracks = config.get("tracks") or ["main"]
        discovered = [
            track for track in tracks
            if os.path.exists(os.path.join(sim_dir, track, "actions.jsonl"))
        ]
        if not discovered:
            return False
        return all(
            state.tracks.get(track, {}).get("status") == "completed"
            for track in discovered
        )
    
    @classmethod
    def _terminate_process(cls, process: subprocess.Popen, simulation_id: str, timeout: int = 10):
        """
        crossPlatformstopenterprogramplusitsstudententerprogram
        
        Args:
            process: wantstopenterprogram
            simulation_id: simulation ID (for logging)
            timeout: time to wait for the process to exit (seconds)
        """
        if IS_WINDOWS:
            # Windows: use taskkill commandstopenterprogramtree
            # /F = force stop, /T = stop the process tree (including child processes)
            logger.info(f"stopenterprogramtree (Windows): simulation={simulation_id}, pid={process.pid}")
            try:
                # firsttestexcellentstop
                subprocess.run(
                    ['taskkill', '/PID', str(process.pid), '/T'],
                    capture_output=True,
                    timeout=5
                )
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    # strengthensystemstop
                    logger.warning(f"Process not responding; forcing stop: {simulation_id}")
                    subprocess.run(
                        ['taskkill', '/F', '/PID', str(process.pid), '/T'],
                        capture_output=True,
                        timeout=5
                    )
                    process.wait(timeout=5)
            except Exception as e:
                logger.warning(f"taskkill failed, trying to terminate: {e}")
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        else:
            # Unix: useenterprogramgroupstop
            # Since start_new_session=True is used, the process group ID equals the main process PID
            pgid = os.getpgid(process.pid)
            logger.info(f"stopenterprogramgroup (Unix): simulation={simulation_id}, pgid={pgid}")
            
            # firstSend SIGTERM givewholeenterprogramgroup
            os.killpg(pgid, signal.SIGTERM)
            
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # If it still hasn't ended, force-send SIGKILL
                logger.warning(f"Process group not responding to SIGTERM; forcing stop: {simulation_id}")
                os.killpg(pgid, signal.SIGKILL)
                process.wait(timeout=5)
    
    @classmethod
    def stop_simulation(cls, simulation_id: str) -> SimulationRunState:
        """stopsimulate"""
        state = cls.get_run_state(simulation_id)
        if not state:
            raise ValueError(f"simulateNot Exist: {simulation_id}")
        
        if state.runner_status not in [RunnerStatus.RUNNING, RunnerStatus.PAUSED]:
            raise ValueError(f"simulatenotatRun: {simulation_id}, status={state.runner_status}")
        
        state.runner_status = RunnerStatus.STOPPING
        cls._save_run_state(state)
        
        # stopenterprogram
        process = cls._processes.get(simulation_id)
        if process and process.poll() is None:
            try:
                cls._terminate_process(process, simulation_id)
            except ProcessLookupError:
                # enterprogramalreadyNot Exist
                pass
            except Exception as e:
                logger.error(f"stopenterprogramgroupfail: {simulation_id}, error={e}")
                # returnexittoconnectstopenterprogram
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except Exception:
                    process.kill()
        
        state.runner_status = RunnerStatus.STOPPED
        state.twitter_running = False
        state.reddit_running = False
        state.completed_at = datetime.now().isoformat()
        cls._save_run_state(state)
        
        # stopGraphmemorymoreNewer
        if cls._graph_memory_enabled.get(simulation_id, False):
            try:
                ZepGraphMemoryManager.stop_updater(simulation_id)
                logger.info(f"stopGraphmemorymoreNew: simulation_id={simulation_id}")
            except Exception as e:
                logger.error(f"stopGraphmemorymoreNewerfail: {e}")
            cls._graph_memory_enabled.pop(simulation_id, None)
        
        logger.info(f"simulatestop: {simulation_id}")
        return state
    
    @classmethod
    def _read_actions_from_file(
        cls,
        file_path: str,
        default_platform: Optional[str] = None,
        platform_filter: Optional[str] = None,
        agent_id: Optional[int] = None,
        round_num: Optional[int] = None
    ) -> List[AgentAction]:
        """
        fromsingleActionFileMiddleReadAction
        
        Args:
            file_path: ActionlogFilePath
            default_platform: default platform (used when an action record has no platform field)
            platform_filter: filterPlatform
            agent_id: filter Agent ID
            round_num: filterround
        """
        if not os.path.exists(file_path):
            return []
        
        actions = []
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    data = json.loads(line)
                    
                    # Skip non-action records (e.g. simulation_start, round_start, round_end events)
                    if "event_type" in data:
                        continue
                    
                    # Skip records without an agent_id (not agent actions)
                    if "agent_id" not in data:
                        continue
                    
                    # Get the platform: first use the platform in the record, then fall back to the default platform
                    record_platform = data.get("platform") or default_platform or ""
                    
                    # filter
                    if platform_filter and record_platform != platform_filter:
                        continue
                    if agent_id is not None and data.get("agent_id") != agent_id:
                        continue
                    if round_num is not None and data.get("round") != round_num:
                        continue
                    
                    actions.append(AgentAction(
                        round_num=data.get("round", 0),
                        timestamp=data.get("timestamp", ""),
                        platform=record_platform,
                        agent_id=data.get("agent_id", 0),
                        agent_name=data.get("agent_name", ""),
                        action_type=data.get("action_type", ""),
                        action_args=data.get("action_args", {}),
                        result=data.get("result"),
                        success=data.get("success", True),
                    ))
                    
                except json.JSONDecodeError:
                    continue
        
        return actions
    
    @classmethod
    def get_all_actions(
        cls,
        simulation_id: str,
        platform: Optional[str] = None,
        agent_id: Optional[int] = None,
        round_num: Optional[int] = None
    ) -> List[AgentAction]:
        """
        Get the complete action history for all platforms (no pagination limit)
        
        Args:
            simulation_id: simulateID
            platform: filter by platform (twitter/reddit)
            agent_id: filterAgent
            round_num: filterround
            
        Returns:
            Complete action list (sorted by timestamp, newest first)
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        actions = []
        
        # Read every domain track declared by the simulation. Keep twitter and
        # reddit as compatibility fallbacks for older simulations.
        config_path = os.path.join(sim_dir, "simulation_config.json")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                run_config = json.load(f)
        except Exception:
            run_config = {}
        tracks = run_config.get("tracks") or ["twitter", "reddit"]
        for track in tracks:
            if platform and platform != track:
                continue
            actions.extend(cls._read_actions_from_file(
                os.path.join(sim_dir, track, "actions.jsonl"),
                default_platform=track,
                platform_filter=platform,
                agent_id=agent_id,
                round_num=round_num
            ))
        
        # If per-platform files do not exist, try the old single-file format
        if not actions:
            actions_log = os.path.join(sim_dir, "actions.jsonl")
            actions = cls._read_actions_from_file(
                actions_log,
                default_platform=None,  # OldformatFileMiddleshouldshouldhave platform wordsegment
                platform_filter=platform,
                agent_id=agent_id,
                round_num=round_num
            )
        
        # Sort by timestamp (newest first)
        actions.sort(key=lambda x: x.timestamp, reverse=True)
        
        return actions
    
    @classmethod
    def get_actions(
        cls,
        simulation_id: str,
        limit: int = 100,
        offset: int = 0,
        platform: Optional[str] = None,
        agent_id: Optional[int] = None,
        round_num: Optional[int] = None
    ) -> List[AgentAction]:
        """
        Get the action history (with pagination)
        
        Args:
            simulation_id: simulateID
            limit: Returnnumbermeasurelimit
            offset: movemeasure
            platform: filterPlatform
            agent_id: filterAgent
            round_num: filterround
            
        Returns:
            Actionlist
        """
        actions = cls.get_all_actions(
            simulation_id=simulation_id,
            platform=platform,
            agent_id=agent_id,
            round_num=round_num
        )
        
        # minutepage
        return actions[offset:offset + limit]
    
    @classmethod
    def get_timeline(
        cls,
        simulation_id: str,
        start_round: int = 0,
        end_round: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get the simulation timeline (rounds)
        
        Args:
            simulation_id: simulateID
            start_round: upbeginround
            end_round: endround
            
        Returns:
            eachroundinformation
        """
        actions = cls.get_actions(simulation_id, limit=10000)
        
        # roundgroup
        rounds: Dict[int, Dict[str, Any]] = {}
        
        for action in actions:
            round_num = action.round_num
            
            if round_num < start_round:
                continue
            if end_round is not None and round_num > end_round:
                continue
            
            if round_num not in rounds:
                rounds[round_num] = {
                    "round_num": round_num,
                    "twitter_actions": 0,
                    "reddit_actions": 0,
                    "active_agents": set(),
                    "action_types": {},
                    "first_action_time": action.timestamp,
                    "last_action_time": action.timestamp,
                }
            
            r = rounds[round_num]
            
            if action.platform == "twitter":
                r["twitter_actions"] += 1
            else:
                r["reddit_actions"] += 1
            
            r["active_agents"].add(action.agent_id)
            r["action_types"][action.action_type] = r["action_types"].get(action.action_type, 0) + 1
            r["last_action_time"] = action.timestamp
        
        # turnswapforlist
        result = []
        for round_num in sorted(rounds.keys()):
            r = rounds[round_num]
            result.append({
                "round_num": round_num,
                "twitter_actions": r["twitter_actions"],
                "reddit_actions": r["reddit_actions"],
                "total_actions": r["twitter_actions"] + r["reddit_actions"],
                "active_agents_count": len(r["active_agents"]),
                "active_agents": list(r["active_agents"]),
                "action_types": r["action_types"],
                "first_action_time": r["first_action_time"],
                "last_action_time": r["last_action_time"],
            })
        
        return result
    
    @classmethod
    def get_agent_stats(cls, simulation_id: str) -> List[Dict[str, Any]]:
        """
        GeteachAgentstatisticsinformation
        
        Returns:
            Agentstatisticslist
        """
        actions = cls.get_actions(simulation_id, limit=10000)
        
        agent_stats: Dict[int, Dict[str, Any]] = {}
        
        for action in actions:
            agent_id = action.agent_id
            
            if agent_id not in agent_stats:
                agent_stats[agent_id] = {
                    "agent_id": agent_id,
                    "agent_name": action.agent_name,
                    "total_actions": 0,
                    "twitter_actions": 0,
                    "reddit_actions": 0,
                    "action_types": {},
                    "first_action_time": action.timestamp,
                    "last_action_time": action.timestamp,
                }
            
            stats = agent_stats[agent_id]
            stats["total_actions"] += 1
            
            if action.platform == "twitter":
                stats["twitter_actions"] += 1
            else:
                stats["reddit_actions"] += 1
            
            stats["action_types"][action.action_type] = stats["action_types"].get(action.action_type, 0) + 1
            stats["last_action_time"] = action.timestamp
        
        # Actionnumbersort
        result = sorted(agent_stats.values(), key=lambda x: x["total_actions"], reverse=True)
        
        return result
    
    @classmethod
    def cleanup_simulation_logs(cls, simulation_id: str) -> Dict[str, Any]:
        """
        Clean up the simulation run logs (for forcibly restarting the simulation)
        
        The following files will be deleted:
        - run_state.json
        - twitter/actions.jsonl
        - reddit/actions.jsonl
        - simulation.log
        - stdout.log / stderr.log
        - twitter_simulation.db (simulation database)
        - reddit_simulation.db (simulation database)
        - env_status.json (environment status)
        
        Note: the configuration file (simulation_config.json) and profile files are NOT deleted
        
        Args:
            simulation_id: simulateID
            
        Returns:
            Cleanupresultinformation
        """
        import shutil
        
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        
        if not os.path.exists(sim_dir):
            return {"success": True, "message": "Simulation directory does not exist; no cleanup needed"}
        
        cleaned_files = []
        errors = []
        
        # List of files to delete (including database files)
        files_to_delete = [
            "run_state.json",
            "simulation.log",
            "stdout.log",
            "stderr.log",
            "twitter_simulation.db",  # Twitter PlatformDatalibrary
            "reddit_simulation.db",   # Reddit PlatformDatalibrary
            "env_status.json",        # EnvironmentStatusFile
        ]
        
        # List of directories to delete (including action logs)
        dirs_to_clean = ["twitter", "reddit"]
        
        # deleteFile
        for filename in files_to_delete:
            file_path = os.path.join(sim_dir, filename)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    cleaned_files.append(filename)
                except Exception as e:
                    errors.append(f"delete {filename} fail: {str(e)}")
        
        # CleanupPlatformDirectoryMiddleActionlog
        for dir_name in dirs_to_clean:
            dir_path = os.path.join(sim_dir, dir_name)
            if os.path.exists(dir_path):
                actions_file = os.path.join(dir_path, "actions.jsonl")
                if os.path.exists(actions_file):
                    try:
                        os.remove(actions_file)
                        cleaned_files.append(f"{dir_name}/actions.jsonl")
                    except Exception as e:
                        errors.append(f"delete {dir_name}/actions.jsonl fail: {str(e)}")
        
        # CleanupInternalstoreMiddleRunStatus
        if simulation_id in cls._run_states:
            del cls._run_states[simulation_id]
        
        logger.info(f"Cleanupsimulatelogcomplete: {simulation_id}, deleteFile: {cleaned_files}")
        
        return {
            "success": len(errors) == 0,
            "cleaned_files": cleaned_files,
            "errors": errors if errors else None
        }
    
    # defendstopheavyrepeatCleanup
    _cleanup_done = False
    
    @classmethod
    def cleanup_all_simulations(cls):
        """
        CleanuphasRunMiddlesimulateenterprogram
        
        Called on server shutdown to stop any running simulation subprocesses
        """
        # defendstopheavyrepeatCleanup
        if cls._cleanup_done:
            return
        cls._cleanup_done = True
        
        # Check whether there is anything to clean up (the empty process only prints useless logs)
        has_processes = bool(cls._processes)
        has_updaters = bool(cls._graph_memory_enabled)
        
        if not has_processes and not has_updaters:
            return  # Nothing to clean up; return quietly
        
        logger.info("positiveatCleanuphassimulateenterprogram...")
        
        # First stop the graph memory updaters (stop_all prints logs internally)
        try:
            ZepGraphMemoryManager.stop_all()
        except Exception as e:
            logger.error(f"stopGraphmemorymoreNewerfail: {e}")
        cls._graph_memory_enabled.clear()
        
        # copydicttoatgenhourmodify
        processes = list(cls._processes.items())
        
        for simulation_id, process in processes:
            try:
                if process.poll() is None:  # enterprogramstillatRun
                    logger.info(f"stopsimulateenterprogram: {simulation_id}, pid={process.pid}")
                    
                    try:
                        # usecrossPlatformenterprogramstopmethod
                        cls._terminate_process(process, simulation_id, timeout=5)
                    except (ProcessLookupError, OSError):
                        # The process may already be gone; try to stop anyway
                        try:
                            process.terminate()
                            process.wait(timeout=3)
                        except Exception:
                            process.kill()
                    
                    # moreNew run_state.json
                    state = cls.get_run_state(simulation_id)
                    if state:
                        state.runner_status = RunnerStatus.STOPPED
                        state.twitter_running = False
                        state.reddit_running = False
                        state.completed_at = datetime.now().isoformat()
                        state.error = "Server shutting down; simulation stopped"
                        cls._save_run_state(state)
                    
                    # Also update state.json, setting the status to stopped
                    try:
                        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
                        state_file = os.path.join(sim_dir, "state.json")
                        logger.info(f"testmoreNew state.json: {state_file}")
                        if os.path.exists(state_file):
                            with open(state_file, 'r', encoding='utf-8') as f:
                                state_data = json.load(f)
                            state_data['status'] = 'stopped'
                            state_data['updated_at'] = datetime.now().isoformat()
                            with open(state_file, 'w', encoding='utf-8') as f:
                                json.dump(state_data, f, indent=2, ensure_ascii=False)
                            logger.info(f"moreNew state.json Statusfor stopped: {simulation_id}")
                        else:
                            logger.warning(f"state.json Not Exist: {state_file}")
                    except Exception as state_err:
                        logger.warning(f"moreNew state.json fail: {simulation_id}, error={state_err}")
                        
            except Exception as e:
                logger.error(f"Cleanupenterprogramfail: {simulation_id}, error={e}")
        
        # CleanupFilesentence
        for simulation_id, file_handle in list(cls._stdout_files.items()):
            try:
                if file_handle:
                    file_handle.close()
            except Exception:
                pass
        cls._stdout_files.clear()
        
        for simulation_id, file_handle in list(cls._stderr_files.items()):
            try:
                if file_handle:
                    file_handle.close()
            except Exception:
                pass
        cls._stderr_files.clear()
        
        # CleanupInternalstoreMiddleStatus
        cls._processes.clear()
        cls._action_queues.clear()
        
        logger.info("simulateenterprogramCleanupcomplete")
    
    @classmethod
    def register_cleanup(cls):
        """
        registerCleanupFunction
        
        Called when the Flask app starts, to clean up simulation subprocesses on server shutdown
        """
        global _cleanup_registered
        
        if _cleanup_registered:
            return
        
        # Under Flask debug mode, register cleanup only in the reloader subprocess (the actual run process)
        # WERKZEUG_RUN_MAIN=true tableare reloader studententerprogram
        # In non-debug mode there is no such env var, but registration is still needed
        is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
        is_debug_mode = os.environ.get('FLASK_DEBUG') == '1' or os.environ.get('WERKZEUG_RUN_MAIN') is not None
        
        # Under debug mode, register only in the reloader subprocess; under non-debug mode, always register
        if is_debug_mode and not is_reloader_process:
            _cleanup_registered = True  # Mark as registered to prevent repeated registration in the subprocess
            return
        
        # SaveoriginalhaveinfoProcesser
        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)
        # SIGHUP only exists on Unix systems (macOS/Linux), not on Windows
        original_sighup = None
        has_sighup = hasattr(signal, 'SIGHUP')
        if has_sighup:
            original_sighup = signal.getsignal(signal.SIGHUP)
        
        def cleanup_handler(signum=None, frame=None):
            """Signal handler: first clean up the simulation subprocesses, then call the original handler"""
            # onlyhaveathaveenterprogramneedwantCleanuphourhitprintlog
            if cls._processes or cls._graph_memory_enabled:
                logger.info(f"Received signal {signum}, starting cleanup...")
            cls.cleanup_all_simulations()
            
            # Call the original signal handler so Flask exits normally
            if signum == signal.SIGINT and callable(original_sigint):
                original_sigint(signum, frame)
            elif signum == signal.SIGTERM and callable(original_sigterm):
                original_sigterm(signum, frame)
            elif has_sighup and signum == signal.SIGHUP:
                # SIGHUP: endClosehourSend
                if callable(original_sighup):
                    original_sighup(signum, frame)
                else:
                    # Default behavior: normal exit
                    sys.exit(0)
            else:
                # If the original handler cannot be called (e.g. SIG_DFL), use the default behavior
                raise KeyboardInterrupt
        
        # Register the atexit handler (as a fallback)
        atexit.register(cls.cleanup_all_simulations)
        
        # Register the signal handler (only in the main thread)
        try:
            # SIGTERM: kill commandDefaultinfo
            signal.signal(signal.SIGTERM, cleanup_handler)
            # SIGINT: Ctrl+C
            signal.signal(signal.SIGINT, cleanup_handler)
            # SIGHUP: shutdown (Unix systems only)
            if has_sighup:
                signal.signal(signal.SIGHUP, cleanup_handler)
        except ValueError:
            # Not in the main thread; can only use atexit
            logger.warning("Cannot register the signal handler (not in the main thread); using only atexit")
        
        _cleanup_registered = True
    
    @classmethod
    def get_running_simulations(cls) -> List[str]:
        """
        GethaspositiveatRunsimulateIDlist
        """
        running = []
        for sim_id, process in cls._processes.items():
            if process.poll() is None:
                running.append(sim_id)
        return running
    
    # ============== Interview function ==============
    
    @classmethod
    def check_env_alive(cls, simulation_id: str) -> bool:
        """
        Check whether the simulation environment is alive (can it receive interview commands)

        Args:
            simulation_id: simulateID

        Returns:
            True means the environment is alive; False means the environment is closed
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            return False

        ipc_client = SimulationIPCClient(sim_dir)
        return ipc_client.check_env_alive()

    @classmethod
    def get_env_status_detail(cls, simulation_id: str) -> Dict[str, Any]:
        """
        GetsimulateEnvironmentdetailedStatusinformation

        Args:
            simulation_id: simulateID

        Returns:
            Status dict, containing status, twitter_available, reddit_available, timestamp
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        status_file = os.path.join(sim_dir, "env_status.json")
        
        default_status = {
            "status": "stopped",
            "twitter_available": False,
            "reddit_available": False,
            "timestamp": None
        }
        
        if not os.path.exists(status_file):
            return default_status
        
        try:
            with open(status_file, 'r', encoding='utf-8') as f:
                status = json.load(f)
            return {
                "status": status.get("status", "stopped"),
                "twitter_available": status.get("twitter_available", False),
                "reddit_available": status.get("reddit_available", False),
                "timestamp": status.get("timestamp")
            }
        except (json.JSONDecodeError, OSError):
            return default_status

    @classmethod
    def interview_agent(
        cls,
        simulation_id: str,
        agent_id: int,
        prompt: str,
        platform: str = None,
        timeout: float = 60.0
    ) -> Dict[str, Any]:
        """
        interviewsingleAgent

        Args:
            simulation_id: simulateID
            agent_id: Agent ID
            prompt: interviewquestion
            platform: specified platform (optional)
                - "twitter": onlyinterviewTwitterPlatform
                - "reddit": onlyinterviewRedditPlatform
                - None: in a dual-platform simulation, interview both platforms at once and return the combined result
            timeout: duration (seconds)

        Returns:
            interviewresultdict

        Raises:
            ValueError: simulateNot ExistorEnvironmentnotRun
            TimeoutError: waitresponsehour
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"simulateNot Exist: {simulation_id}")

        ipc_client = SimulationIPCClient(sim_dir)

        if not ipc_client.check_env_alive():
            raise ValueError(f"Simulation environment is not running or is closed; cannot execute interview: {simulation_id}")

        logger.info(f"SendInterviewcommand: simulation_id={simulation_id}, agent_id={agent_id}, platform={platform}")

        response = ipc_client.send_interview(
            agent_id=agent_id,
            prompt=prompt,
            platform=platform,
            timeout=timeout
        )

        if response.status.value == "completed":
            return {
                "success": True,
                "agent_id": agent_id,
                "prompt": prompt,
                "result": response.result,
                "timestamp": response.timestamp
            }
        else:
            return {
                "success": False,
                "agent_id": agent_id,
                "prompt": prompt,
                "error": response.error,
                "timestamp": response.timestamp
            }
    
    @classmethod
    def interview_agents_batch(
        cls,
        simulation_id: str,
        interviews: List[Dict[str, Any]],
        platform: str = None,
        timeout: float = 120.0
    ) -> Dict[str, Any]:
        """
        batchinterviewmanyAgent

        Args:
            simulation_id: simulateID
            interviews: list of interviews, each item containing {"agent_id": int, "prompt": str, "platform": str (optional)}
            platform: default platform (optional; overridden by each interview item's platform)
                - "twitter": DefaultonlyinterviewTwitterPlatform
                - "reddit": DefaultonlyinterviewRedditPlatform
                - None: doublePlatformsimulatehoureachAgentsimultaneouslyinterviewtwoPlatform
            timeout: duration (seconds)

        Returns:
            batchinterviewresultdict

        Raises:
            ValueError: simulateNot ExistorEnvironmentnotRun
            TimeoutError: waitresponsehour
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"simulateNot Exist: {simulation_id}")

        ipc_client = SimulationIPCClient(sim_dir)

        if not ipc_client.check_env_alive():
            raise ValueError(f"Simulation environment is not running or is closed; cannot execute interview: {simulation_id}")

        logger.info(f"SendbatchInterviewcommand: simulation_id={simulation_id}, count={len(interviews)}, platform={platform}")

        response = ipc_client.send_batch_interview(
            interviews=interviews,
            platform=platform,
            timeout=timeout
        )

        if response.status.value == "completed":
            return {
                "success": True,
                "interviews_count": len(interviews),
                "result": response.result,
                "timestamp": response.timestamp
            }
        else:
            return {
                "success": False,
                "interviews_count": len(interviews),
                "error": response.error,
                "timestamp": response.timestamp
            }
    
    @classmethod
    def interview_all_agents(
        cls,
        simulation_id: str,
        prompt: str,
        platform: str = None,
        timeout: float = 180.0
    ) -> Dict[str, Any]:
        """
        Interview all agents (bulk interview)

        usesamequestioninterviewsimulateMiddlehasAgent

        Args:
            simulation_id: simulateID
            prompt: interview question (all agents use the same question)
            platform: specified platform (optional)
                - "twitter": onlyinterviewTwitterPlatform
                - "reddit": onlyinterviewRedditPlatform
                - None: doublePlatformsimulatehoureachAgentsimultaneouslyinterviewtwoPlatform
            timeout: duration (seconds)

        Returns:
            allbureauinterviewresultdict
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"simulateNot Exist: {simulation_id}")

        # fromConfigurationFileGethasAgentinformation
        config_path = os.path.join(sim_dir, "simulation_config.json")
        if not os.path.exists(config_path):
            raise ValueError(f"simulateConfigurationNot Exist: {simulation_id}")

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        agent_configs = config.get("agent_configs", [])
        if not agent_configs:
            raise ValueError(f"simulateConfigurationMiddlenohaveAgent: {simulation_id}")

        # buildbatchinterviewlist
        interviews = []
        for agent_config in agent_configs:
            agent_id = agent_config.get("agent_id")
            if agent_id is not None:
                interviews.append({
                    "agent_id": agent_id,
                    "prompt": prompt
                })

        logger.info(f"SendallbureauInterviewcommand: simulation_id={simulation_id}, agent_count={len(interviews)}, platform={platform}")

        return cls.interview_agents_batch(
            simulation_id=simulation_id,
            interviews=interviews,
            platform=platform,
            timeout=timeout
        )
    
    @classmethod
    def close_simulation_env(
        cls,
        simulation_id: str,
        timeout: float = 30.0
    ) -> Dict[str, Any]:
        """
        Close the simulation environment (does not stop the simulation process)
        
        Send a close-environment command to the simulation; it gracefully exits command/wait mode
        
        Args:
            simulation_id: simulateID
            timeout: duration (seconds)
            
        Returns:
            operateresultdict
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"simulateNot Exist: {simulation_id}")
        
        ipc_client = SimulationIPCClient(sim_dir)
        
        if not ipc_client.check_env_alive():
            return {
                "success": True,
                "message": "EnvironmentalreadyClose"
            }
        
        logger.info(f"SendCloseEnvironmentcommand: simulation_id={simulation_id}")
        
        try:
            response = ipc_client.send_close_env(timeout=timeout)
            
            return {
                "success": response.status.value == "completed",
                "message": "EnvironmentClosecommandSend",
                "result": response.result,
                "timestamp": response.timestamp
            }
        except TimeoutError:
            # hourcancanarebecauseforEnvironmentpositiveatClose
            return {
                "success": True,
                "message": "Environment close command sent (while waiting for a response, the environment may already be closing)"
            }
    
    @classmethod
    def _get_interview_history_from_db(
        cls,
        db_path: str,
        platform_name: str,
        agent_id: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """fromsingleDatalibraryGetInterviewhistorical"""
        import sqlite3
        
        if not os.path.exists(db_path):
            return []
        
        results = []
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            if agent_id is not None:
                cursor.execute("""
                    SELECT user_id, info, created_at
                    FROM trace
                    WHERE action = 'interview' AND user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (agent_id, limit))
            else:
                cursor.execute("""
                    SELECT user_id, info, created_at
                    FROM trace
                    WHERE action = 'interview'
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (limit,))
            
            for user_id, info_json, created_at in cursor.fetchall():
                try:
                    info = json.loads(info_json) if info_json else {}
                except json.JSONDecodeError:
                    info = {"raw": info_json}
                
                results.append({
                    "agent_id": user_id,
                    "response": info.get("response", info),
                    "prompt": info.get("prompt", ""),
                    "timestamp": created_at,
                    "platform": platform_name
                })
            
            conn.close()
            
        except Exception as e:
            logger.error(f"ReadInterviewhistoricalfail ({platform_name}): {e}")
        
        return results

    @classmethod
    def get_interview_history(
        cls,
        simulation_id: str,
        platform: str = None,
        agent_id: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get the interview history records (read from the database)
        
        Args:
            simulation_id: simulateID
            platform: platform type (reddit/twitter/None)
                - "reddit": onlyGetRedditPlatformhistorical
                - "twitter": onlyGetTwitterPlatformhistorical
                - None: GettwoPlatformhashistorical
            agent_id: specified agent ID (optional; only retrieves this agent's history)
            limit: eachPlatformReturnnumbermeasurelimit
            
        Returns:
            InterviewhistoricalRecordlist
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        
        results = []
        
        # mustwantqueryPlatform
        if platform in ("reddit", "twitter"):
            platforms = [platform]
        else:
            # When no platform is specified, query both platforms
            platforms = ["twitter", "reddit"]
        
        for p in platforms:
            db_path = os.path.join(sim_dir, f"{p}_simulation.db")
            platform_results = cls._get_interview_history_from_db(
                db_path=db_path,
                platform_name=p,
                agent_id=agent_id,
                limit=limit
            )
            results.extend(platform_results)
        
        # Timedowngradeordersort
        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
        # When querying multiple platforms, limit the count
        if len(platforms) > 1 and len(results) > limit:
            results = results[:limit]
        
        return results

