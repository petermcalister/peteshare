#!/usr/bin/env python3
"""
TODO Task Management MCP Server with Git-based Lease Coordination

This MCP server manages TODO work tasks with the following features:
- File-based state management in a local directory
- Git commit-based lease mechanism for distributed work coordination
- Task allocation and context storage
- Automatic conflict prevention through lease commits

Author: Pete
"""

import json
import os
import asyncio
import inspect
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
import subprocess
import uuid
import hashlib
from fastmcp import FastMCP, Context

# Configure logging as per your standards
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='todo_mcp.log',
    filemode='a'
)
logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP("TODO Task Manager")

# ========================
# Data Models
# ========================

class TaskStatus(Enum):
    """Status of a TODO task"""
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"

class LeaseStatus(Enum):
    """Status of a task lease"""
    ACTIVE = "active"
    EXPIRED = "expired"
    RELEASED = "released"

@dataclass
class TaskContext:
    """Context information stored with a task"""
    strDescription: str
    dictMetadata: Dict[str, Any] = field(default_factory=dict)
    lstRelatedFiles: List[str] = field(default_factory=list)
    strRequirements: str = ""
    strAcceptanceCriteria: str = ""
    dtCreated: datetime = field(default_factory=datetime.now)
    dtUpdated: datetime = field(default_factory=datetime.now)

@dataclass
class TaskLease:
    """Lease information for a task"""
    strLeaseId: str
    strTaskKey: str
    strAssignee: str
    dtLeaseStart: datetime
    dtLeaseExpiry: datetime
    strCommitHash: str
    enumStatus: LeaseStatus = LeaseStatus.ACTIVE
    
    def is_expired(self) -> bool:
        """Check if lease has expired"""
        return datetime.now() > self.dtLeaseExpiry

@dataclass
class TodoTask:
    """A TODO work task"""
    strKey: str  # Short name/key for the task (e.g., "AEP-001")
    strTitle: str
    strAssignee: Optional[str] = None
    enumStatus: TaskStatus = TaskStatus.OPEN
    objContext: TaskContext = field(default_factory=TaskContext)
    objLease: Optional[TaskLease] = None
    lstSubTasks: List[str] = field(default_factory=list)
    dictTags: Dict[str, str] = field(default_factory=dict)
    dtCreated: datetime = field(default_factory=datetime.now)
    dtUpdated: datetime = field(default_factory=datetime.now)
    dtDue: Optional[datetime] = None
    intPriority: int = 0  # Higher number = higher priority

# ========================
# Storage Manager
# ========================

