"""
Report Agent Service
Use LangChain + Zep to implement ReAct mode for simulation report generation

Features:
1. Generate reports based on simulation requirements and Zep Graph information
2. First plan the directory structure, then generate in segments
3. Each segment adopts ReAct multi-round thinking and reflection mode
4. Support user chat, autonomously invoking the retrieval tool during chat
"""

import os
import json
import time
import re
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..config import Config
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger
from .zep_tools import (
    ZepToolsService, 
    SearchResult, 
    InsightForgeResult, 
    PanoramaResult,
    InterviewResult
)
from .world_state_report import WorldStateReport

logger = get_logger('mirofish.report_agent')


class ReportLogger:
    """
    Report Agent detailed log recorder
    
    Generate an agent_log.jsonl file in the report folder, recording every detailed action.
    each line is a complete JSON object, containing timestamp, action type, detailed content, etc.
    """
    
    def __init__(self, report_id: str):
        """
        Initialize the log recorder
        
        Args:
            report_id: report ID, used to determine the log file path
        """
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'agent_log.jsonl'
        )
        self.start_time = datetime.now()
        self._ensure_log_file()
    
    def _ensure_log_file(self):
        """Ensure the log file directory exists"""
        log_dir = os.path.dirname(self.log_file_path)
        os.makedirs(log_dir, exist_ok=True)
    
    def _get_elapsed_time(self) -> float:
        """Get elapsed time from start to now in seconds"""
        return (datetime.now() - self.start_time).total_seconds()
    
    def log(
        self, 
        action: str, 
        stage: str,
        details: Dict[str, Any],
        section_title: str = None,
        section_index: int = None
    ):
        """
        Record an edge log entry
        
        Args:
            action: Action type, e.g. 'start', 'tool_call', 'llm_response', 'section_complete', etc.
            stage: current stage, e.g. 'planning', 'generating', 'completed'
            details: detailed content dict, not truncated
            section_title: current section title (optional)
            section_index: current section index (optional)
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "elapsed_seconds": round(self._get_elapsed_time(), 2),
            "report_id": self.report_id,
            "action": action,
            "stage": stage,
            "section_title": section_title,
            "section_index": section_index,
            "details": details
        }
        
        # Append and write JSONL File
        with open(self.log_file_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
    
    def log_start(self, simulation_id: str, graph_id: str, simulation_requirement: str):
        """Record report generation start"""
        self.log(
            action="report_start",
            stage="pending",
            details={
                "simulation_id": simulation_id,
                "graph_id": graph_id,
                "simulation_requirement": simulation_requirement,
                "message": "Report generation task started"
            }
        )
    
    def log_planning_start(self):
        """Record outline planning start"""
        self.log(
            action="planning_start",
            stage="planning",
            details={"message": "Start planning report outline"}
        )
    
    def log_planning_context(self, context: Dict[str, Any]):
        """Record context information obtained during planning"""
        self.log(
            action="planning_context",
            stage="planning",
            details={
                "message": "Obtained simulation context information",
                "context": context
            }
        )
    
    def log_planning_complete(self, outline_dict: Dict[str, Any]):
        """Record outline planning complete"""
        self.log(
            action="planning_complete",
            stage="planning",
            details={
                "message": "Outline planning complete",
                "outline": outline_dict
            }
        )
    
    def log_section_start(self, section_title: str, section_index: int):
        """Record section generation start"""
        self.log(
            action="section_start",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={"message": f"Start generating section: {section_title}"}
        )
    
    def log_react_thought(self, section_title: str, section_index: int, iteration: int, thought: str):
        """Record the ReAct thinking process"""
        self.log(
            action="react_thought",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "thought": thought,
                "message": f"ReAct round {iteration} thinking"
            }
        )
    
    def log_tool_call(
        self, 
        section_title: str, 
        section_index: int,
        tool_name: str, 
        parameters: Dict[str, Any],
        iteration: int
    ):
        """Record a tool invocation"""
        self.log(
            action="tool_call",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "tool_name": tool_name,
                "parameters": parameters,
                "message": f"Invoke tool: {tool_name}"
            }
        )
    
    def log_tool_result(
        self,
        section_title: str,
        section_index: int,
        tool_name: str,
        result: str,
        iteration: int
    ):
        """Record tool invocation result (complete content, not truncated)"""
        self.log(
            action="tool_result",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "tool_name": tool_name,
                "result": result,  # complete result, not truncated
                "result_length": len(result),
                "message": f"tool {tool_name} returned result"
            }
        )
    
    def log_llm_response(
        self,
        section_title: str,
        section_index: int,
        response: str,
        iteration: int,
        has_tool_calls: bool,
        has_final_answer: bool
    ):
        """Record LLM response (complete content, not truncated)"""
        self.log(
            action="llm_response",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "response": response,  # complete response, not truncated
                "response_length": len(response),
                "has_tool_calls": has_tool_calls,
                "has_final_answer": has_final_answer,
                "message": f"LLM response (tool call: {has_tool_calls}, final answer: {has_final_answer})"
            }
        )
    
    def log_section_content(
        self,
        section_title: str,
        section_index: int,
        content: str,
        tool_calls_count: int
    ):
        """Record section content generation complete (only records content, not the entire section complete)"""
        self.log(
            action="section_content",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "content": content,  # complete content, not truncated
                "content_length": len(content),
                "tool_calls_count": tool_calls_count,
                "message": f"section {section_title} content generation complete"
            }
        )
    
    def log_section_full_complete(
        self,
        section_title: str,
        section_index: int,
        full_content: str
    ):
        """
        Record section generation complete

        Should be logged before the end to check whether a section truly completed, and get the complete content
        """
        self.log(
            action="section_complete",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "content": full_content,
                "content_length": len(full_content),
                "message": f"section {section_title} generation complete"
            }
        )
    
    def log_report_complete(self, total_sections: int, total_time_seconds: float):
        """Record report generation complete"""
        self.log(
            action="report_complete",
            stage="completed",
            details={
                "total_sections": total_sections,
                "total_time_seconds": round(total_time_seconds, 2),
                "message": "Report generation complete"
            }
        )
    
    def log_error(self, error_message: str, stage: str, section_title: str = None):
        """Record an error"""
        self.log(
            action="error",
            stage=stage,
            section_title=section_title,
            section_index=None,
            details={
                "error": error_message,
                "message": f"Error occurred: {error_message}"
            }
        )


class ReportConsoleLogger:
    """
    Report Agent console log recorder
    
    Writes console-style logs (INFO, WARNING, etc.) to the console_log.txt file in the report folder.
    Unlike agent_log.jsonl, this log is plain-text-format console output.
    """
    
    def __init__(self, report_id: str):
        """
        Initialize the console log recorder
        
        Args:
            report_id: report ID, used to determine the log file path
        """
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'console_log.txt'
        )
        self._ensure_log_file()
        self._file_handler = None
        self._setup_file_handler()
    
    def _ensure_log_file(self):
        """Ensure the log file directory exists"""
        log_dir = os.path.dirname(self.log_file_path)
        os.makedirs(log_dir, exist_ok=True)
    
    def _setup_file_handler(self):
        """Set up the file handler to simultaneously write logs to a file"""
        import logging
        
        # Create file handler
        self._file_handler = logging.FileHandler(
            self.log_file_path,
            mode='a',
            encoding='utf-8'
        )
        self._file_handler.setLevel(logging.INFO)
        
        # Use the same concise format as the console
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s: %(message)s',
            datefmt='%H:%M:%S'
        )
        self._file_handler.setFormatter(formatter)
        
        # Add to report_agent-related loggers
        loggers_to_attach = [
            'mirofish.report_agent',
            'mirofish.zep_tools',
        ]
        
        for logger_name in loggers_to_attach:
            target_logger = logging.getLogger(logger_name)
            # Avoid repeatedly adding
            if self._file_handler not in target_logger.handlers:
                target_logger.addHandler(self._file_handler)
    
    def close(self):
        """Close the file handler and remove it from the loggers"""
        import logging
        
        if self._file_handler:
            loggers_to_detach = [
                'mirofish.report_agent',
                'mirofish.zep_tools',
            ]
            
            for logger_name in loggers_to_detach:
                target_logger = logging.getLogger(logger_name)
                if self._file_handler in target_logger.handlers:
                    target_logger.removeHandler(self._file_handler)
            
            self._file_handler.close()
            self._file_handler = None
    
    def __del__(self):
        """Close the file handler when destroyed"""
        self.close()


class ReportStatus(str, Enum):
    """Report status"""
    PENDING = "pending"
    PLANNING = "planning"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class ReportSection:
    """Report section"""
    title: str
    content: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content
        }

    def to_markdown(self, level: int = 2) -> str:
        """Convert to Markdown format"""
        md = f"{'#' * level} {self.title}\n\n"
        if self.content:
            md += f"{self.content}\n\n"
        return md


@dataclass
class ReportOutline:
    """Report outline"""
    title: str
    summary: str
    sections: List[ReportSection]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "sections": [s.to_dict() for s in self.sections]
        }
    
    def to_markdown(self) -> str:
        """Convert to Markdown format"""
        md = f"# {self.title}\n\n"
        md += f"> {self.summary}\n\n"
        for section in self.sections:
            md += section.to_markdown()
        return md


@dataclass
class Report:
    """Complete report"""
    report_id: str
    simulation_id: str
    graph_id: str
    simulation_requirement: str
    status: ReportStatus
    outline: Optional[ReportOutline] = None
    markdown_content: str = ""
    created_at: str = ""
    completed_at: str = ""
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "simulation_id": self.simulation_id,
            "graph_id": self.graph_id,
            "simulation_requirement": self.simulation_requirement,
            "status": self.status.value,
            "outline": self.outline.to_dict() if self.outline else None,
            "markdown_content": self.markdown_content,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error
        }


# ═══════════════════════════════════════════════════════════════
# Prompt template definitions
# ═══════════════════════════════════════════════════════════════

# ── Tool descriptions ──

TOOL_DESC_INSIGHT_FORGE = """\
【Deep Insight Retrieval - Powerful Search Tool】
This is our powerful search function, specially designed for deep analysis. It will:
1. Automatically decompose your question into multiple sub-questions
2. Retrieve information from the simulation graph across multiple dimensions
3. Integrate semantic search, entity analysis, and relationship chain results
4. Return the most comprehensive and in-depth retrieved content

