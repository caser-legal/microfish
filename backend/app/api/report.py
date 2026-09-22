"""
Report API routes
Simulation report generation, retrieval, chat with the agent, and other endpoints
"""

import os
import traceback
import threading
from flask import request, jsonify, send_file

from . import report_bp
from ..config import Config
from ..services.report_agent import ReportAgent, ReportManager, ReportStatus
from ..services.simulation_manager import SimulationManager
from ..models.project import ProjectManager
from ..models.task import TaskManager, TaskStatus
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.report')

_report_agents = {}
_report_threads = {}


# ============== Report Generationconnectperson ==============

@report_bp.route('/generate', methods=['POST'])
def generate_report():
    """
    Generate a simulation analysis report (asynchronous task)
    
    This operation starts an asynchronous task. The endpoint immediately returns a task_id,
    which can be queried via GET /api/report/generate/status for progress.
    
    Request (JSON):
        {
            "simulation_id": "sim_xxxx",    // Required, simulation ID
            "force_regenerate": false        // Optional, force regeneration
        }
    
    Returns:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "task_id": "task_xxxx",
                "status": "generating",
                "message": "Report generation task started"
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Please provide simulation_id"
            }), 400
        
        force_regenerate = data.get('force_regenerate', False)
        
        # Get simulation information
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        
        if not state:
            return jsonify({
                "success": False,
                "error": f"Simulation does not exist: {simulation_id}"
            }), 404
        
        # Never start a duplicate request while one is already running.
        active = _report_agents.get(simulation_id)
        if active and not active.stop_requested:
            return jsonify({
                "success": True,
                "data": {"simulation_id": simulation_id, "report_id": getattr(active, "report_id", None),
                         "status": "generating", "message": "Report is already running",
                         "already_running": True}
            })

        # Check whether a report already exists
        if not force_regenerate:
            existing_report = ReportManager.get_report_by_simulation(simulation_id)
            if existing_report and existing_report.status == ReportStatus.COMPLETED:
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "report_id": existing_report.report_id,
                        "status": "completed",
                        "message": "reportExist",
                        "already_generated": True
                    }
                })
        
        # Get project information
        project = ProjectManager.get_project(state.project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": f"Project does not exist: {state.project_id}"
            }), 404
        
        graph_id = state.graph_id or project.graph_id
        if not graph_id:
            return jsonify({
                "success": False,
                "error": "Missing graph ID, please build the graph first"
            }), 400
        
        simulation_requirement = project.simulation_requirement
        if not simulation_requirement:
            return jsonify({
                "success": False,
                "error": "Missing simulation requirement description"
            }), 400
        
        # Pre-generate a report_id so it can be returned to the frontend immediately
        import uuid
        report_id = f"report_{uuid.uuid4().hex[:12]}"
        
        # Create an asynchronous task
        task_manager = TaskManager()
        task_id = task_manager.create_task(
            task_type="report_generate",
            metadata={
                "simulation_id": simulation_id,
                "graph_id": graph_id,
                "report_id": report_id
            }
        )
        
        # Define the task logic
        def run_generate():
            try:
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.PROCESSING,
                    progress=0,
                    message="Initializing Report Agent..."
                )
                
                # createReport Agent
                agent = ReportAgent(
                    graph_id=graph_id,
                    simulation_id=simulation_id,
                    simulation_requirement=simulation_requirement
                )
                agent.report_id = report_id
                _report_agents[simulation_id] = agent
                
                # enterdepthreturn
                def progress_callback(stage, progress, message):
                    task_manager.update_task(
                        task_id,
                        progress=progress,
                        message=f"[{stage}] {message}"
                    )
                
                # Generatereport（transferinprefirstGenerate report_id）
                report = agent.generate_report(
                    progress_callback=progress_callback,
                    report_id=report_id
                )
                
                # Savereport
                ReportManager.save_report(report)
                
                if report.status == ReportStatus.COMPLETED:
                    task_manager.complete_task(
                        task_id,
                        result={
                            "report_id": report.report_id,
                            "simulation_id": simulation_id,
                            "status": "completed"
                        }
                    )
                else:
                    task_manager.fail_task(task_id, report.error or "Report Generationfail")
                
            except Exception as e:
                logger.error(f"Report Generation failed: {str(e)}")
                task_manager.fail_task(task_id, str(e))
            finally:
                _report_agents.pop(simulation_id, None)
                _report_threads.pop(simulation_id, None)
        
        # launchAfterthreadprogram
        thread = threading.Thread(target=run_generate, daemon=True)
        _report_threads[simulation_id] = thread
        thread.start()
        
        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "report_id": report_id,
                "task_id": task_id,
                "status": "generating",
                "message": "Report Generationtasklaunch，pleasevia /api/report/generate/status queryenterdepth",
                "already_generated": False
            }
        })
        
    except Exception as e:
        logger.error(f"launchReport Generationtaskfail: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/stop', methods=['POST'])
def stop_report(report_id: str):
    """Request cooperative cancellation of a running report."""
    for simulation_id, agent in list(_report_agents.items()):
        if getattr(agent, 'report_id', None) == report_id:
            agent.stop_requested = True
            return jsonify({"success": True, "data": {"report_id": report_id, "status": "stopping"}})
    return jsonify({"success": False, "error": "Report is not currently running"}), 404


@report_bp.route('/generate/status', methods=['POST'])
def get_generate_status():
    """
    Query the status of a report generation task
    
    Request (JSON):
        {
            "task_id": "task_xxxx",         // Optional, the task_id returned by generate
            "simulation_id": "sim_xxxx"     // Optional, simulation ID
        }
    
    Returns:
        {
            "success": true,
            "data": {
                "task_id": "task_xxxx",
                "status": "processing|completed|failed",
                "progress": 45,
                "message": "..."
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        task_id = data.get('task_id')
        simulation_id = data.get('simulation_id')
        
        # ifsimulation_id，firstcheckwhetherhavecompletereport
        if simulation_id:
            existing_report = ReportManager.get_report_by_simulation(simulation_id)
            if existing_report and existing_report.status == ReportStatus.COMPLETED:
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "report_id": existing_report.report_id,
                        "status": "completed",
                        "progress": 100,
                        "message": "reportGenerate",
                        "already_completed": True
                    }
                })
        
        if not task_id:
            return jsonify({
                "success": False,
                "error": "please task_id or simulation_id"
            }), 400
        
        task_manager = TaskManager()
        task = task_manager.get_task(task_id)
        
        if not task:
            return jsonify({
                "success": False,
                "error": f"taskNot Exist: {task_id}"
            }), 404
        
        return jsonify({
            "success": True,
            "data": task.to_dict()
        })
        
    except Exception as e:
        logger.error(f"querytaskStatusfail: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============== reportGetconnectperson ==============

@report_bp.route('/<report_id>', methods=['GET'])
def get_report(report_id: str):
    """
    Get report details
    
    Returns:
        {
            "success": true,
            "data": {
                "report_id": "report_xxxx",
                "simulation_id": "sim_xxxx",
                "status": "completed",
                "outline": {...},
                "markdown_content": "...",
                "created_at": "...",
                "completed_at": "..."
            }
        }
    """
    try:
        report = ReportManager.get_report(report_id)
        
        if not report:
            return jsonify({
                "success": False,
                "error": f"Report does not exist: {report_id}"
            }), 404
        
        return jsonify({
            "success": True,
            "data": report.to_dict()
        })
        
    except Exception as e:
        logger.error(f"Failed to get report: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/by-simulation/<simulation_id>', methods=['GET'])
def get_report_by_simulation(simulation_id: str):
    """
    Get a report by simulation ID
    
    Returns:
        {
            "success": true,
            "data": {
                "report_id": "report_xxxx",
                ...
            }
        }
    """
    try:
        report = ReportManager.get_report_by_simulation(simulation_id)
        
        if not report:
            return jsonify({
                "success": False,
                "error": f"shouldsimulatenonereport: {simulation_id}",
                "has_report": False
            }), 404
        
        return jsonify({
            "success": True,
            "data": report.to_dict(),
            "has_report": True
        })
        
    except Exception as e:
        logger.error(f"Failed to get report: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/list', methods=['GET'])
def list_reports():
    """
    List existing reports
    
    Query parameters:
        simulation_id: Filter by simulation ID (optional)
        limit: Maximum number of results to return (default 50)
    
    Returns:
        {
            "success": true,
            "data": [...],
            "count": 10
        }
    """
    try:
        simulation_id = request.args.get('simulation_id')
        limit = request.args.get('limit', 50, type=int)
        
        reports = ReportManager.list_reports(
            simulation_id=simulation_id,
            limit=limit
        )
        
        return jsonify({
            "success": True,
            "data": [r.to_dict() for r in reports],
            "count": len(reports)
        })
        
    except Exception as e:
        logger.error(f"columnoutreportfail: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/download', methods=['GET'])
def download_report(report_id: str):
    """
    Download a report (in Markdown format)
    
    Returns a Markdown file
    """
    try:
        report = ReportManager.get_report(report_id)
        
        if not report:
            return jsonify({
                "success": False,
                "error": f"Report does not exist: {report_id}"
            }), 404
        
        md_path = ReportManager._get_report_markdown_path(report_id)
        
        if not os.path.exists(md_path):
            # ifMDFileNot Exist，GenerateaapproachhourFile
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
                f.write(report.markdown_content)
                temp_path = f.name
            
            return send_file(
                temp_path,
                as_attachment=True,
                download_name=f"{report_id}.md"
            )
        
        return send_file(
            md_path,
            as_attachment=True,
            download_name=f"{report_id}.md"
        )
        
    except Exception as e:
        logger.error(f"underloadreportfail: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>', methods=['DELETE'])
def delete_report(report_id: str):
    """deletereport"""
    try:
        success = ReportManager.delete_report(report_id)
        
        if not success:
            return jsonify({
                "success": False,
                "error": f"Report does not exist: {report_id}"
            }), 404
        
        return jsonify({
            "success": True,
            "message": f"reportdelete: {report_id}"
        })
        
    except Exception as e:
        logger.error(f"deletereportfail: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Report Agenttowardchatconnectperson ==============

@report_bp.route('/chat', methods=['POST'])
def chat_with_report_agent():
    """
    Chat with the Report Agent
    
    The Report Agent can autonomously invoke retrieval tools during the conversation to answer questions.
    
    Request (JSON):
        {
            "simulation_id": "sim_xxxx",        // Required, simulation ID
            "message": "Help me analyze the direction of this situation",    // Required, user message
            "chat_history": [                   // Optional, conversation history
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "..."}
            ]
        }
    
    Returns:
        {
            "success": true,
            "data": {
                "response": "Agent reply...",
                "tool_calls": [list of invoked tools],
                "sources": [information sources]
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        message = data.get('message')
        chat_history = data.get('chat_history', [])
        
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Please provide simulation_id"
            }), 400
        
        if not message:
            return jsonify({
                "success": False,
                "error": "please message"
            }), 400
        
        # Getsimulatesumitemiteminformation
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        
        if not state:
            return jsonify({
                "success": False,
                "error": f"Simulation does not exist: {simulation_id}"
            }), 404
        
        project = ProjectManager.get_project(state.project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": f"Project does not exist: {state.project_id}"
            }), 404
        
        graph_id = state.graph_id or project.graph_id
        if not graph_id:
            return jsonify({
                "success": False,
                "error": "lackfewGraphID"
            }), 400
        
        simulation_requirement = project.simulation_requirement or ""
        
        # createAgentandentergotowardchat
        agent = ReportAgent(
            graph_id=graph_id,
            simulation_id=simulation_id,
            simulation_requirement=simulation_requirement
        )
        
        result = agent.chat(message=message, chat_history=chat_history)
        
        return jsonify({
            "success": True,
            "data": result
        })
        
    except Exception as e:
        logger.error(f"towardchatfail: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== reportenterdepthandminutesectionconnectperson ==============

@report_bp.route('/<report_id>/progress', methods=['GET'])
def get_report_progress(report_id: str):
    """
    Get report generation progress (real-time)
    
    Returns:
        {
            "success": true,
            "data": {
                "status": "generating",
                "progress": 45,
                "message": "Generating section: key findings",
                "current_section": "key_findings",
                "completed_sections": ["executive_summary", "simulation_background"],
                "updated_at": "2025-12-09T..."
            }
        }
    """
    try:
        progress = ReportManager.get_progress(report_id)
        
        if not progress:
            return jsonify({
                "success": False,
                "error": f"reportNot Existorenterdepthinformationnoavailable: {report_id}"
            }), 404
        
        return jsonify({
            "success": True,
            "data": progress
        })
        
    except Exception as e:
        logger.error(f"Getreportenterdepthfail: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/sections', methods=['GET'])
def get_report_sections(report_id: str):
    """
    Get the list of generated sections (incremental output)
    
    The frontend can use this endpoint to retrieve section content as it is generated, without waiting for the entire report to complete.
    
    Returns:
        {
            "success": true,
            "data": {
                "report_id": "report_xxxx",
                "sections": [
                    {
                        "filename": "section_01.md",
                        "section_index": 1,
                        "content": "## Executive Summary\\n\\n..."
                    },
                    ...
                ],
                "total_sections": 3,
                "is_complete": false
            }
        }
    """
    try:
        sections = ReportManager.get_generated_sections(report_id)
        
        # GetreportStatus
        report = ReportManager.get_report(report_id)
        is_complete = report is not None and report.status == ReportStatus.COMPLETED
        
        return jsonify({
            "success": True,
            "data": {
                "report_id": report_id,
                "sections": sections,
                "total_sections": len(sections),
                "is_complete": is_complete
            }
        })
        
    except Exception as e:
        logger.error(f"Getsectionlistfail: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/section/<int:section_index>', methods=['GET'])
def get_single_section(report_id: str, section_index: int):
    """
    Get the content of a single section
    
    Returns:
        {
            "success": true,
            "data": {
                "filename": "section_01.md",
                "content": "## Executive Summary\\n\\n..."
            }
        }
    """
    try:
        section_path = ReportManager._get_section_path(report_id, section_index)
        
        if not os.path.exists(section_path):
            return jsonify({
                "success": False,
                "error": f"sectionNot Exist: section_{section_index:02d}.md"
            }), 404
        
        with open(section_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return jsonify({
            "success": True,
            "data": {
                "filename": f"section_{section_index:02d}.md",
                "section_index": section_index,
                "content": content
            }
        })
        
    except Exception as e:
        logger.error(f"Getsectioncontentfail: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== reportStatuscheckconnectperson ==============

@report_bp.route('/check/<simulation_id>', methods=['GET'])
def check_report_status(simulation_id: str):
    """
    Check whether a simulation has a report, and return the report status
    
    Used by the frontend to determine whether to unlock the interview feature.
    
    Returns:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "has_report": true,
                "report_status": "completed",
                "report_id": "report_xxxx",
                "interview_unlocked": true
            }
        }
    """
    try:
        report = ReportManager.get_report_by_simulation(simulation_id)
        
        has_report = report is not None
        report_status = report.status.value if report else None
        report_id = report.report_id if report else None
        
        # onlyhavereportcompleteAfteruntielockinterview
        interview_unlocked = has_report and report.status == ReportStatus.COMPLETED
        
        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "has_report": has_report,
                "report_status": report_status,
                "report_id": report_id,
                "interview_unlocked": interview_unlocked
            }
        })
        
    except Exception as e:
        logger.error(f"checkreportStatusfail: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Agent logconnectperson ==============

@report_bp.route('/<report_id>/agent-log', methods=['GET'])
def get_agent_log(report_id: str):
    """
    Get detailed execution logs for the Report Agent
    
    Retrieve each step of the report generation process in real time, including:
    - report start, planning start/complete
    - each section: start, tool calls, LLM responses, completion
    - report completion or failure
    
    Query parameters:
        from_line: Start reading from this line number (optional, default 0, used for incremental retrieval)
    
    Returns:
        {
            "success": true,
            "data": {
                "logs": [
                    {
                        "timestamp": "2025-12-13T...",
                        "elapsed_seconds": 12.5,
                        "report_id": "report_xxxx",
                        "action": "tool_call",
                        "stage": "generating",
                        "section_title": "executive_summary",
                        "section_index": 1,
                        "details": {
                            "tool_name": "insight_forge",
                            "parameters": {...},
                            ...
                        }
                    },
                    ...
                ],
                "total_lines": 25,
                "from_line": 0,
                "has_more": false
            }
        }
    """
    try:
        from_line = request.args.get('from_line', 0, type=int)
        
        log_data = ReportManager.get_agent_log(report_id, from_line=from_line)
        
        return jsonify({
            "success": True,
            "data": log_data
        })
        
    except Exception as e:
        logger.error(f"Failed to get agent log: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/agent-log/stream', methods=['GET'])
def stream_agent_log(report_id: str):
    """
    Get the complete agent log (retrieve all at once)
    
    Returns:
        {
            "success": true,
            "data": {
                "logs": [...],
                "count": 25
            }
        }
    """
    try:
        logs = ReportManager.get_agent_log_stream(report_id)
        
        return jsonify({
            "success": True,
            "data": {
                "logs": logs,
                "count": len(logs)
            }
        })
        
    except Exception as e:
        logger.error(f"Failed to get agent log: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== controllogconnectperson ==============

@report_bp.route('/<report_id>/console-log', methods=['GET'])
def get_console_log(report_id: str):
    """
    Get the Report Agent's console output logs
    
    Retrieve the console output (INFO, WARNING, etc.) during report generation in real time.
    Unlike the agent-log endpoint, which returns structured JSON logs,
    these are plain-text, console-style logs.
    
    Query parameters:
        from_line: Start reading from this line number (optional, default 0, used for incremental retrieval)
    
    Returns:
        {
            "success": true,
            "data": {
                "logs": [
                    "[19:46:14] INFO: Search complete: found 15 relevant facts",
                    "[19:46:14] INFO: Graph search: graph_id=xxx, query=...",
                    ...
                ],
                "total_lines": 100,
                "from_line": 0,
                "has_more": false
            }
        }
    """
    try:
        from_line = request.args.get('from_line', 0, type=int)
        
        log_data = ReportManager.get_console_log(report_id, from_line=from_line)
        
        return jsonify({
            "success": True,
            "data": log_data
        })
        
    except Exception as e:
        logger.error(f"Failed to get console log: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/console-log/stream', methods=['GET'])
def stream_console_log(report_id: str):
    """
    Get the complete console log (retrieve all at once)
    
    Returns:
        {
            "success": true,
            "data": {
                "logs": [...],
                "count": 100
            }
        }
    """
    try:
        logs = ReportManager.get_console_log_stream(report_id)
        
        return jsonify({
            "success": True,
            "data": {
                "logs": logs,
                "count": len(logs)
            }
        })
        
    except Exception as e:
        logger.error(f"Failed to get console log: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== toolinvokeconnectperson（testuse）==============

@report_bp.route('/tools/search', methods=['POST'])
def search_graph_tool():
    """
    Graph search tool endpoint (for testing)
    
    Request (JSON):
        {
            "graph_id": "mirofish_xxxx",
            "query": "search query",
            "limit": 10
        }
    """
    try:
        data = request.get_json() or {}
        
        graph_id = data.get('graph_id')
        query = data.get('query')
        limit = data.get('limit', 10)
        
        if not graph_id or not query:
            return jsonify({
                "success": False,
                "error": "please graph_id sum query"
            }), 400
        
        from ..services.zep_tools import ZepToolsService
        
        tools = ZepToolsService()
        result = tools.search_graph(
            graph_id=graph_id,
            query=query,
            limit=limit
        )
        
        return jsonify({
            "success": True,
            "data": result.to_dict()
        })
        
    except Exception as e:
        logger.error(f"Graphsearchfail: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/tools/statistics', methods=['POST'])
def get_graph_statistics_tool():
    """
    Graph statistics tool endpoint (for testing)
    
    Request (JSON):
        {
            "graph_id": "mirofish_xxxx"
        }
    """
    try:
        data = request.get_json() or {}
        
        graph_id = data.get('graph_id')
        
        if not graph_id:
            return jsonify({
                "success": False,
                "error": "please graph_id"
            }), 400
        
        from ..services.zep_tools import ZepToolsService
        
        tools = ZepToolsService()
        result = tools.get_graph_statistics(graph_id)
        
        return jsonify({
            "success": True,
            "data": result
        })
        
    except Exception as e:
        logger.error(f"Get graphstatisticsfail: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500