class TaskStorageManager:
    """Manages file-based storage of tasks"""
    
    def __init__(self, strBasePath: str = "./todo_tasks"):
        """
        Initialize storage manager
        
        Args:
            strBasePath: Base directory for storing task data
        """
        self.pathBase = Path(strBasePath)
        self.pathTasks = self.pathBase / "tasks"
        self.pathLeases = self.pathBase / "leases"
        self.pathContext = self.pathBase / "context"
        self.pathArchive = self.pathBase / "archive"
        
        # Create directory structure
        for path in [self.pathTasks, self.pathLeases, self.pathContext, self.pathArchive]:
            path.mkdir(parents=True, exist_ok=True)
            
    def save_task(self, objTask: TodoTask) -> None:
        """Save a task to disk"""
        try:
            objTask.dtUpdated = datetime.now()
            strFilePath = self.pathTasks / f"{objTask.strKey}.json"
            
            # Convert task to JSON-serializable format
            dictTask = self._task_to_dict(objTask)
            
            with open(strFilePath, 'w') as file:
                json.dump(dictTask, file, indent=4, default=str)
                
            logger.info(f"Saved task {objTask.strKey} to {strFilePath}")
            
        except Exception as e:
            current_function = inspect.currentframe().f_code.co_name
            print(f"An error occurred in {current_function}: {e}")
            logger.warning(f"An error occurred in {current_function}: {e}")
            raise e
    
    def load_task(self, strKey: str) -> Optional[TodoTask]:
        """Load a task from disk"""
        try:
            strFilePath = self.pathTasks / f"{strKey}.json"
            
            if not strFilePath.exists():
                return None
                
            with open(strFilePath, 'r') as file:
                dictTask = json.load(file)
                
            return self._dict_to_task(dictTask)
            
        except Exception as e:
            current_function = inspect.currentframe().f_code.co_name
            print(f"An error occurred in {current_function}: {e}")
            logger.warning(f"An error occurred in {current_function}: {e}")
            raise e
    
    def list_tasks(self) -> List[TodoTask]:
        """List all tasks"""
        try:
            lstTasks = []
            
            for strFilePath in self.pathTasks.glob("*.json"):
                with open(strFilePath, 'r') as file:
                    dictTask = json.load(file)
                    lstTasks.append(self._dict_to_task(dictTask))
                    
            return lstTasks
            
        except Exception as e:
            current_function = inspect.currentframe().f_code.co_name
            print(f"An error occurred in {current_function}: {e}")
            logger.warning(f"An error occurred in {current_function}: {e}")
            raise e
    
    def save_lease(self, objLease: TaskLease) -> None:
        """Save a lease to disk"""
        try:
            strFilePath = self.pathLeases / f"{objLease.strLeaseId}.json"
            
            dictLease = {
                "strLeaseId": objLease.strLeaseId,
                "strTaskKey": objLease.strTaskKey,
                "strAssignee": objLease.strAssignee,
                "dtLeaseStart": objLease.dtLeaseStart.isoformat(),
                "dtLeaseExpiry": objLease.dtLeaseExpiry.isoformat(),
                "strCommitHash": objLease.strCommitHash,
                "enumStatus": objLease.enumStatus.value
            }
            
            with open(strFilePath, 'w') as file:
                json.dump(dictLease, file, indent=4)
                
            logger.info(f"Saved lease {objLease.strLeaseId} to {strFilePath}")
            
        except Exception as e:
            current_function = inspect.currentframe().f_code.co_name
            print(f"An error occurred in {current_function}: {e}")
            logger.warning(f"An error occurred in {current_function}: {e}")
            raise e
    
    def load_active_leases(self) -> List[TaskLease]:
        """Load all active leases"""
        try:
            lstLeases = []
            
            for strFilePath in self.pathLeases.glob("*.json"):
                with open(strFilePath, 'r') as file:
                    dictLease = json.load(file)
                    
                objLease = TaskLease(
                    strLeaseId=dictLease["strLeaseId"],
                    strTaskKey=dictLease["strTaskKey"],
                    strAssignee=dictLease["strAssignee"],
                    dtLeaseStart=datetime.fromisoformat(dictLease["dtLeaseStart"]),
                    dtLeaseExpiry=datetime.fromisoformat(dictLease["dtLeaseExpiry"]),
                    strCommitHash=dictLease["strCommitHash"],
                    enumStatus=LeaseStatus(dictLease["enumStatus"])
                )
                
                if objLease.enumStatus == LeaseStatus.ACTIVE:
                    lstLeases.append(objLease)
                    
            return lstLeases
            
        except Exception as e:
            current_function = inspect.currentframe().f_code.co_name
            print(f"An error occurred in {current_function}: {e}")
            logger.warning(f"An error occurred in {current_function}: {e}")
            raise e
    
    def _task_to_dict(self, objTask: TodoTask) -> dict:
        """Convert task object to dictionary"""
        return {
            "strKey": objTask.strKey,
            "strTitle": objTask.strTitle,
            "strAssignee": objTask.strAssignee,
            "enumStatus": objTask.enumStatus.value,
            "objContext": {
                "strDescription": objTask.objContext.strDescription,
                "dictMetadata": objTask.objContext.dictMetadata,
                "lstRelatedFiles": objTask.objContext.lstRelatedFiles,
                "strRequirements": objTask.objContext.strRequirements,
                "strAcceptanceCriteria": objTask.objContext.strAcceptanceCriteria,
                "dtCreated": objTask.objContext.dtCreated.isoformat(),
                "dtUpdated": objTask.objContext.dtUpdated.isoformat()
            },
            "objLease": self._lease_to_dict(objTask.objLease) if objTask.objLease else None,
            "lstSubTasks": objTask.lstSubTasks,
            "dictTags": objTask.dictTags,
            "dtCreated": objTask.dtCreated.isoformat(),
            "dtUpdated": objTask.dtUpdated.isoformat(),
            "dtDue": objTask.dtDue.isoformat() if objTask.dtDue else None,
            "intPriority": objTask.intPriority
        }
    
    def _dict_to_task(self, dictTask: dict) -> TodoTask:
        """Convert dictionary to task object"""
        objContext = TaskContext(
            strDescription=dictTask["objContext"]["strDescription"],
            dictMetadata=dictTask["objContext"]["dictMetadata"],
            lstRelatedFiles=dictTask["objContext"]["lstRelatedFiles"],
            strRequirements=dictTask["objContext"]["strRequirements"],
            strAcceptanceCriteria=dictTask["objContext"]["strAcceptanceCriteria"],
            dtCreated=datetime.fromisoformat(dictTask["objContext"]["dtCreated"]),
            dtUpdated=datetime.fromisoformat(dictTask["objContext"]["dtUpdated"])
        )
        
        objLease = None
        if dictTask["objLease"]:
            objLease = self._dict_to_lease(dictTask["objLease"])
        
        return TodoTask(
            strKey=dictTask["strKey"],
            strTitle=dictTask["strTitle"],
            strAssignee=dictTask["strAssignee"],
            enumStatus=TaskStatus(dictTask["enumStatus"]),
            objContext=objContext,
            objLease=objLease,
            lstSubTasks=dictTask["lstSubTasks"],
            dictTags=dictTask["dictTags"],
            dtCreated=datetime.fromisoformat(dictTask["dtCreated"]),
            dtUpdated=datetime.fromisoformat(dictTask["dtUpdated"]),
            dtDue=datetime.fromisoformat(dictTask["dtDue"]) if dictTask["dtDue"] else None,
            intPriority=dictTask["intPriority"]
        )
    
    def _lease_to_dict(self, objLease: Optional[TaskLease]) -> Optional[dict]:
        """Convert lease object to dictionary"""
        if not objLease:
            return None
            
        return {
            "strLeaseId": objLease.strLeaseId,
            "strTaskKey": objLease.strTaskKey,
            "strAssignee": objLease.strAssignee,
            "dtLeaseStart": objLease.dtLeaseStart.isoformat(),
            "dtLeaseExpiry": objLease.dtLeaseExpiry.isoformat(),
            "strCommitHash": objLease.strCommitHash,
            "enumStatus": objLease.enumStatus.value
        }
    
    def _dict_to_lease(self, dictLease: dict) -> TaskLease:
        """Convert dictionary to lease object"""
        return TaskLease(
            strLeaseId=dictLease["strLeaseId"],
            strTaskKey=dictLease["strTaskKey"],
            strAssignee=dictLease["strAssignee"],
            dtLeaseStart=datetime.fromisoformat(dictLease["dtLeaseStart"]),
            dtLeaseExpiry=datetime.fromisoformat(dictLease["dtLeaseExpiry"]),
            strCommitHash=dictLease["strCommitHash"],
            enumStatus=LeaseStatus(dictLease["enumStatus"])
        )