【Use scenarios】
- When you need to deeply analyze a question
- When you need to understand all aspects of an event
- When you need abundant material for a report section

【Returned content】
- Relevant facts and source documents (citable)
- Core entity insights
- Relationship chain analysis"""

TOOL_DESC_PANORAMA_SEARCH = """\
【Breadth Search - Get the Full Panoramic View】
This tool retrieves the complete panorama of simulation results, especially suited for understanding the event evolution process. It will:
1. Get related nodes and relationships
2. Distinguish current valid facts from historical/expired facts
3. Help you understand how sentiment evolves

【Use scenarios】
- When you need to understand the complete event progression
- When you want to observe sentiment changes across different stages
- When you need comprehensive entity and relationship information

【Returned content】
- Current valid facts (simulation latest results)
- Historical/expired facts (evolution record)
- Related entities"""

TOOL_DESC_QUICK_SEARCH = """\
【Quick Search - Fast Retrieval】
A lightweight fast retrieval tool that combines simple, related information queries.

【Use scenarios】
- When you need to quickly find a specific entity's information
- When you need to verify a fact
- Simple information retrieval

【Returned content】
- List of facts most relevant to the query"""

TOOL_DESC_INTERVIEW_AGENTS = """\
【Deep Interview - Real Agent Interview (Dual-Platform)】
Calls the OASIS simulation environment interview API to conduct real interviews with the running simulation agents!
This is not an LLM simulation, but rather calls the real interview interface to get the simulation agents' original answers.
By default, it interviews on both Twitter and Reddit platforms simultaneously, to obtain more comprehensive viewpoints.

Workflow:
1. Auto-read persona files to understand what simulation agents exist
2. Intelligently select the agents most relevant to the interview topic (e.g. students, media, officials)
3. Auto-generate interview questions
4. Call the /api/simulation/interview/batch interface to conduct real interviews on both platforms
5. Integrate all interview results for multi-perspective analysis

【Use scenarios】
- When you need to understand views on the event from different role/perspective standpoints (How do students view it? How does the media view it? What do officials say?)
- When you need to collect multiple opinions and stances
- When you need to get real answers from the simulation agents (from the OASIS simulation environment)
- When you want the report to be more vivid, including "interview transcripts"

【Returned content】
- Identity information of the interviewed agents
- Each agent's interview answers on both Twitter and Reddit platforms
- Key quotes (citable)
- Interview key points and viewpoint tendencies

【Important】 Requires the OASIS simulation environment to be running to use this function!"""

# ── Outline planning prompt ──

PLAN_SYSTEM_PROMPT = """\
You are a "Future Prediction Report" professional expert, holding a "top-down view" of the simulation world — you can observe every agent's behavior, discussions, and movements within the simulation.

【Core logic】
We built a simulation world and injected a specific "simulation requirement" into it as a change measure. The results the simulation world exhibits are predictions of situations that may happen in the future. What you are observing is not "actual test data", but "future pre-enactment".

【Your task】
Write a "Future Prediction Report", answering:
1. Under our set conditions, what will happen in the future?
2. How will each type of agent (group) react and act?
3. What future trends and risks worth attention does this simulation reveal?

【Report key points】
- ✅ This is a future prediction report based on simulation, revealing "if it's like this, how the future will be"
- ✅ Focus on prediction results: event trajectory, group reactions, emerging phenomena, risks
- ✅ Agent behavior in the simulation world is a prediction of future group behavior
- ❌ It is not an analysis of the real world
- ❌ It is not just talking about emotion

【Section count limit】
- At least 2 sections, at most 5 sections
- No sub-sections needed; each section should be coherent, complete content
- Content should be concise, focusing on core prediction findings
- Section structure is designed by you autonomously based on prediction results

Please output the report outline in JSON format, as follows:
{
    "title": "report title",
    "summary": "report summary (one sentence summarizing core prediction findings)",
    "sections": [
        {
            "title": "section title",
            "description": "section content description"
        }
    ]
}

Note: The sections array should have at least 2 and at most 5 elements!"""

PLAN_USER_PROMPT_TEMPLATE = """\
【Prediction scenario setup】
The change measure (simulation requirement) we injected into the simulation world: {simulation_requirement}

【Simulation world scale】
- Number of entities participating in the simulation: {total_nodes}
- Number of relationships between entities: {total_edges}
- Entity type distribution: {entity_types}
- Number of living agents: {total_entities}

【Simulation-prediction-related future facts】
{related_facts_json}

【Computed world-state summary】
{world_state_summary}

Please view this simulation from a top-down view:
1. Under our set conditions, what state will the future show?
2. How will each type of group (agent) react and act?
3. What future trends worth attention does this simulation reveal?

Based on the prediction results, design the most suitable report section structure.

【Reminder】 Report section count: at least 2, at most 5; content should be concise and focus on core prediction findings."""

# ── Section generation prompt ──

SECTION_SYSTEM_PROMPT_TEMPLATE = """\
You are a "Future Prediction Report" professional expert, currently writing a section of the report.

Report title: {report_title}
Report summary: {report_summary}
Prediction scenario (simulation requirement): {simulation_requirement}

Current section to write: {section_title}

═══════════════════════════════════════════════════════════════
【Core logic】
═══════════════════════════════════════════════════════════════

The simulation world is a pre-enactment of the future. We injected specific conditions (simulation requirement) into the simulation world;
the behavior and movements of agents in the simulation are predictions of future group behavior.

Your task is to:
- Reveal what will happen in the future under the set conditions
- Predict how each type of group (agent) will react and act
- Discover trends, risks, opportunities, and quantitative outcomes worth attention
- When the active domain provides computed metrics, report those values exactly.

❌ Do not write it as an analysis of the real world
✅ Focus on "how the future will be" — the simulation results are predictions of the future

═══════════════════════════════════════════════════════════════
【Most important rules - must follow】
═══════════════════════════════════════════════════════════════

1. 【Must invoke tools to observe the simulation world】
   - You are observing the future pre-enactment from a "top-down view"
   - All content must come from events and agent movements happening in the simulation world
   - Forbidden to use your own pre-existing knowledge for report content
   - Each section must invoke at least 3 tools (at most 5) to observe the simulation world and generate the future

2. 【Must use the agents' original statements】
   - Agents' statements and behaviors are predictions of future group behavior
   - In the report, use quote format to display these predictions, for example:
     > "Some type of group will state: source document content..."
   - These quotes are the core data of the simulation prediction

3. 【English-only output】
   - All report prose, quotations, section titles, explanations, and tool summaries MUST be written in English.
   - Tool-returned content may contain Chinese or other languages; translate its meaning into English before using it.
   - Never copy Chinese characters into the report, even inside quote blocks.
   - Preserve the source meaning while translating; do not invent facts.
   - This rule applies to the body text, headings, metadata, and every quote block.

4. 【Genuine simulation results and computed numbers】
   - Report content must reflect results generated in the simulation world.
   - Quantitative claims MUST come from the `query_world_state` tool output; do not estimate or invent numbers in prose.
   - Distinguish computed outcomes (fills, P&L, resources, rankings, failure rates) from agent statements and interpretations.
   - Do not add information that does not exist in the simulation.
   - If information in some aspects is insufficient, state it honestly.

═══════════════════════════════════════════════════════════════
【⚠️ Format norms - this is important!】
═══════════════════════════════════════════════════════════════

