"""
simulateIPCinfomodule
useatFlaskAfterendsumsimulatefootthisofBetweenenterprogramBetweeninfo

Implements a simple command/response mode via the file system:
1. FlaskWritecommandto commands/ Directory
2. The simulation script polls the commands directory, executes the command, and writes the response to the responses/ directory
3. FlaskroundresponseDirectoryGetresult
"""

import os
import json
import time
import uuid
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..utils.logger import get_logger

logger = get_logger('mirofish.simulation_ipc')


class CommandType(str, Enum):
    """commandType"""
    INTERVIEW = "interview"           # singleAgentinterview
    BATCH_INTERVIEW = "batch_interview"  # batchinterview
    CLOSE_ENV = "close_env"           # CloseEnvironment


class CommandStatus(str, Enum):
    """commandStatus"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class IPCCommand:
    """IPCcommand"""
    command_id: str
    command_type: CommandType
    args: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "command_id": self.command_id,
            "command_type": self.command_type.value,
            "args": self.args,
            "timestamp": self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IPCCommand':
        return cls(
            command_id=data["command_id"],
            command_type=CommandType(data["command_type"]),
            args=data.get("args", {}),
            timestamp=data.get("timestamp", datetime.now().isoformat())
        )


@dataclass
class IPCResponse:
    """IPCresponse"""
    command_id: str
    status: CommandStatus
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "command_id": self.command_id,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "timestamp": self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IPCResponse':
        return cls(
            command_id=data["command_id"],
            status=CommandStatus(data["status"]),
            result=data.get("result"),
            error=data.get("error"),
            timestamp=data.get("timestamp", datetime.now().isoformat())
        )


class SimulationIPCClient:
    """
    Simulation IPC client (used by the Flask backend)
    
    useattowardssimulateenterprogramSendcommandandwaitresponse
    """
    
    def __init__(self, simulation_dir: str):
        """
        InitializeIPCclientend
        
        Args:
            simulation_dir: simulateDataDirectory
        """
        self.simulation_dir = simulation_dir
        self.commands_dir = os.path.join(simulation_dir, "ipc_commands")
        self.responses_dir = os.path.join(simulation_dir, "ipc_responses")
        
        # keepDirectory exists
        os.makedirs(self.commands_dir, exist_ok=True)
        os.makedirs(self.responses_dir, exist_ok=True)
    
    def send_command(
        self,
        command_type: CommandType,
        args: Dict[str, Any],
        timeout: float = 60.0,
        poll_interval: float = 0.5
    ) -> IPCResponse:
        """
        Sendcommandandwaitresponse
        
        Args:
            command_type: commandType
            args: commandParameter
            timeout: timeout duration (seconds)
            poll_interval: polling interval (seconds)
            
        Returns:
            IPCResponse
            
        Raises:
            TimeoutError: waitresponsehour
        """
        command_id = str(uuid.uuid4())
        command = IPCCommand(
            command_id=command_id,
            command_type=command_type,
            args=args
        )
        
        # WritecommandFile
        command_file = os.path.join(self.commands_dir, f"{command_id}.json")
        with open(command_file, 'w', encoding='utf-8') as f:
            json.dump(command.to_dict(), f, ensure_ascii=False, indent=2)
        
        logger.info(f"SendIPCcommand: {command_type.value}, command_id={command_id}")
        
        # waitresponse
        response_file = os.path.join(self.responses_dir, f"{command_id}.json")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if os.path.exists(response_file):
                try:
                    with open(response_file, 'r', encoding='utf-8') as f:
                        response_data = json.load(f)
                    response = IPCResponse.from_dict(response_data)
                    
                    # CleanupcommandsumresponseFile
                    try:
                        os.remove(command_file)
                        os.remove(response_file)
                    except OSError:
                        pass
                    
                    logger.info(f"accepttoIPCresponse: command_id={command_id}, status={response.status.value}")
                    return response
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"parseresponsefail: {e}")
            
            time.sleep(poll_interval)
        
        # hour
        logger.error(f"waitIPCresponsehour: command_id={command_id}")
        
        # CleanupcommandFile
        try:
            os.remove(command_file)
        except OSError:
            pass
        
        raise TimeoutError(f"waitcommandresponsehour ({timeout}second)")
    
    def send_interview(
        self,
        agent_id: int,
        prompt: str,
        platform: str = None,
        timeout: float = 60.0
    ) -> IPCResponse:
        """
        SendsingleAgentinterviewcommand
        
        Args:
            agent_id: Agent ID
            prompt: interviewquestion
            platform: target platform (optional)
                - "twitter": onlyinterviewTwitterPlatform
                - "reddit": onlyinterviewRedditPlatform  
                - None: in dual-platform simulation, interview both platforms simultaneously; in single-platform simulation, interview that platform
            timeout: hourTime
            
        Returns:
            IPCResponse, whose result field contains the interview result
        """
        args = {
            "agent_id": agent_id,
            "prompt": prompt
        }
        if platform:
            args["platform"] = platform
            
        return self.send_command(
            command_type=CommandType.INTERVIEW,
            args=args,
            timeout=timeout
        )
    
    def send_batch_interview(
        self,
        interviews: List[Dict[str, Any]],
        platform: str = None,
        timeout: float = 120.0
    ) -> IPCResponse:
        """
        Sendbatchinterviewcommand
        
        Args:
            interviews: interview list, each element contains {"agent_id": int, "prompt": str, "platform": str(optional)}
            platform: default platform (optional, can be overridden per interview item)
                - "twitter": DefaultonlyinterviewTwitterPlatform
                - "reddit": DefaultonlyinterviewRedditPlatform
                - None: doublePlatformsimulatehoureachAgentsimultaneouslyinterviewtwoPlatform
            timeout: hourTime
            
        Returns:
            IPCResponse, whose result field contains all interview results
        """
        args = {"interviews": interviews}
        if platform:
            args["platform"] = platform
            
        return self.send_command(
            command_type=CommandType.BATCH_INTERVIEW,
            args=args,
            timeout=timeout
        )
    
    def send_close_env(self, timeout: float = 30.0) -> IPCResponse:
        """
        SendCloseEnvironmentcommand
        
        Args:
            timeout: hourTime
            
        Returns:
            IPCResponse
        """
        return self.send_command(
            command_type=CommandType.CLOSE_ENV,
            args={},
            timeout=timeout
        )
    
    def check_env_alive(self) -> bool:
        """
        checksimulateEnvironmentwhetherstorelive
        
        viacheck env_status.json Filefuturecut
        """
        status_file = os.path.join(self.simulation_dir, "env_status.json")
        if not os.path.exists(status_file):
            return False
        
        try:
            with open(status_file, 'r', encoding='utf-8') as f:
                status = json.load(f)
            return status.get("status") == "alive"
        except (json.JSONDecodeError, OSError):
            return False


class SimulationIPCServer:
    """
    Simulation IPC server (used by the simulation script)
    
    Polls the commands directory, executes commands, and returns responses.
    """
    
    def __init__(self, simulation_dir: str):
        """
        InitializeIPCServiceer
        
        Args:
            simulation_dir: simulateDataDirectory
        """
        self.simulation_dir = simulation_dir
        self.commands_dir = os.path.join(simulation_dir, "ipc_commands")
        self.responses_dir = os.path.join(simulation_dir, "ipc_responses")
        
        # keepDirectory exists
        os.makedirs(self.commands_dir, exist_ok=True)
        os.makedirs(self.responses_dir, exist_ok=True)
        
        # EnvironmentStatus
        self._running = False
    
    def start(self):
        """MarkServiceerforRunStatus"""
        self._running = True
        self._update_env_status("alive")
    
    def stop(self):
        """MarkServiceerforstopStatus"""
        self._running = False
        self._update_env_status("stopped")
    
    def _update_env_status(self, status: str):
        """moreNewEnvironmentStatusFile"""
        status_file = os.path.join(self.simulation_dir, "env_status.json")
        with open(status_file, 'w', encoding='utf-8') as f:
            json.dump({
                "status": status,
                "timestamp": datetime.now().isoformat()
            }, f, ensure_ascii=False, indent=2)
    
    def poll_commands(self) -> Optional[IPCCommand]:
        """
        Poll the commands directory and return the first pending command
        
        Returns:
            IPCCommand or None
        """
        if not os.path.exists(self.commands_dir):
            return None
        
        # TimesortGetcommandFile
        command_files = []
        for filename in os.listdir(self.commands_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(self.commands_dir, filename)
                command_files.append((filepath, os.path.getmtime(filepath)))
        
        command_files.sort(key=lambda x: x[1])
        
        for filepath, _ in command_files:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return IPCCommand.from_dict(data)
            except (json.JSONDecodeError, KeyError, OSError) as e:
                logger.warning(f"ReadcommandFilefail: {filepath}, {e}")
                continue
        
        return None
    
    def send_response(self, response: IPCResponse):
        """
        Sendresponse
        
        Args:
            response: IPCresponse
        """
        response_file = os.path.join(self.responses_dir, f"{response.command_id}.json")
        with open(response_file, 'w', encoding='utf-8') as f:
            json.dump(response.to_dict(), f, ensure_ascii=False, indent=2)
        
        # deletecommandFile
        command_file = os.path.join(self.commands_dir, f"{response.command_id}.json")
        try:
            os.remove(command_file)
        except OSError:
            pass
    
    def send_success(self, command_id: str, result: Dict[str, Any]):
        """Sendsuccessresponse"""
        self.send_response(IPCResponse(
            command_id=command_id,
            status=CommandStatus.COMPLETED,
            result=result
        ))
    
    def send_error(self, command_id: str, error: str):
        """SendErrorresponse"""
        self.send_response(IPCResponse(
            command_id=command_id,
            status=CommandStatus.FAILED,
            error=error
        ))