# ========================
# Git Manager
# ========================

class GitLeaseManager:
    """Manages Git-based lease coordination"""
    
    def __init__(self, strRepoPath: str = "."):
        """
        Initialize Git manager
        
        Args:
            strRepoPath: Path to the Git repository
        """
        self.strRepoPath = strRepoPath
        
    def create_lease_commit(self, strTaskKey: str, strAssignee: str, boolStart: bool = True) -> str:
        """
        Create a lease commit in Git
        
        Args:
            strTaskKey: Task key (e.g., "AEP-001")
            strAssignee: Who is taking the lease
            boolStart: True for START, False for END
            
        Returns:
            Commit hash of the lease commit
        """
        try:
            strAction = "START" if boolStart else "END"
            strMessage = f"{strTaskKey}: TODO {strAssignee} {strAction}"
            
            # Create an empty commit with the lease message
            result = subprocess.run(
                ["git", "commit", "--allow-empty", "-m", strMessage],
                cwd=self.strRepoPath,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                raise RuntimeError(f"Git commit failed: {result.stderr}")
            
            # Get the commit hash
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.strRepoPath,
                capture_output=True,
                text=True
            )
            
            strCommitHash = result.stdout.strip()
            
            # Push the commit
            result = subprocess.run(
                ["git", "push"],
                cwd=self.strRepoPath,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                # Try force-with-lease if regular push fails
                result = subprocess.run(
                    ["git", "push", "--force-with-lease"],
                    cwd=self.strRepoPath,
                    capture_output=True,
                    text=True
                )
                
                if result.returncode != 0:
                    raise RuntimeError(f"Git push failed: {result.stderr}")
            
            logger.info(f"Created lease commit {strCommitHash} for task {strTaskKey}")
            return strCommitHash
            
        except Exception as e:
            current_function = inspect.currentframe().f_code.co_name
            print(f"An error occurred in {current_function}: {e}")
            logger.warning(f"An error occurred in {current_function}: {e}")
            raise e
    
    def check_for_conflicts(self, strTaskKey: str) -> bool:
        """
        Check if there are any conflicting leases for a task
        
        Args:
            strTaskKey: Task key to check
            
        Returns:
            True if there are conflicts, False otherwise
        """
        try:
            # Fetch latest commits
            subprocess.run(
                ["git", "fetch"],
                cwd=self.strRepoPath,
                capture_output=True,
                text=True
            )
            
            # Search for lease commits for this task
            result = subprocess.run(
                ["git", "log", "--grep", f"^{strTaskKey}:", "--format=%H %s", "origin/main"],
                cwd=self.strRepoPath,
                capture_output=True,
                text=True
            )
            
            lstCommits = result.stdout.strip().split('\n') if result.stdout.strip() else []
            
            # Check for active leases (START without matching END)
            dictLeases = {}
            for strCommit in lstCommits:
                if strCommit:
                    lstParts = strCommit.split(' ', 1)
                    if len(lstParts) == 2:
                        strHash, strMessage = lstParts
                        
                        # Parse the message
                        if ": TODO " in strMessage:
                            lstMessageParts = strMessage.split(": TODO ")
                            if len(lstMessageParts) == 2:
                                strKey, strRest = lstMessageParts
                                lstRestParts = strRest.rsplit(' ', 1)
                                if len(lstRestParts) == 2:
                                    strUser, strAction = lstRestParts
                                    
                                    if strAction == "START":
                                        dictLeases[strUser] = strHash
                                    elif strAction == "END" and strUser in dictLeases:
                                        del dictLeases[strUser]
            
            # If there are active leases, there's a conflict
            return len(dictLeases) > 0
            
        except Exception as e:
            current_function = inspect.currentframe().f_code.co_name
            print(f"An error occurred in {current_function}: {e}")
            logger.warning(f"An error occurred in {current_function}: {e}")
            raise e
    
    def search_remote_commits(self, strPattern: str = "TODO") -> List[Dict[str, str]]:
        """
        Search for remote commits matching a pattern
        
        Args:
            strPattern: Pattern to search for in commit messages
            
        Returns:
            List of matching commits
        """
        try:
            # Fetch latest commits
            subprocess.run(
                ["git", "fetch"],
                cwd=self.strRepoPath,
                capture_output=True,
                text=True
            )
            
            # Search for commits
            result = subprocess.run(
                ["git", "log", "--grep", strPattern, "--format=%H|%an|%ae|%ai|%s", "origin/main"],
                cwd=self.strRepoPath,
                capture_output=True,
                text=True
            )
            
            lstCommits = []
            for strLine in result.stdout.strip().split('\n'):
                if strLine:
                    lstParts = strLine.split('|', 4)
                    if len(lstParts) == 5:
                        lstCommits.append({
                            "hash": lstParts[0],
                            "author": lstParts[1],
                            "email": lstParts[2],
                            "date": lstParts[3],
                            "message": lstParts[4]
                        })
            
            return lstCommits
            
        except Exception as e:
            current_function = inspect.currentframe().f_code.co_name
            print(f"An error occurred in {current_function}: {e}")
            logger.warning(f"An error occurred in {current_function}: {e}")
            raise e

# ========================
# Global instances
# ========================

storage_manager = TaskStorageManager()
git_manager = GitLeaseManager()

# ========================
# MCP Tools
# ========================

@mcp.tool
async def create_task(
    strKey: str,
    strTitle: str,
    strDescription: str,
    intPriority: int = 0,
    strDueDate: Optional[str] = None,
    dictTags: Optional[Dict[str, str]] = None,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Create a new TODO task
    
    Args:
        strKey: Unique task key (e.g., "AEP-001")
        strTitle: Task title
        strDescription: Detailed description
        intPriority: Priority level (0-10)
        strDueDate: Due date in ISO format
        dictTags: Optional tags
        ctx: MCP context
        
    Returns:
        Created task details
    """
    try:
        # Check if task already exists
        existing_task = storage_manager.load_task(strKey)
        if existing_task:
            return {
                "success": False,
                "error": f"Task {strKey} already exists"
            }
        
        # Create task context
        objContext = TaskContext(
            strDescription=strDescription,
            dictMetadata={
                "created_by": os.environ.get("USER", "unknown"),
                "created_at": datetime.now().isoformat()
            }
        )
        
        # Parse due date
        dtDue = None
        if strDueDate:
            dtDue = datetime.fromisoformat(strDueDate)
        
        # Create task
        objTask = TodoTask(
            strKey=strKey,
            strTitle=strTitle,
            objContext=objContext,
            intPriority=intPriority,
            dtDue=dtDue,
            dictTags=dictTags or {}
        )
        
        # Save task
        storage_manager.save_task(objTask)
        
        if ctx:
            ctx.info(f"Created task {strKey}: {strTitle}")
        
        return {
            "success": True,
            "task": storage_manager._task_to_dict(objTask)
        }
        
    except Exception as e:
        current_function = inspect.currentframe().f_code.co_name
        print(f"An error occurred in {current_function}: {e}")
        logger.warning(f"An error occurred in {current_function}: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@mcp.tool
async def start_work(
    strTaskKey: str,
    strAssignee: str,
    intLeaseHours: int = 4,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Start work on a task by acquiring a lease
    
    Args:
        strTaskKey: Task key to work on
        strAssignee: Who is starting the work
        intLeaseHours: How many hours to lease for
        ctx: MCP context
        
    Returns:
        Lease information
    """
    try:
        # Load task
        objTask = storage_manager.load_task(strTaskKey)
        if not objTask:
            return {
                "success": False,
                "error": f"Task {strTaskKey} not found"
            }
        
        # Check for existing lease
        if objTask.objLease and objTask.objLease.enumStatus == LeaseStatus.ACTIVE:
            if not objTask.objLease.is_expired():
                return {
                    "success": False,
                    "error": f"Task already leased to {objTask.objLease.strAssignee} until {objTask.objLease.dtLeaseExpiry}"
                }
        
        # Check for conflicts in Git
        if git_manager.check_for_conflicts(strTaskKey):
            return {
                "success": False,
                "error": "Conflicting lease found in Git. Please sync and try again."
            }
        
        # Create lease commit
        strCommitHash = git_manager.create_lease_commit(strTaskKey, strAssignee, True)
        
        # Create lease
        objLease = TaskLease(
            strLeaseId=str(uuid.uuid4()),
            strTaskKey=strTaskKey,
            strAssignee=strAssignee,
            dtLeaseStart=datetime.now(),
            dtLeaseExpiry=datetime.now() + timedelta(hours=intLeaseHours),
            strCommitHash=strCommitHash,
            enumStatus=LeaseStatus.ACTIVE
        )
        
        # Update task
        objTask.objLease = objLease
        objTask.strAssignee = strAssignee
        objTask.enumStatus = TaskStatus.IN_PROGRESS
        
        # Save
        storage_manager.save_task(objTask)
        storage_manager.save_lease(objLease)
        
        if ctx:
            ctx.info(f"Started work on {strTaskKey} for {strAssignee}")
        
        return {
            "success": True,
            "lease": {
                "lease_id": objLease.strLeaseId,
                "task_key": objLease.strTaskKey,
                "assignee": objLease.strAssignee,
                "expires": objLease.dtLeaseExpiry.isoformat(),
                "commit": objLease.strCommitHash
            }
        }
        
    except Exception as e:
        current_function = inspect.currentframe().f_code.co_name
        print(f"An error occurred in {current_function}: {e}")
        logger.warning(f"An error occurred in {current_function}: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@mcp.tool
async def end_work(
    strTaskKey: str,
    strAssignee: str,
    boolMarkComplete: bool = False,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    End work on a task by releasing the lease
    
    Args:
        strTaskKey: Task key
        strAssignee: Who is ending the work
        boolMarkComplete: Whether to mark task as complete
        ctx: MCP context
        
    Returns:
        Update result
    """
    try:
        # Load task
        objTask = storage_manager.load_task(strTaskKey)
        if not objTask:
            return {
                "success": False,
                "error": f"Task {strTaskKey} not found"
            }
        
        # Check lease
        if not objTask.objLease or objTask.objLease.strAssignee != strAssignee:
            return {
                "success": False,
                "error": f"No active lease for {strAssignee} on task {strTaskKey}"
            }
        
        # Create end commit
        strCommitHash = git_manager.create_lease_commit(strTaskKey, strAssignee, False)
        
        # Update lease
        objTask.objLease.enumStatus = LeaseStatus.RELEASED
        
        # Update task status
        if boolMarkComplete:
            objTask.enumStatus = TaskStatus.COMPLETED
        else:
            objTask.enumStatus = TaskStatus.OPEN
            objTask.strAssignee = None
        
        # Save
        storage_manager.save_task(objTask)
        storage_manager.save_lease(objTask.objLease)
        
        if ctx:
            ctx.info(f"Ended work on {strTaskKey} for {strAssignee}")
        
        return {
            "success": True,
            "task_key": strTaskKey,
            "status": objTask.enumStatus.value,
            "commit": strCommitHash
        }
        
    except Exception as e:
        current_function = inspect.currentframe().f_code.co_name
        print(f"An error occurred in {current_function}: {e}")
        logger.warning(f"An error occurred in {current_function}: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@mcp.tool
async def list_tasks(
    strStatusFilter: Optional[str] = None,
    boolShowLeased: bool = True,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    List all TODO tasks
    
    Args:
        strStatusFilter: Filter by status
        boolShowLeased: Include leased tasks
        ctx: MCP context
        
    Returns:
        List of tasks
    """
    try:
        # Load all tasks
        lstAllTasks = storage_manager.list_tasks()
        
        # Filter tasks
        lstFilteredTasks = []
        for objTask in lstAllTasks:
            # Status filter
            if strStatusFilter and objTask.enumStatus.value != strStatusFilter:
                continue
            
            # Lease filter
            if not boolShowLeased and objTask.objLease and objTask.objLease.enumStatus == LeaseStatus.ACTIVE:
                continue
            
            lstFilteredTasks.append({
                "key": objTask.strKey,
                "title": objTask.strTitle,
                "status": objTask.enumStatus.value,
                "assignee": objTask.strAssignee,
                "priority": objTask.intPriority,
                "due": objTask.dtDue.isoformat() if objTask.dtDue else None,
                "has_lease": bool(objTask.objLease and objTask.objLease.enumStatus == LeaseStatus.ACTIVE)
            })
        
        # Sort by priority
        lstFilteredTasks.sort(key=lambda x: x["priority"], reverse=True)
        
        if ctx:
            ctx.info(f"Listed {len(lstFilteredTasks)} tasks")
        
        return {
            "success": True,
            "count": len(lstFilteredTasks),
            "tasks": lstFilteredTasks
        }
        
    except Exception as e:
        current_function = inspect.currentframe().f_code.co_name
        print(f"An error occurred in {current_function}: {e}")
        logger.warning(f"An error occurred in {current_function}: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@mcp.tool
async def update_context(
    strTaskKey: str,
    dictContext: Dict[str, Any],
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Update task context
    
    Args:
        strTaskKey: Task key
        dictContext: Context updates
        ctx: MCP context
        
    Returns:
        Update result
    """
    try:
        # Load task
        objTask = storage_manager.load_task(strTaskKey)
        if not objTask:
            return {
                "success": False,
                "error": f"Task {strTaskKey} not found"
            }
        
        # Update context
        if "description" in dictContext:
            objTask.objContext.strDescription = dictContext["description"]
        if "requirements" in dictContext:
            objTask.objContext.strRequirements = dictContext["requirements"]
        if "acceptance_criteria" in dictContext:
            objTask.objContext.strAcceptanceCriteria = dictContext["acceptance_criteria"]
        if "metadata" in dictContext:
            objTask.objContext.dictMetadata.update(dictContext["metadata"])
        if "related_files" in dictContext:
            objTask.objContext.lstRelatedFiles = dictContext["related_files"]
        
        objTask.objContext.dtUpdated = datetime.now()
        
        # Save
        storage_manager.save_task(objTask)
        
        if ctx:
            ctx.info(f"Updated context for task {strTaskKey}")
        
        return {
            "success": True,
            "task_key": strTaskKey,
            "updated_at": objTask.objContext.dtUpdated.isoformat()
        }
        
    except Exception as e:
        current_function = inspect.currentframe().f_code.co_name
        print(f"An error occurred in {current_function}: {e}")
        logger.warning(f"An error occurred in {current_function}: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@mcp.tool
async def search_commits(
    strPattern: str = "TODO",
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Search for lease commits in Git
    
    Args:
        strPattern: Pattern to search for
        ctx: MCP context
        
    Returns:
        Matching commits
    """
    try:
        lstCommits = git_manager.search_remote_commits(strPattern)
        
        if ctx:
            ctx.info(f"Found {len(lstCommits)} commits matching '{strPattern}'")
        
        return {
            "success": True,
            "count": len(lstCommits),
            "commits": lstCommits
        }
        
    except Exception as e:
        current_function = inspect.currentframe().f_code.co_name
        print(f"An error occurred in {current_function}: {e}")
        logger.warning(f"An error occurred in {current_function}: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@mcp.tool
async def check_expired_leases(ctx: Context = None) -> Dict[str, Any]:
    """
    Check for expired leases and clean them up
    
    Args:
        ctx: MCP context
        
    Returns:
        List of expired leases
    """
    try:
        lstExpired = []
        lstAllTasks = storage_manager.list_tasks()
        
        for objTask in lstAllTasks:
            if objTask.objLease and objTask.objLease.enumStatus == LeaseStatus.ACTIVE:
                if objTask.objLease.is_expired():
                    # Mark lease as expired
                    objTask.objLease.enumStatus = LeaseStatus.EXPIRED
                    objTask.enumStatus = TaskStatus.OPEN
                    objTask.strAssignee = None
                    
                    # Save updates
                    storage_manager.save_task(objTask)
                    storage_manager.save_lease(objTask.objLease)
                    
                    lstExpired.append({
                        "task_key": objTask.strKey,
                        "assignee": objTask.objLease.strAssignee,
                        "expired_at": objTask.objLease.dtLeaseExpiry.isoformat()
                    })
        
        if ctx:
            ctx.info(f"Found {len(lstExpired)} expired leases")
        
        return {
            "success": True,
            "count": len(lstExpired),
            "expired_leases": lstExpired
        }
        
    except Exception as e:
        current_function = inspect.currentframe().f_code.co_name
        print(f"An error occurred in {current_function}: {e}")
        logger.warning(f"An error occurred in {current_function}: {e}")
        return {
            "success": False,
            "error": str(e)
        }

# ========================
# MCP Resources
# ========================

@mcp.resource("task://{task_key}")
async def get_task_details(uri: str, ctx: Context = None) -> str:
    """
    Get detailed information about a specific task
    
    Args:
        uri: Task URI (e.g., "task://AEP-001")
        ctx: MCP context
        
    Returns:
        Task details in JSON format
    """
    try:
        # Extract task key from URI
        strTaskKey = uri.replace("task://", "")
        
        # Load task
        objTask = storage_manager.load_task(strTaskKey)
        if not objTask:
            return json.dumps({"error": f"Task {strTaskKey} not found"})
        
        # Return detailed information
        dictTask = storage_manager._task_to_dict(objTask)
        return json.dumps(dictTask, indent=2, default=str)
        
    except Exception as e:
        current_function = inspect.currentframe().f_code.co_name
        logger.warning(f"An error occurred in {current_function}: {e}")
        return json.dumps({"error": str(e)})

# ========================
# Main execution
# ========================

if __name__ == "__main__":
    # Run the server
    import sys
    
    # Check for initialization flag
    if len(sys.argv) > 1 and sys.argv[1] == "--init":
        print("Initializing TODO MCP Server...")
        print(f"Storage directory: {storage_manager.pathBase}")
        print(f"Git repository: {git_manager.strRepoPath}")
        print("Server initialized successfully!")
        sys.exit(0)
    
    # Run the MCP server
    print("Starting TODO Task Management MCP Server...")
    print("Available tools:")
    print("  - create_task: Create a new TODO task")
    print("  - start_work: Start work on a task (acquire lease)")
    print("  - end_work: End work on a task (release lease)")
    print("  - list_tasks: List all tasks")
    print("  - update_context: Update task context")
    print("  - search_commits: Search for lease commits")
    print("  - check_expired_leases: Check and clean expired leases")
    print("\nServer running...")
    
    # Run the server (stdio mode by default)
    mcp.run()