【A section = the smallest content unit】
- Each section is the smallest block unit of the report
- ❌ Forbidden to use any Markdown headings within a section (#, ##, ###, ####, etc.)
- ❌ Forbidden to add the section main title at the start of the content
- ✅ The section title is auto-added by the system; you only need pure body content
- ✅ Use **bold**, paragraph breaks, quotes, and lists to organize content, but do not use headings

【Correct example】
```
This section analyzes the event's sentiment transition state. Through in-depth analysis of the simulation data, we discovered...

**Sending stage**

As the scene where emotion first appears, it bears the core features of information sending:

> "68% of the sending volume..."

**Emotion release stage**

The volatile platform welcomes the impact of a major release event:

- Visible emotional impact strengthened
- Emotional depth is high
```

【Error example】
```
## Execution points          ← Error! Do not add any headings
### 1. Sending stage     ← Error! Do not use ### to split into sub-sections
#### 1.1 Detailed analysis   ← Error! Do not use #### for detailed splits

This section analyzes...
```

═══════════════════════════════════════════════════════════════
【Available retrieval tools】(invoke 3-5 per section)
═══════════════════════════════════════════════════════════════

{tools_description}

【Tool usage suggestions - please mix different tools, don't only use one type】
- insight_forge: deep insight analysis, auto-decomposes questions and retrieves facts and relationships across multiple dimensions
- panorama_search: role panoramic search, understand the event's full picture, timeline, and evolution process
- quick_search: quickly verify a specific entity's information point
- interview_agents: interview simulation agents, get first-person viewpoints and real reactions from different role/perspective standpoints

═══════════════════════════════════════════════════════════════
【Workflow】
═══════════════════════════════════════════════════════════════

Each reply you can only do one of the following two things (cannot do both):

Option A - invoke a tool:
Output your thinking, then use the following format to invoke a tool:
<tool_call>
{{"name": "toolName", "parameters": {{"Parameter name": "Parameter value"}}}}
</tool_call>
The system will execute the tool and return the result to you. You do not need to and cannot fabricate tool-returned results yourself.

Option B - output final content:
When you have obtained enough information via tools, start with "Final Answer:" to output the section content.

⚠️ Strictly forbidden:
- Forbidden to include both a tool call and Final Answer in one reply
- Forbidden to write tool-returned results (Observation) yourself; tool results are injected by the system
- Each reply can invoke at most one tool

═══════════════════════════════════════════════════════════════
【Section content requirements】
═══════════════════════════════════════════════════════════════

1. Content must be based on simulation data retrieved by tools
2. Extensively use source documents to display the simulation effect
3. Use Markdown format (but no headings):
   - Use **bold text** to mark key points (instead of sub-headings)
   - Use lists (- or 1. 2. 3.) to organize key points
   - Use blank lines to separate different paragraphs
   - ❌ Forbidden to use any heading formats like #, ##, ###, ####
4. 【Quote format norm - must be an independent paragraph】
   Quotes must be independent paragraphs, with a blank line before and after; they cannot be mixed into a paragraph:

   ✅ Correct format:
   ```
   The school's response should be recognized as lacking substantial content.

   > "The school should navigate the ever-changing social media environment to gain resonance and traction."

   This evaluation is incomplete for the public.
   ```

   ❌ Error format:
   ```
   The school's response should be recognized as lacking substantial content. > "The school should navigate..." This evaluation is...
   ```
5. Maintain coherence with other sections
6. 【Avoid repetition】 Carefully read the complete section content below; do not repeatedly describe the same information
7. 【Re-emphasize】 Do not add any headings! Use **bold** to replace sub-headings"""

SECTION_USER_PROMPT_TEMPLATE = """\
completesectioncontent（pleasecarefuldetailedreadread，heavyrepeat）：
{previous_content}

═══════════════════════════════════════════════════════════════
【currenttask】section: {section_title}
═══════════════════════════════════════════════════════════════

【heavywantwake】
1. carefuldetailedreadreadUpcompletesection，heavyrepeatsamecontent！
2. startBeforemustfirstinvoketoolGetsimulateData
3. pleasemixusedifferenttool，do notonlyuseonetype
4. reportcontentmustfutureselfretrieveresult，do notuseselfownknowknow

【⚠️ formatwarning - mustfollow】
- ❌ do notanywhattitle（#、##、###、####nogo）
- ❌ do not"{section_title}"actforopenhead
- ✅ sectiontitlebySystemautoadd
- ✅ connectbody，use**coarsebody**genreplaceSmallsectiontitle

pleasestart：
1. firstthinking（Thought）thissectionneedwantwhatinformation
2. theninvoketool（Action）GetsimulateData
3. acceptcollectenoughableinformationAfteroutput Final Answer（purebody，noneanywhattitle）"""

# ── ReACT ringInternalinfotemplate ──

REACT_OBSERVATION_TEMPLATE = """\
Observation（retrieveresult）:

═══ tool {tool_name} Return ═══
{result}

═══════════════════════════════════════════════════════════════
invoketool {tool_calls_count}/{max_tool_calls} （use: {used_tools_str}）{unused_hint}
- ifinformationfillminute：to "Final Answer:" openheadoutputsectioncontent（mustuseUporiginaldoc）
- ifneedwantmoremanyinformation：invokeatoolcontinueretrieve
═══════════════════════════════════════════════════════════════"""

REACT_INSUFFICIENT_TOOLS_MSG = (
    "【】youonlyinvoke{tool_calls_count}tool，tofewneedwant{min_tool_calls}。"
    "pleaseagaininvoketoolGetmoremanysimulateData，thenagainoutput Final Answer。{unused_hint}"
)

REACT_INSUFFICIENT_TOOLS_MSG_ALT = (
    "currentonlyinvoke {tool_calls_count} tool，tofewneedwant {min_tool_calls} 。"
    "pleaseinvoketoolGetsimulateData。{unused_hint}"
)

REACT_TOOL_LIMIT_MSG = (
    "toolinvokenumberarriveUp（{tool_calls_count}/{max_tool_calls}），nocanagaininvoketool。"
    'pleaseinstantbased onGetinformation，to "Final Answer:" openheadoutputsectioncontent。'
)

REACT_UNUSED_TOOLS_HINT = "\n💡 youalsonohaveusepast: {unused_list}，suggestiontestdifferenttoolGetmanyroledepthinformation"

REACT_FORCE_FINAL_MSG = "arrivetotoolinvokelimit，pleaseconnectoutput Final Answer: andGeneratesectioncontent。"

# ── Chat prompt ──

CHAT_SYSTEM_PROMPT_TEMPLATE = """\
youareaconciseHigheffectsimulatePredictionhelphand。

【background】
Predictioncondition: {simulation_requirement}

【Generateanalyzereport】
{report_content}

【rules】
1. excellentfirstbased onUpreportcontentreturnanswerquestion
2. connectreturnanswerquestion，Longthinkingdiscuss
3. onlyatreportcontentnoenoughtoreturnanswerhour，invoketoolretrievemoremanyData
4. returnanswerwantconcise、clear、haveedgelogic

【availabletool】（onlyatneedwanthouruse，mostmanyinvoke1-2）
{tools_description}

【toolinvokeformat】
<tool_call>
{{"name": "toolName", "parameters": {{"Parametername": "Parametervalue"}}}}
</tool_call>

【returnanswerstyle】
- conciseconnect，do notLongessayLargediscuss
- use > formatusekeycontent
- excellentfirstgiveoutconclusion，againuntiereleaseoriginalbecause"""

CHAT_OBSERVATION_SUFFIX = "\n\npleaseconcisereturnanswerquestion。"


# ═══════════════════════════════════════════════════════════════
# ReportAgent maintype
# ═══════════════════════════════════════════════════════════════


class ReportAgent:
    """
    Report Agent - simulateReport GenerationAgent

    adoptReACT（Reasoning + Acting）mode：
    1. planstage：analyzesimulaterequirement，planreportDirectorystructure
    2. Generatestage：sectionGeneratecontent，eachsectioncanmanyinvoketoolGetinformation
    3. reflectionstage：checkcontentcompletesumallow
    """
    
    # mostLargetoolinvokenumber（eachsection）
    MAX_TOOL_CALLS_PER_SECTION = 5
    
    # mostLargereflectionroundnumber
    MAX_REFLECTION_ROUNDS = 3
    
    # towardchatMiddlemostLargetoolinvokenumber
    MAX_TOOL_CALLS_PER_CHAT = 2
    
    def __init__(
        self, 
        graph_id: str,
        simulation_id: str,
        simulation_requirement: str,
        llm_client: Optional[LLMClient] = None,
        zep_tools: Optional[ZepToolsService] = None
    ):
        """
        InitializeReport Agent
        
        Args:
            graph_id: GraphID
            simulation_id: simulateID
            simulation_requirement: simulaterequirementDescription
            llm_client: LLMclientend（Optional）
            zep_tools: ZeptoolService（Optional）
        """
        self.graph_id = graph_id
        self.simulation_id = simulation_id
        self.simulation_requirement = simulation_requirement
        
        self.llm = llm_client or LLMClient()
        self.zep_tools = zep_tools or ZepToolsService()
        self.world_state = WorldStateReport(simulation_id)
        self.stop_requested = False
        
        # toolmustmeaning
        self.tools = self._define_tools()
        
        # logRecorder（at generate_report MiddleInitialize）
        self.report_logger: Optional[ReportLogger] = None
        # controllogRecorder（at generate_report MiddleInitialize）
        self.console_logger: Optional[ReportConsoleLogger] = None
        
        logger.info(f"ReportAgent Initializecomplete: graph_id={graph_id}, simulation_id={simulation_id}")
    
    def _define_tools(self) -> Dict[str, Dict[str, Any]]:
        """mustmeaningavailabletool"""
        return {
            "insight_forge": {
                "name": "insight_forge",
                "description": TOOL_DESC_INSIGHT_FORGE,
                "parameters": {
                    "query": "youthinkdeepinanalyzequestionorchatquestion",
                    "report_context": "currentreportsectionUpunderdoc（Optional，havehelpatGeneratemorefineallowstudentquestion）"
                }
            },
            "panorama_search": {
                "name": "panorama_search",
                "description": TOOL_DESC_PANORAMA_SEARCH,
                "parameters": {
                    "query": "search query，useatrelevantsort",
                    "include_expired": "whethercontainpastperiod/historicalcontent（DefaultTrue）"
                }
            },
            "quick_search": {
                "name": "quick_search",
                "description": TOOL_DESC_QUICK_SEARCH,
                "parameters": {
                    "query": "search querycharacterstring",
                    "limit": "Returnresultnumbermeasure（Optional，Default10）"
                }
            },
            "interview_agents": {
                "name": "interview_agents",
                "description": TOOL_DESC_INTERVIEW_AGENTS,
                "parameters": {
                    "interview_topic": "interview main question or requirement",
                    "max_agents": "maximum number of interview targets (default 5, max 10)"
                }
            },
            "query_world_state": {
                "name": "query_world_state",
                "description": (
                    "Read-only computed metrics from the active domain's world state. "
                    "Use this for every quantitative claim: P&L, rankings, resource "
                    "totals, action counts, failure rates, or time series. Never invent "
                    "numbers that this tool can answer."
                ),
                "parameters": {
                    "metric": "metric name, or empty for all available metrics",
                    "round_range": "optional [first_round, last_round]"
                }
            }
        }
    
    def _execute_tool(self, tool_name: str, parameters: Dict[str, Any], report_context: str = "") -> str:
        """
        executetoolinvoke
        
        Args:
            tool_name: toolName
            parameters: toolParameter
            report_context: reportUpunderdoc（useatInsightForge）
            
        Returns:
            toolexecuteresult（textformat）
        """
        logger.info(f"executetool: {tool_name}, Parameter: {parameters}")
        
        try:
            if tool_name == "insight_forge":
                query = parameters.get("query", "")
                ctx = parameters.get("report_context", "") or report_context
                result = self.zep_tools.insight_forge(
                    graph_id=self.graph_id,
                    query=query,
                    simulation_requirement=self.simulation_requirement,
                    report_context=ctx
                )
                return result.to_text()
            
            elif tool_name == "panorama_search":
                # breadthsearch - Getallappearance
                query = parameters.get("query", "")
                include_expired = parameters.get("include_expired", True)
                if isinstance(include_expired, str):
                    include_expired = include_expired.lower() in ['true', '1', 'yes']
                result = self.zep_tools.panorama_search(
                    graph_id=self.graph_id,
                    query=query,
                    include_expired=include_expired
                )
                return result.to_text()
            
            elif tool_name == "quick_search":
                # simplesearch - quickretrieve
                query = parameters.get("query", "")
                limit = parameters.get("limit", 10)
                if isinstance(limit, str):
                    limit = int(limit)
                result = self.zep_tools.quick_search(
                    graph_id=self.graph_id,
                    query=query,
                    limit=limit
                )
                return result.to_text()
            
            elif tool_name == "interview_agents":
                interview_topic = parameters.get("interview_topic", parameters.get("query", ""))
                max_agents = parameters.get("max_agents", 5)
                if isinstance(max_agents, str):
                    max_agents = int(max_agents)
                max_agents = min(max_agents, 10)
                result = self.zep_tools.interview_agents(
                    simulation_id=self.simulation_id,
                    interview_requirement=interview_topic,
                    simulation_requirement=self.simulation_requirement,
                    max_agents=max_agents
                )
                return result.to_text()

            elif tool_name == "query_world_state":
                metric = parameters.get("metric", "")
                round_range = parameters.get("round_range")
                if isinstance(round_range, str):
                    try:
                        round_range = json.loads(round_range)
                    except json.JSONDecodeError:
                        round_range = None
                return json.dumps(
                    self.world_state.query(metric=metric, round_range=round_range),
                    ensure_ascii=False, indent=2, default=str
                )
            
            # ========== towardsAftercompatibleOldtool（InternaldeptheavymusttowardstoNewtool） ==========
            
            elif tool_name == "search_graph":
                # heavymusttowardsto quick_search
                logger.info("search_graph heavymusttowardsto quick_search")
                return self._execute_tool("quick_search", parameters, report_context)
            
            elif tool_name == "get_graph_statistics":
                result = self.zep_tools.get_graph_statistics(self.graph_id)
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            elif tool_name == "get_entity_summary":
                entity_name = parameters.get("entity_name", "")
                result = self.zep_tools.get_entity_summary(
                    graph_id=self.graph_id,
                    entity_name=entity_name
                )
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            elif tool_name == "get_simulation_context":
                # heavymusttowardsto insight_forge，becauseforitmorestrengthenLarge
                logger.info("get_simulation_context heavymusttowardsto insight_forge")
                query = parameters.get("query", self.simulation_requirement)
                return self._execute_tool("insight_forge", {"query": query}, report_context)
            
            elif tool_name == "get_entities_by_type":
                entity_type = parameters.get("entity_type", "")
                nodes = self.zep_tools.get_entities_by_type(
                    graph_id=self.graph_id,
                    entity_type=entity_type
                )
                result = [n.to_dict() for n in nodes]
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            else:
                return f"notknowtool: {tool_name}。pleaseusetoundertoolofone: insight_forge, panorama_search, quick_search"
                
        except Exception as e:
            logger.error(f"toolexecutefail: {tool_name}, Error: {str(e)}")
            return f"toolexecutefail: {str(e)}"
    
    # combinelawtoolNamecollectcombine，useat JSON bottomparsehourschooltest
    VALID_TOOL_NAMES = {"insight_forge", "panorama_search", "quick_search", "interview_agents", "query_world_state"}

    def _parse_tool_calls(self, response: str) -> List[Dict[str, Any]]:
        """
        fromLLMresponseMiddleparsetoolinvoke

        supportformat（excellentfirstlevel）：
        1. <tool_call>{"name": "tool_name", "parameters": {...}}</tool_call>
        2.  JSON（responsewholebodyorsinglegoareatoolinvoke JSON）
        """
        tool_calls = []

        # format1: XMLstyle（allowformat）
        xml_pattern = r'<tool_call>\s*(\{.*?\})\s*</tool_call>'
        for match in re.finditer(xml_pattern, response, re.DOTALL):
            try:
                call_data = json.loads(match.group(1))
                tool_calls.append(call_data)
            except json.JSONDecodeError:
                pass

        if tool_calls:
            return tool_calls

        # format2: bottom - LLM connectoutput JSON（nopackage <tool_call> ）
        # onlyatformat1notmatchhourtest，errormatchbodyMiddle JSON
        stripped = response.strip()
        if stripped.startswith('{') and stripped.endswith('}'):
            try:
                call_data = json.loads(stripped)
                if self._is_valid_tool_call(call_data):
                    tool_calls.append(call_data)
                    return tool_calls
            except json.JSONDecodeError:
                pass

        # responsecancancontainthinkingtext +  JSON，testextractLasta JSON object
        json_pattern = r'(\{"(?:name|tool)"\s*:.*?\})\s*$'
        match = re.search(json_pattern, stripped, re.DOTALL)
        if match:
            try:
                call_data = json.loads(match.group(1))
                if self._is_valid_tool_call(call_data):
                    tool_calls.append(call_data)
            except json.JSONDecodeError:
                pass

        return tool_calls

    def _is_valid_tool_call(self, data: dict) -> bool:
        """schooltestparseout JSON whetherarecombinelawtoolinvoke"""
        # support {"name": ..., "parameters": ...} sum {"tool": ..., "params": ...} twotypename
        tool_name = data.get("name") or data.get("tool")
        if tool_name and tool_name in self.VALID_TOOL_NAMES:
            # onenamefor name / parameters
            if "tool" in data:
                data["name"] = data.pop("tool")
            if "params" in data and "parameters" not in data:
                data["parameters"] = data.pop("params")
            return True
        return False
    
    def _get_tools_description(self) -> str:
        """GeneratetoolDescriptiontext"""
        desc_parts = ["availabletool："]
        for name, tool in self.tools.items():
            params_desc = ", ".join([f"{k}: {v}" for k, v in tool["parameters"].items()])
            desc_parts.append(f"- {name}: {tool['description']}")
            if params_desc:
                desc_parts.append(f"  Parameter: {params_desc}")
        return "\n".join(desc_parts)
    
    def plan_outline(
        self, 
        progress_callback: Optional[Callable] = None
    ) -> ReportOutline:
        """
        planreportLarge
        
        useLLManalyzesimulaterequirement，planreportDirectorystructure
        
        Args:
            progress_callback: enterdepthreturnFunction
            
        Returns:
            ReportOutline: reportLarge
        """
        logger.info("startplanreportLarge...")
        
        if progress_callback:
            progress_callback("planning", 0, "positiveatanalyzesimulaterequirement...")
        
        # firstGetsimulateUpunderdoc
        context = self.zep_tools.get_simulation_context(
            graph_id=self.graph_id,
            simulation_requirement=self.simulation_requirement
        )
        
        if progress_callback:
            progress_callback("planning", 30, "positiveatGeneratereportLarge...")
        
        system_prompt = PLAN_SYSTEM_PROMPT
        user_prompt = PLAN_USER_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            total_nodes=context.get('graph_statistics', {}).get('total_nodes', 0),
            total_edges=context.get('graph_statistics', {}).get('total_edges', 0),
            entity_types=list(context.get('graph_statistics', {}).get('entity_types', {}).keys()),
            total_entities=context.get('total_entities', 0),
            related_facts_json=json.dumps(context.get('related_facts', [])[:10], ensure_ascii=False, indent=2),
            world_state_summary=json.dumps(self.world_state.summary(), ensure_ascii=False, indent=2, default=str),
        )

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            if progress_callback:
                progress_callback("planning", 80, "positiveatparseLargestructure...")
            
            # parseLarge
            sections = []
            for section_data in response.get("sections", []):
                sections.append(ReportSection(
                    title=section_data.get("title", ""),
                    content=""
                ))
            
            outline = ReportOutline(
                title=self._english_only(response.get("title", "Simulation Analysis Report")),
                summary=self._english_only(response.get("summary", "")),
                sections=sections
            )
            for section in outline.sections:
                section.title = self._english_only(section.title)
            
            if progress_callback:
                progress_callback("planning", 100, "Largeplancomplete")
            
            logger.info(f"Largeplancomplete: {len(sections)} section")
            return outline
            
        except Exception as e:
            logger.error(f"Largeplanfail: {str(e)}")
            # ReturnDefaultLarge（3section，actforfallback）
            return ReportOutline(
                title="FuturePredictionreport",
                summary="based onsimulatePredictionFuturetrendandriskanalyze",
                sections=[
                    ReportSection(title="Predictionscenesceneandcorediscover"),
                    ReportSection(title="groupsbehaviorPredictionanalyze"),
                    ReportSection(title="trendandriskprompt")
                ]
            )
    
    def _generate_section_react(
        self, 
        section: ReportSection,
        outline: ReportOutline,
        previous_sections: List[str],
        progress_callback: Optional[Callable] = None,
        section_index: int = 0
    ) -> str:
        """
        useReACTmodeGeneratesinglesectioncontent
        
        ReACTring：
        1. Thought（thinking）- analyzeneedwantwhatinformation
        2. Action（action）- invoketoolGetinformation
        3. Observation（observe）- analyzetoolReturnresult
        4. heavyrepeattoinformationenoughableorarrivetomostLargenumber
        5. Final Answer（Finalreturnanswer）- Generatesectioncontent
        
        Args:
            section: wantGeneratesection
            outline: completeLarge
            previous_sections: ofBeforesectioncontent（useatkeepmaintainlink）
            progress_callback: enterdepthreturn
            section_index: sectionindex（useatlogRecord）
            
        Returns:
            sectioncontent（Markdownformat）
        """
        logger.info(f"ReACTGeneratesection: {section.title}")
        
        # Recordsectionstartlog
        if self.report_logger:
            self.report_logger.log_section_start(section.title, section_index)
        
        system_prompt = SECTION_SYSTEM_PROMPT_TEMPLATE.format(
            report_title=outline.title,
            report_summary=outline.summary,
            simulation_requirement=self.simulation_requirement,
            section_title=section.title,
            tools_description=self._get_tools_description(),
        )

        # builduserprompt - eachcompletesectioneachtransferinmostLarge4000word
        if previous_sections:
            previous_parts = []
            for sec in previous_sections:
                # eachsectionmostmany4000word
                truncated = sec[:4000] + "..." if len(sec) > 4000 else sec
                previous_parts.append(truncated)
            previous_content = "\n\n---\n\n".join(previous_parts)
        else:
            previous_content = "（thisareFirstsection）"
        
        user_prompt = SECTION_USER_PROMPT_TEMPLATE.format(
            previous_content=previous_content,
            section_title=section.title,
        )

        if self.stop_requested:
            raise RuntimeError("Report generation stopped by user")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # ReACTring
        tool_calls_count = 0
        max_iterations = 5  # mostLargegenroundnumber
        min_tool_calls = 3  # mostfewtoolinvokenumber
        conflict_retries = 0  # toolinvokeandFinal Answersimultaneouslyoutnowlinkcontinuesuddennumber
        used_tools = set()  # Recordinvokepasttoolname
        all_tools = {"insight_forge", "panorama_search", "quick_search", "interview_agents"}

        # reportUpunderdoc，useatInsightForgestudentquestionGenerate
        report_context = f"sectiontitle: {section.title}\nsimulaterequirement: {self.simulation_requirement}"
        
        for iteration in range(max_iterations):
            if progress_callback:
                progress_callback(
                    "generating", 
                    int((iteration / max_iterations) * 100),
                    f"depthretrieveandMiddle ({tool_calls_count}/{self.MAX_TOOL_CALLS_PER_SECTION})"
                )
            
            # invokeLLM
            # No max_tokens: report sections are long-form and a cap truncates them.
            response = self.llm.chat(
                messages=messages,
                temperature=0.5
            )

            # check LLM Returnwhetherfor None（API ExceptionorcontentforEmpty）
            if response is None:
                logger.warning(f"section {section.title} # {iteration + 1} gen: LLM Return None")
                # ifalsohavegennumber，addinfoandheavytest
                if iteration < max_iterations - 1:
                    messages.append({"role": "assistant", "content": "（responseforEmpty）"})
                    messages.append({"role": "user", "content": "pleasecontinueGeneratecontent。"})
                    continue
                # LastonegenalsoReturn None，jumpoutringenterinstrengthensystemaccept
                break

            logger.debug(f"LLMresponse: {response[:200]}...")

            # parseone，repeatuseresult
            tool_calls = self._parse_tool_calls(response)
            has_tool_calls = bool(tool_calls)
            has_final_answer = "Final Answer:" in response

            # ── suddenProcess：LLM simultaneouslyoutputtoolinvokesum Final Answer ──
            if has_tool_calls and has_final_answer:
                conflict_retries += 1
                logger.warning(
                    f"section {section.title} # {iteration+1} round: "
                    f"LLM simultaneouslyoutputtoolinvokesum Final Answer（# {conflict_retries} sudden）"
                )

                if conflict_retries <= 2:
                    # Beforetwo：discardabandonthisresponse，wantrequest LLM heavyNewreply
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": (
                            "【formatError】youatonereplyMiddlesimultaneouslycontaintoolinvokesum Final Answer，thisarenoallowpermit。\n"
                            "each timereplycan onlydotoundertwoitemmatterofone：\n"
                            "- invokeatool（outputa <tool_call> block，do not Final Answer）\n"
                            "- outputFinalcontent（to 'Final Answer:' openhead，do notcontain <tool_call>）\n"
                            "pleaseheavyNewreply，onlydoitsMiddleoneitemmatter。"
                        ),
                    })
                    continue
                else:
                    # Third：downgradelevelProcess，truncatetoFirsttoolinvoke，strengthensystemexecute
                    logger.warning(
                        f"section {section.title}: linkcontinue {conflict_retries} sudden，"
                        "downgradelevelfortruncateexecuteFirsttoolinvoke"
                    )
                    first_tool_end = response.find('</tool_call>')
                    if first_tool_end != -1:
                        response = response[:first_tool_end + len('</tool_call>')]
                        tool_calls = self._parse_tool_calls(response)
                        has_tool_calls = bool(tool_calls)
                    has_final_answer = False
                    conflict_retries = 0

            # Record LLM responselog
            if self.report_logger:
                self.report_logger.log_llm_response(
                    section_title=section.title,
                    section_index=section_index,
                    response=response,
                    iteration=iteration + 1,
                    has_tool_calls=has_tool_calls,
                    has_final_answer=has_final_answer
                )

            # ── situation1：LLM output Final Answer ──
            if has_final_answer:
                # toolinvokenumbernoenough，rejectandwantrequestcontinuetool
                if tool_calls_count < min_tool_calls:
                    messages.append({"role": "assistant", "content": response})
                    unused_tools = all_tools - used_tools
                    unused_hint = f"（thistoolalsonotuse，pushuseoneunderthey: {', '.join(unused_tools)}）" if unused_tools else ""
                    messages.append({
                        "role": "user",
                        "content": REACT_INSUFFICIENT_TOOLS_MSG.format(
                            tool_calls_count=tool_calls_count,
                            min_tool_calls=min_tool_calls,
                            unused_hint=unused_hint,
                        ),
                    })
                    continue

                # normalend
                final_answer = self._english_only(response.split("Final Answer:")[-1].strip())
                logger.info(f"section {section.title} Generatecomplete (tool calls: {tool_calls_count})")

                if self.report_logger:
                    self.report_logger.log_section_content(
                        section_title=section.title,
                        section_index=section_index,
                        content=final_answer,
                        tool_calls_count=tool_calls_count
                    )
                return final_answer

            # ── situation2：LLM testinvoketool ──
            if has_tool_calls:
                # tooldepthexhaust → explicittellknow，wantrequestoutput Final Answer
                if tool_calls_count >= self.MAX_TOOL_CALLS_PER_SECTION:
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": REACT_TOOL_LIMIT_MSG.format(
                            tool_calls_count=tool_calls_count,
                            max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                        ),
                    })
                    continue

                # onlyexecuteFirsttoolinvoke
                call = tool_calls[0]
                if len(tool_calls) > 1:
                    logger.info(f"LLM testinvoke {len(tool_calls)} tool，onlyexecuteFirst: {call['name']}")

                if self.report_logger:
                    self.report_logger.log_tool_call(
                        section_title=section.title,
                        section_index=section_index,
                        tool_name=call["name"],
                        parameters=call.get("parameters", {}),
                        iteration=iteration + 1
                    )

                result = self._execute_tool(
                    call["name"],
                    call.get("parameters", {}),
                    report_context=report_context
                )

                if self.report_logger:
                    self.report_logger.log_tool_result(
                        section_title=section.title,
                        section_index=section_index,
                        tool_name=call["name"],
                        result=result,
                        iteration=iteration + 1
                    )

                tool_calls_count += 1
                used_tools.add(call['name'])

                # buildnotusetoolprompt
                unused_tools = all_tools - used_tools
                unused_hint = ""
                if unused_tools and tool_calls_count < self.MAX_TOOL_CALLS_PER_SECTION:
                    unused_hint = REACT_UNUSED_TOOLS_HINT.format(unused_list="、".join(unused_tools))

                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": REACT_OBSERVATION_TEMPLATE.format(
                        tool_name=call["name"],
                        result=result,
                        tool_calls_count=tool_calls_count,
                        max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                        used_tools_str=", ".join(used_tools),
                        unused_hint=unused_hint,
                    ),
                })
                continue

            # ── situation3：sincenohavetoolinvoke，alsonohave Final Answer ──
            messages.append({"role": "assistant", "content": response})

            if tool_calls_count < min_tool_calls:
                # toolinvokenumbernoenough，pushnotusepasttool
                unused_tools = all_tools - used_tools
                unused_hint = f"（thistoolalsonotuse，pushuseoneunderthey: {', '.join(unused_tools)}）" if unused_tools else ""

                messages.append({
                    "role": "user",
                    "content": REACT_INSUFFICIENT_TOOLS_MSG_ALT.format(
                        tool_calls_count=tool_calls_count,
                        min_tool_calls=min_tool_calls,
                        unused_hint=unused_hint,
                    ),
                })
                continue

            # toolinvokeenoughable，LLM outputcontentbutnobelt "Final Answer:" Before
            # connectwillthissegmentcontentactforFinalanswer，noagainEmptyturn
            logger.info(f"section {section.title} notDetectto 'Final Answer:' Before，connectacceptLLMoutputactforFinalcontent（toolinvoke: {tool_calls_count}）")
            final_answer = self._english_only(response.strip())

            if self.report_logger:
                self.report_logger.log_section_content(
                    section_title=section.title,
                    section_index=section_index,
                    content=final_answer,
                    tool_calls_count=tool_calls_count
                )
            return final_answer
        
        # arrivetomostLargegennumber，strengthensystemGeneratecontent
        logger.warning(f"section {section.title} arrivetomostLargegennumber，strengthensystemGenerate")
        messages.append({"role": "user", "content": REACT_FORCE_FINAL_MSG})
        
        response = self.llm.chat(
            messages=messages,
            temperature=0.5
        )

        # checkstrengthensystemaccepthour LLM Returnwhetherfor None
        if response is None:
            logger.error(f"section {section.title} strengthensystemaccepthour LLM Return None，useDefaultErrorprompt")
            final_answer = f"（thissectionGeneratefail：LLM ReturnEmptyresponse，pleaseafter heavytest）"
        elif "Final Answer:" in response:
            final_answer = self._english_only(response.split("Final Answer:")[-1].strip())
        else:
            final_answer = self._english_only(response)
        
        # RecordsectioncontentGeneratecompletelog
        if self.report_logger:
            self.report_logger.log_section_content(
                section_title=section.title,
                section_index=section_index,
                content=final_answer,
                tool_calls_count=tool_calls_count
            )
        
        return final_answer
    
    @staticmethod
    def _english_only(text: str) -> str:
        """Reject non-English CJK output rather than exposing it in reports."""
        import re
        if not text:
            return text
        if re.search(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]', text):
            raise ValueError(
                "The model returned non-English characters. Report generation was "
                "stopped to prevent non-English output from entering the report."
            )
        return text

    def generate_report(
        self, 
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
        report_id: Optional[str] = None
    ) -> Report:
        """
        Generatecompletereport（minutesectionReal-timeoutput）
        
        eachsectionGeneratecompleteAfterinstantSavetoFilefolder，noneedwantwaitwholereportcomplete。
        Filestructure：
        reports/{report_id}/
            meta.json       - reportmetainformation
            outline.json    - reportLarge
            progress.json   - Generateenterdepth
            section_01.md   - #1section
            section_02.md   - #2section
            ...
            full_report.md  - completereport
        
        Args:
            progress_callback: enterdepthreturnFunction (stage, progress, message)
            report_id: reportID（Optional，ifnotransferthenautoGenerate）
            
        Returns:
            Report: completereport
        """
        import uuid
        
        # ifnohavetransferin report_id，thenautoGenerate
        if not report_id:
            report_id = f"report_{uuid.uuid4().hex[:12]}"
        start_time = datetime.now()
        
        report = Report(
            report_id=report_id,
            simulation_id=self.simulation_id,
            graph_id=self.graph_id,
            simulation_requirement=self.simulation_requirement,
            status=ReportStatus.PENDING,
            created_at=datetime.now().isoformat()
        )
        
        # completesectiontitlelist（useatenterdepth）
        completed_section_titles = []
        
        try:
            # Initialize：createreportFilefolderandSaveInitialStatus
            ReportManager._ensure_report_folder(report_id)
            
            # InitializelogRecorder（structurechemlog agent_log.jsonl）
            self.report_logger = ReportLogger(report_id)
            self.report_logger.log_start(
                simulation_id=self.simulation_id,
                graph_id=self.graph_id,
                simulation_requirement=self.simulation_requirement
            )
            
            # InitializecontrollogRecorder（console_log.txt）
            self.console_logger = ReportConsoleLogger(report_id)
            
            ReportManager.update_progress(
                report_id, "pending", 0, "Initializereport...",
                completed_sections=[]
            )
            ReportManager.save_report(report)
            
            # stage1: planLarge
            report.status = ReportStatus.PLANNING
            ReportManager.update_progress(
                report_id, "planning", 5, "startplanreportLarge...",
                completed_sections=[]
            )
            
            # Recordplanstartlog
            self.report_logger.log_planning_start()
            
            if progress_callback:
                progress_callback("planning", 0, "startplanreportLarge...")
            
            outline = self.plan_outline(
                progress_callback=lambda stage, prog, msg: 
                    progress_callback(stage, prog // 5, msg) if progress_callback else None
            )
            report.outline = outline
            
            # Recordplancompletelog
            self.report_logger.log_planning_complete(outline.to_dict())
            
            # SaveLargetoFile
            ReportManager.save_outline(report_id, outline)
            ReportManager.update_progress(
                report_id, "planning", 15, f"Largeplancomplete，{len(outline.sections)}section",
                completed_sections=[]
            )
            ReportManager.save_report(report)
            
            logger.info(f"LargeSavetoFile: {report_id}/outline.json")
            
            # stage2: sectionGenerate（minutesectionSave）
            report.status = ReportStatus.GENERATING
            
            total_sections = len(outline.sections)
            generated_sections = []  # SavecontentuseatUpunderdoc
            
            for i, section in enumerate(outline.sections):
                if self.stop_requested:
                    raise RuntimeError("Report generation stopped by user")
                section_num = i + 1
                base_progress = 20 + int((i / total_sections) * 70)
                
                # moreNewenterdepth
                ReportManager.update_progress(
                    report_id, "generating", base_progress,
                    f"positiveatGeneratesection: {section.title} ({section_num}/{total_sections})",
                    current_section=section.title,
                    completed_sections=completed_section_titles
                )
                
                if progress_callback:
                    progress_callback(
                        "generating", 
                        base_progress, 
                        f"positiveatGeneratesection: {section.title} ({section_num}/{total_sections})"
                    )
                
                # Generatemainsectioncontent
                section_content = self._generate_section_react(
                    section=section,
                    outline=outline,
                    previous_sections=generated_sections,
                    progress_callback=lambda stage, prog, msg:
                        progress_callback(
                            stage, 
                            base_progress + int(prog * 0.7 / total_sections),
                            msg
                        ) if progress_callback else None,
                    section_index=section_num
                )
                
                section.content = section_content
                generated_sections.append(f"## {section.title}\n\n{section_content}")

                # Savesection
                ReportManager.save_section(report_id, section_num, section)
                completed_section_titles.append(section.title)

                # Recordsectioncompletelog
                full_section_content = f"## {section.title}\n\n{section_content}"

                if self.report_logger:
                    self.report_logger.log_section_full_complete(
                        section_title=section.title,
                        section_index=section_num,
                        full_content=full_section_content.strip()
                    )

                logger.info(f"sectionSave: {report_id}/section_{section_num:02d}.md")
                
                # moreNewenterdepth
                ReportManager.update_progress(
                    report_id, "generating", 
                    base_progress + int(70 / total_sections),
                    f"section {section.title} complete",
                    current_section=None,
                    completed_sections=completed_section_titles
                )
            
            # stage3: groupinstallcompletereport
            if progress_callback:
                progress_callback("generating", 95, "positiveatgroupinstallcompletereport...")
            
            ReportManager.update_progress(
                report_id, "generating", 95, "positiveatgroupinstallcompletereport...",
                completed_sections=completed_section_titles
            )
            
            # useReportManagergroupinstallcompletereport
            report.markdown_content = ReportManager.assemble_full_report(report_id, outline)
            report.status = ReportStatus.COMPLETED
            report.completed_at = datetime.now().isoformat()
            
            # calculatehour
            total_time_seconds = (datetime.now() - start_time).total_seconds()
            
            # Recordreportcompletelog
            if self.report_logger:
                self.report_logger.log_report_complete(
                    total_sections=total_sections,
                    total_time_seconds=total_time_seconds
                )
            
            # SaveFinalreport
            ReportManager.save_report(report)
            ReportManager.update_progress(
                report_id, "completed", 100, "Report Generationcomplete",
                completed_sections=completed_section_titles
            )
            
            if progress_callback:
                progress_callback("completed", 100, "Report Generationcomplete")
            
            logger.info(f"Report Generationcomplete: {report_id}")
            
            # ClosecontrollogRecorder
            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None
            
            return report
            
        except Exception as e:
            logger.error(f"Report Generationfail: {str(e)}")
            report.status = ReportStatus.FAILED
            report.error = str(e)
            
            # RecordErrorlog
            if self.report_logger:
                self.report_logger.log_error(str(e), "failed")
            
            # SavefailStatus
            try:
                ReportManager.save_report(report)
                ReportManager.update_progress(
                    report_id, "failed", -1, f"Report Generationfail: {str(e)}",
                    completed_sections=completed_section_titles
                )
            except Exception:
                pass  # suddenlySavefailError
            
            # ClosecontrollogRecorder
            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None
            
            return report
    
    def chat(
        self, 
        message: str,
        chat_history: List[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        andReport Agenttowardchat
        
        attowardchatMiddleAgentcantoautonomousinvokeretrievetoolfuturereturnanswerquestion
        
        Args:
            message: userinfo
            chat_history: towardchathistorical
            
        Returns:
            {
                "response": "Agentreply",
                "tool_calls": [invoketoollist],
                "sources": [informationfuture]
            }
        """
        logger.info(f"Report Agenttowardchat: {message[:50]}...")
        
        chat_history = chat_history or []
        
        # GetGeneratereportcontent
        report_content = ""
        try:
            report = ReportManager.get_report_by_simulation(self.simulation_id)
            if report and report.markdown_content:
                # limitreportLongdepth，UpunderdocpastLong
                report_content = report.markdown_content[:15000]
                if len(report.markdown_content) > 15000:
                    report_content += "\n\n... [reportcontenttruncate] ..."
        except Exception as e:
            logger.warning(f"Getreportcontentfail: {e}")
        
        system_prompt = CHAT_SYSTEM_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            report_content=report_content if report_content else "（nonereport）",
            tools_description=self._get_tools_description(),
        )

        # buildinfo
        messages = [{"role": "system", "content": system_prompt}]
        
        # addhistoricaltowardchat
        for h in chat_history[-10:]:  # limithistoricalLongdepth
            messages.append(h)
        
        # adduserinfo
        messages.append({
            "role": "user", 
            "content": message
        })
        
        # ReACTring（chemversion）
        tool_calls_made = []
        max_iterations = 2  # decreasefewgenroundnumber
        
        for iteration in range(max_iterations):
            response = self.llm.chat(
                messages=messages,
                temperature=0.5
            )
            
            # parsetoolinvoke
            tool_calls = self._parse_tool_calls(response)
            
            if not tool_calls:
                # nohavetoolinvoke，connectReturnresponse
                clean_response = re.sub(r'<tool_call>.*?</tool_call>', '', response, flags=re.DOTALL)
                clean_response = re.sub(r'\[TOOL_CALL\].*?\)', '', clean_response)
                
                return {
                    "response": clean_response.strip(),
                    "tool_calls": tool_calls_made,
                    "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made]
                }
            
            # executetoolinvoke（limitnumbermeasure）
            tool_results = []
            for call in tool_calls[:1]:  # eachroundmostmanyexecute1toolinvoke
                if len(tool_calls_made) >= self.MAX_TOOL_CALLS_PER_CHAT:
                    break
                result = self._execute_tool(call["name"], call.get("parameters", {}))
                tool_results.append({
                    "tool": call["name"],
                    "result": result[:1500]  # limitresultLongdepth
                })
                tool_calls_made.append(call)
            
            # willresultaddtoinfo
            messages.append({"role": "assistant", "content": response})
            observation = "\n".join([f"[{r['tool']}result]\n{r['result']}" for r in tool_results])
            messages.append({
                "role": "user",
                "content": observation + CHAT_OBSERVATION_SUFFIX
            })
        
        # arrivetomostLargegen，GetFinalresponse
        final_response = self.llm.chat(
            messages=messages,
            temperature=0.5
        )
        
        # Cleanupresponse
        clean_response = re.sub(r'<tool_call>.*?</tool_call>', '', final_response, flags=re.DOTALL)
        clean_response = re.sub(r'\[TOOL_CALL\].*?\)', '', clean_response)
        
        return {
            "response": clean_response.strip(),
            "tool_calls": tool_calls_made,
            "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made]
        }


class ReportManager:
    """
    reportmanageer
    
    negativereportmaintainlong-timechemstorestoragesumretrieve
    
    Filestructure（minutesectionoutput）：
    reports/
      {report_id}/
        meta.json          - reportmetainformationsumStatus
        outline.json       - reportLarge
        progress.json      - Generateenterdepth
        section_01.md      - #1section
        section_02.md      - #2section
        ...
        full_report.md     - completereport
    """
    
    # reportstorestorageDirectory
    REPORTS_DIR = os.path.join(Config.UPLOAD_FOLDER, 'reports')
    
    @classmethod
    def _ensure_reports_dir(cls):
        """keepreportrootDirectory exists"""
        os.makedirs(cls.REPORTS_DIR, exist_ok=True)
    
    @classmethod
    def _get_report_folder(cls, report_id: str) -> str:
        """GetreportFilefolderPath"""
        return os.path.join(cls.REPORTS_DIR, report_id)
    
    @classmethod
    def _ensure_report_folder(cls, report_id: str) -> str:
        """keepreportFilefolderExistandReturnPath"""
        folder = cls._get_report_folder(report_id)
        os.makedirs(folder, exist_ok=True)
        return folder
    
    @classmethod
    def _get_report_path(cls, report_id: str) -> str:
        """GetreportmetainformationFilePath"""
        return os.path.join(cls._get_report_folder(report_id), "meta.json")
    
    @classmethod
    def _get_report_markdown_path(cls, report_id: str) -> str:
        """GetcompletereportMarkdownFilePath"""
        return os.path.join(cls._get_report_folder(report_id), "full_report.md")
    
    @classmethod
    def _get_outline_path(cls, report_id: str) -> str:
        """GetLargeFilePath"""
        return os.path.join(cls._get_report_folder(report_id), "outline.json")
    
    @classmethod
    def _get_progress_path(cls, report_id: str) -> str:
        """GetenterdepthFilePath"""
        return os.path.join(cls._get_report_folder(report_id), "progress.json")
    
    @classmethod
    def _get_section_path(cls, report_id: str, section_index: int) -> str:
        """GetsectionMarkdownFilePath"""
        return os.path.join(cls._get_report_folder(report_id), f"section_{section_index:02d}.md")
    
    @classmethod
    def _get_agent_log_path(cls, report_id: str) -> str:
        """Get Agent logFilePath"""
        return os.path.join(cls._get_report_folder(report_id), "agent_log.jsonl")
    
    @classmethod
    def _get_console_log_path(cls, report_id: str) -> str:
        """GetcontrollogFilePath"""
        return os.path.join(cls._get_report_folder(report_id), "console_log.txt")
    
    @classmethod
    def get_console_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        """
        Getcontrollogcontent
        
        thisareReport GenerationprocessMiddlecontroloutputlog（INFO、WARNINGetc），
        and agent_log.jsonl structurechemlogdifferent。
        
        Args:
            report_id: reportID
            from_line: from#severalgostartRead（useatincreasemeasureGet，0 tablefromheadstart）
            
        Returns:
            {
                "logs": [loggolist],
                "total_lines": gonumber,
                "from_line": upbegingo,
                "has_more": whetheralsohavemoremanylog
            }
        """
        log_path = cls._get_console_log_path(report_id)
        
        if not os.path.exists(log_path):
            return {
                "logs": [],
                "total_lines": 0,
                "from_line": 0,
                "has_more": False
            }
        
        logs = []
        total_lines = 0
        
        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= from_line:
                    # keepkeeporiginalbeginloggo，godropswapgo
                    logs.append(line.rstrip('\n\r'))
        
        return {
            "logs": logs,
            "total_lines": total_lines,
            "from_line": from_line,
            "has_more": False  # Readto
        }
    
    @classmethod
    def get_console_log_stream(cls, report_id: str) -> List[str]:
        """
        Getcompletecontrollog（oneGetall）
        
        Args:
            report_id: reportID
            
        Returns:
            loggolist
        """
        result = cls.get_console_log(report_id, from_line=0)
        return result["logs"]
    
    @classmethod
    def get_agent_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        """
        Get Agent logcontent
        
        Args:
            report_id: reportID
            from_line: from#severalgostartRead（useatincreasemeasureGet，0 tablefromheadstart）
            
        Returns:
            {
                "logs": [logedgeitemlist],
                "total_lines": gonumber,
                "from_line": upbegingo,
                "has_more": whetheralsohavemoremanylog
            }
        """
        log_path = cls._get_agent_log_path(report_id)
        
        if not os.path.exists(log_path):
            return {
                "logs": [],
                "total_lines": 0,
                "from_line": 0,
                "has_more": False
            }
        
        logs = []
        total_lines = 0
        
        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= from_line:
                    try:
                        log_entry = json.loads(line.strip())
                        logs.append(log_entry)
                    except json.JSONDecodeError:
                        # jumppastparsefailgo
                        continue
        
        return {
            "logs": logs,
            "total_lines": total_lines,
            "from_line": from_line,
            "has_more": False  # Readto
        }
    
    @classmethod
    def get_agent_log_stream(cls, report_id: str) -> List[Dict[str, Any]]:
        """
        Getcomplete Agent log（useatoneGetall）
        
        Args:
            report_id: reportID
            
        Returns:
            logedgeitemlist
        """
        result = cls.get_agent_log(report_id, from_line=0)
        return result["logs"]
    
    @classmethod
    def save_outline(cls, report_id: str, outline: ReportOutline) -> None:
        """
        SavereportLarge
        
        atplanstagecompleteAfterinstantinvoke
        """
        cls._ensure_report_folder(report_id)
        
        with open(cls._get_outline_path(report_id), 'w', encoding='utf-8') as f:
            json.dump(outline.to_dict(), f, ensure_ascii=False, indent=2)
        
        logger.info(f"LargeSave: {report_id}")
    
    @classmethod
    def save_section(
        cls,
        report_id: str,
        section_index: int,
        section: ReportSection
    ) -> str:
        """
        Savesinglesection

        ateachsectionGeneratecompleteAfterinstantinvoke，implementminutesectionoutput

        Args:
            report_id: reportID
            section_index: sectionindex（from1start）
            section: sectionobject

        Returns:
            SaveFilePath
        """
        cls._ensure_report_folder(report_id)

        # buildsectionMarkdowncontent - CleanupcancanExistheavyrepeattitle
        cleaned_content = cls._clean_section_content(section.content, section.title)
        md_content = f"## {section.title}\n\n"
        if cleaned_content:
            md_content += f"{cleaned_content}\n\n"

        # SaveFile
        file_suffix = f"section_{section_index:02d}.md"
        file_path = os.path.join(cls._get_report_folder(report_id), file_suffix)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        logger.info(f"sectionSave: {report_id}/{file_suffix}")
        return file_path
    
    @classmethod
    def _clean_section_content(cls, content: str, section_title: str) -> str:
        """
        Cleanupsectioncontent
        
        1. removecontentopenheadandsectiontitleheavyrepeatMarkdowntitlego
        2. willhas ### plustounderranktitleturnswapforcoarsebodytext
        
        Args:
            content: originalbegincontent
            section_title: sectiontitle
            
        Returns:
            CleanupAftercontent
        """
        import re
        
        if not content:
            return content
        
        content = content.strip()
        lines = content.split('\n')
        cleaned_lines = []
        skip_next_empty = False
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # checkwhetherareMarkdowntitlego
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
            
            if heading_match:
                level = len(heading_match.group(1))
                title_text = heading_match.group(2).strip()
                
                # checkwhetherareandsectiontitleheavyrepeattitle（jumppastBefore5goInternalheavyrepeat）
                if i < 5:
                    if title_text == section_title or title_text.replace(' ', '') == section_title.replace(' ', ''):
                        skip_next_empty = True
                        continue
                
                # willhasranktitle（#, ##, ###, ####etc）turnswapforcoarsebody
                # becauseforsectiontitlebySystemadd，contentMiddlenoshouldhaveanywhattitle
                cleaned_lines.append(f"**{title_text}**")
                cleaned_lines.append("")  # addEmptygo
                continue
            
            # ifUponegoarebyjumppasttitle，pluscurrentbehaviorEmpty，alsojumppast
            if skip_next_empty and stripped == '':
                skip_next_empty = False
                continue
            
            skip_next_empty = False
            cleaned_lines.append(line)
        
        # removeopenheadEmptygo
        while cleaned_lines and cleaned_lines[0].strip() == '':
            cleaned_lines.pop(0)
        
        # removeopenheadminutethread
        while cleaned_lines and cleaned_lines[0].strip() in ['---', '***', '___']:
            cleaned_lines.pop(0)
            # simultaneouslyremoveminutethreadAfterEmptygo
            while cleaned_lines and cleaned_lines[0].strip() == '':
                cleaned_lines.pop(0)
        
        return '\n'.join(cleaned_lines)
    
    @classmethod
    def update_progress(
        cls, 
        report_id: str, 
        status: str, 
        progress: int, 
        message: str,
        current_section: str = None,
        completed_sections: List[str] = None
    ) -> None:
        """
        moreNewReport Generationenterdepth
        
        BeforeendcantoviaReadprogress.jsonGetReal-timeenterdepth
        """
        cls._ensure_report_folder(report_id)
        
        progress_data = {
            "status": status,
            "progress": progress,
            "message": message,
            "current_section": current_section,
            "completed_sections": completed_sections or [],
            "updated_at": datetime.now().isoformat()
        }
        
        with open(cls._get_progress_path(report_id), 'w', encoding='utf-8') as f:
            json.dump(progress_data, f, ensure_ascii=False, indent=2)
    
    @classmethod
    def get_progress(cls, report_id: str) -> Optional[Dict[str, Any]]:
        """GetReport Generationenterdepth"""
        path = cls._get_progress_path(report_id)
        
        if not os.path.exists(path):
            return None
        
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    @classmethod
    def get_generated_sections(cls, report_id: str) -> List[Dict[str, Any]]:
        """
        GetGeneratesectionlist
        
        ReturnhasSavesectionFileinformation
        """
        folder = cls._get_report_folder(report_id)
        
        if not os.path.exists(folder):
            return []
        
        sections = []
        for filename in sorted(os.listdir(folder)):
            if filename.startswith('section_') and filename.endswith('.md'):
                file_path = os.path.join(folder, filename)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # fromFilenameparsesectionindex
                parts = filename.replace('.md', '').split('_')
                section_index = int(parts[1])

                sections.append({
                    "filename": filename,
                    "section_index": section_index,
                    "content": content
                })

        return sections
    
    @classmethod
    def assemble_full_report(cls, report_id: str, outline: ReportOutline) -> str:
        """
        groupinstallcompletereport
        
        fromSavesectionFilegroupinstallcompletereport，andentergotitleCleanup
        """
        folder = cls._get_report_folder(report_id)
        
        # buildreportheaddept
        md_content = f"# {outline.title}\n\n"
        md_content += f"> {outline.summary}\n\n"
        md_content += f"---\n\n"
        
        # orderReadhassectionFile
        sections = cls.get_generated_sections(report_id)
        for section_info in sections:
            md_content += section_info["content"]
        
        # AfterProcess：Cleanupwholereporttitlequestion
        md_content = cls._post_process_report(md_content, outline)
        
        # Savecompletereport
        full_path = cls._get_report_markdown_path(report_id)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        logger.info(f"completereportgroupinstall: {report_id}")
        return md_content
    
    @classmethod
    def _post_process_report(cls, content: str, outline: ReportOutline) -> str:
        """
        AfterProcessreportcontent
        
        1. removeheavyrepeattitle
        2. keepkeepreportmaintitle(#)sumsectiontitle(##)，removeitsheranktitle(###, ####etc)
        3. CleanupmanyremainderEmptygosumminutethread
        
        Args:
            content: originalbeginreportcontent
            outline: reportLarge
            
        Returns:
            ProcessAftercontent
        """
        import re
        
        lines = content.split('\n')
        processed_lines = []
        prev_was_heading = False
        
        # acceptcollectLargeMiddlehassectiontitle
        section_titles = set()
        for section in outline.sections:
            section_titles.add(section.title)
        
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            
            # checkwhetheraretitlego
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
            
            if heading_match:
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                
                # checkwhetherareheavyrepeattitle（atlinkcontinue5goInternaloutnowsamecontenttitle）
                is_duplicate = False
                for j in range(max(0, len(processed_lines) - 5), len(processed_lines)):
                    prev_line = processed_lines[j].strip()
                    prev_match = re.match(r'^(#{1,6})\s+(.+)$', prev_line)
                    if prev_match:
                        prev_title = prev_match.group(2).strip()
                        if prev_title == title:
                            is_duplicate = True
                            break
                
                if is_duplicate:
                    # jumppastheavyrepeattitleplusitsAfterEmptygo
                    i += 1
                    while i < len(lines) and lines[i].strip() == '':
                        i += 1
                    continue
                
                # titlelevelProcess：
                # - # (level=1) onlykeepkeepreportmaintitle
                # - ## (level=2) keepkeepsectiontitle
                # - ### plustounder (level>=3) turnswapforcoarsebodytext
                
                if level == 1:
                    if title == outline.title:
                        # keepkeepreportmaintitle
                        processed_lines.append(line)
                        prev_was_heading = True
                    elif title in section_titles:
                        # sectiontitleErroruse#，fixpositivefor##
                        processed_lines.append(f"## {title}")
                        prev_was_heading = True
                    else:
                        # itsheoneleveltitleturnforcoarsebody
                        processed_lines.append(f"**{title}**")
                        processed_lines.append("")
                        prev_was_heading = False
                elif level == 2:
                    if title in section_titles or title == outline.title:
                        # keepkeepsectiontitle
                        processed_lines.append(line)
                        prev_was_heading = True
                    else:
                        # notsectionleveltitleturnforcoarsebody
                        processed_lines.append(f"**{title}**")
                        processed_lines.append("")
                        prev_was_heading = False
                else:
                    # ### plustounderranktitleturnswapforcoarsebodytext
                    processed_lines.append(f"**{title}**")
                    processed_lines.append("")
                    prev_was_heading = False
                
                i += 1
                continue
            
            elif stripped == '---' and prev_was_heading:
                # jumppasttitleAftertightminutethread
                i += 1
                continue
            
            elif stripped == '' and prev_was_heading:
                # titleAfteronlykeepkeepaEmptygo
                if processed_lines and processed_lines[-1].strip() != '':
                    processed_lines.append(line)
                prev_was_heading = False
            
            else:
                processed_lines.append(line)
                prev_was_heading = False
            
            i += 1
        
        # CleanuplinkcontinuemanyEmptygo（keepkeepmostmany2）
        result_lines = []
        empty_count = 0
        for line in processed_lines:
            if line.strip() == '':
                empty_count += 1
                if empty_count <= 2:
                    result_lines.append(line)
            else:
                empty_count = 0
                result_lines.append(line)
        
        return '\n'.join(result_lines)
    
    @classmethod
    def save_report(cls, report: Report) -> None:
        """Savereportmetainformationsumcompletereport"""
        cls._ensure_report_folder(report.report_id)
        
        # SavemetainformationJSON
        with open(cls._get_report_path(report.report_id), 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        
        # SaveLarge
        if report.outline:
            cls.save_outline(report.report_id, report.outline)
        
        # SavecompleteMarkdownreport
        if report.markdown_content:
            with open(cls._get_report_markdown_path(report.report_id), 'w', encoding='utf-8') as f:
                f.write(report.markdown_content)
        
        logger.info(f"reportSave: {report.report_id}")
    
    @classmethod
    def get_report(cls, report_id: str) -> Optional[Report]:
        """Getreport"""
        path = cls._get_report_path(report_id)
        
        if not os.path.exists(path):
            # compatibleOldformat：checkconnectstorestorageatreportsDirectoryunderFile
            old_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.json")
            if os.path.exists(old_path):
                path = old_path
            else:
                return None
        
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # heavyReportobject
        outline = None
        if data.get('outline'):
            outline_data = data['outline']
            sections = []
            for s in outline_data.get('sections', []):
                sections.append(ReportSection(
                    title=s['title'],
                    content=s.get('content', '')
                ))
            outline = ReportOutline(
                title=outline_data['title'],
                summary=outline_data['summary'],
                sections=sections
            )
        
        # ifmarkdown_contentforEmpty，testfromfull_report.mdRead
        markdown_content = data.get('markdown_content', '')
        if not markdown_content:
            full_report_path = cls._get_report_markdown_path(report_id)
            if os.path.exists(full_report_path):
                with open(full_report_path, 'r', encoding='utf-8') as f:
                    markdown_content = f.read()
        
        return Report(
            report_id=data['report_id'],
            simulation_id=data['simulation_id'],
            graph_id=data['graph_id'],
            simulation_requirement=data['simulation_requirement'],
            status=ReportStatus(data['status']),
            outline=outline,
            markdown_content=markdown_content,
            created_at=data.get('created_at', ''),
            completed_at=data.get('completed_at', ''),
            error=data.get('error')
        )
    
    @classmethod
    def get_report_by_simulation(cls, simulation_id: str) -> Optional[Report]:
        """according tosimulateIDGetreport"""
        cls._ensure_reports_dir()
        
        for item in os.listdir(cls.REPORTS_DIR):
            item_path = os.path.join(cls.REPORTS_DIR, item)
            # Newformat：Filefolder
            if os.path.isdir(item_path):
                report = cls.get_report(item)
                if report and report.simulation_id == simulation_id:
                    return report
            # compatibleOldformat：JSONFile
            elif item.endswith('.json'):
                report_id = item[:-5]
                report = cls.get_report(report_id)
                if report and report.simulation_id == simulation_id:
                    return report
        
        return None
    
    @classmethod
    def list_reports(cls, simulation_id: Optional[str] = None, limit: int = 50) -> List[Report]:
        """columnoutreport"""
        cls._ensure_reports_dir()
        
        reports = []
        for item in os.listdir(cls.REPORTS_DIR):
            item_path = os.path.join(cls.REPORTS_DIR, item)
            # Newformat：Filefolder
            if os.path.isdir(item_path):
                report = cls.get_report(item)
                if report:
                    if simulation_id is None or report.simulation_id == simulation_id:
                        reports.append(report)
            # compatibleOldformat：JSONFile
            elif item.endswith('.json'):
                report_id = item[:-5]
                report = cls.get_report(report_id)
                if report:
                    if simulation_id is None or report.simulation_id == simulation_id:
                        reports.append(report)
        
        # createTimereverseorder
        reports.sort(key=lambda r: r.created_at, reverse=True)
        
        return reports[:limit]
    
    @classmethod
    def delete_report(cls, report_id: str) -> bool:
        """deletereport（wholeFilefolder）"""
        import shutil
        
        folder_path = cls._get_report_folder(report_id)
        
        # Newformat：deletewholeFilefolder
        if os.path.exists(folder_path) and os.path.isdir(folder_path):
            shutil.rmtree(folder_path)
            logger.info(f"reportFilefolderdelete: {report_id}")
            return True
        
        # compatibleOldformat：deletealoneFile
        deleted = False
        old_json_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.json")
        old_md_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.md")
        
        if os.path.exists(old_json_path):
            os.remove(old_json_path)
            deleted = True
        if os.path.exists(old_md_path):
            os.remove(old_md_path)
            deleted = True
        
        return deleted
