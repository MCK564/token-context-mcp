"""High-performance in-memory access control, rate limiting, and permission revocation."""
from __future__ import annotations

import collections
import enum
import time
from typing import Any


class AgentState(str, enum.Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"


class PolicyProfile(str, enum.Enum):
    FULL_ACCESS = "FULL_ACCESS"
    READ_ONLY = "READ_ONLY"
    CUSTOM = "CUSTOM"


READ_ONLY_TOOLS: frozenset[str] = frozenset({
    "list_repositories",
    "get_repo_map",
    "find_symbols",
    "get_module_dependents",
    "search_source",
    "get_file_skeleton",
    "get_symbol_context",
    "get_impact_slice",
    "get_index_status",
    "inspect_symbol",
    "list_available_tools",
    "search_tools",
    "get_tool_schema",
    "memory_get",
    "memory_search",
})

WRITE_OR_MUTATING_TOOLS: frozenset[str] = frozenset({
    "memory_put",
    "memory_lock",
    "sample_summarize",
})


class AccessControlManager:
    """Zero-overhead in-memory Access Control Plane for Multi-Agent coordination.

    Features:
    - O(1) Fast-Path checking in < 0.02ms (pure in-memory dictionary lookup).
    - Dynamic permission revocation: Pause, Block, or Resume individual agents.
    - Global Emergency Kill-Switch (Panic Button) for immediate operational halt.
    - Sliding-window rate limiter per agent to prevent runaway loops.
    """

    def __init__(
        self,
        default_policy: PolicyProfile = PolicyProfile.FULL_ACCESS,
        max_calls_per_minute: int = 120,
    ) -> None:
        self.default_policy = default_policy
        self.max_calls_per_minute = max_calls_per_minute

        self._states: dict[str, AgentState] = {}
        self._policies: dict[str, PolicyProfile] = {}
        self._custom_allowed_tools: dict[str, set[str]] = {}
        self._reasons: dict[str, str] = {}
        self._agent_metadata: dict[str, dict[str, Any]] = {}

        # Sliding window rate limiting: agent_id -> deque of timestamps
        self._call_history: dict[str, collections.deque[float]] = collections.defaultdict(collections.deque)

        # Global emergency stop
        self._emergency_halt: bool = False
        self._emergency_reason: str = ""

    @property
    def is_emergency_halted(self) -> bool:
        return self._emergency_halt

    @property
    def emergency_reason(self) -> str:
        return self._emergency_reason

    def emergency_halt(self, reason: str = "Administrator triggered emergency stop") -> None:
        """Immediately block all tool execution across all agents."""
        self._emergency_halt = True
        self._emergency_reason = reason

    def emergency_resume(self) -> None:
        """Clear global emergency halt."""
        self._emergency_halt = False
        self._emergency_reason = ""

    def register_agent(
        self,
        agent_id: str,
        role: str = "agent",
        policy: PolicyProfile | None = None,
        custom_tools: set[str] | None = None,
    ) -> None:
        """Register or update agent metadata and policy."""
        if not agent_id:
            return
        if agent_id not in self._states:
            self._states[agent_id] = AgentState.ACTIVE
        self._policies[agent_id] = policy or self.default_policy
        if custom_tools is not None:
            self._custom_allowed_tools[agent_id] = set(custom_tools)
        self._agent_metadata[agent_id] = {
            "role": role,
            "registered_at": time.time(),
            "last_active": time.time(),
            "call_count": 0,
        }

    def pause_agent(self, agent_id: str, reason: str = "Paused by administrator") -> None:
        """Temporarily suspend an agent's tool execution."""
        self._states[agent_id] = AgentState.PAUSED
        self._reasons[agent_id] = reason

    def resume_agent(self, agent_id: str) -> None:
        """Restore an agent to ACTIVE state."""
        self._states[agent_id] = AgentState.ACTIVE
        self._reasons.pop(agent_id, None)

    def block_agent(self, agent_id: str, reason: str = "Blocked by administrator") -> None:
        """Permanently block an agent from accessing tools."""
        self._states[agent_id] = AgentState.BLOCKED
        self._reasons[agent_id] = reason

    def unblock_agent(self, agent_id: str) -> None:
        """Unblock an agent, restoring to ACTIVE state."""
        self._states[agent_id] = AgentState.ACTIVE
        self._reasons.pop(agent_id, None)

    def set_agent_policy(
        self,
        agent_id: str,
        policy: PolicyProfile,
        custom_tools: set[str] | None = None,
    ) -> None:
        """Assign an access policy to a specific agent."""
        self._policies[agent_id] = policy
        if custom_tools is not None:
            self._custom_allowed_tools[agent_id] = set(custom_tools)

    def get_agent_state(self, agent_id: str) -> AgentState:
        return self._states.get(agent_id, AgentState.ACTIVE)

    def get_agent_policy(self, agent_id: str) -> PolicyProfile:
        return self._policies.get(agent_id, self.default_policy)

    def check_access(self, tool_name: str, agent_id: str | None = None) -> tuple[bool, str | None]:
        """Fast-Path access check. Completes in < 0.02ms.

        Returns (allowed: bool, rejection_reason: str | None).
        """
        # 1. Global emergency kill-switch check
        if self._emergency_halt:
            return False, f"HALT_BY_USER: Global emergency stop is active. Reason: {self._emergency_reason}"

        if not agent_id:
            # Anonymous or general tool call without explicit agent_id is permitted by default
            return True, None

        # 2. Check Agent State
        state = self._states.get(agent_id, AgentState.ACTIVE)
        if state == AgentState.PAUSED:
            reason = self._reasons.get(agent_id, "Execution paused by administrator via GUI.")
            return False, f"HALT_BY_USER: Agent '{agent_id}' is PAUSED. {reason}"
        if state == AgentState.BLOCKED:
            reason = self._reasons.get(agent_id, "Access permanently revoked.")
            return False, f"ACCESS_DENIED: Agent '{agent_id}' is BLOCKED. {reason}"

        # 3. Check Policy
        policy = self._policies.get(agent_id, self.default_policy)
        if policy == PolicyProfile.READ_ONLY and tool_name not in READ_ONLY_TOOLS:
            return False, f"POLICY_VIOLATION: Tool '{tool_name}' is not permitted under READ_ONLY policy for agent '{agent_id}'."

        if policy == PolicyProfile.CUSTOM:
            allowed = self._custom_allowed_tools.get(agent_id, set())
            if tool_name not in allowed:
                return False, f"POLICY_VIOLATION: Tool '{tool_name}' is not in custom permitted list for agent '{agent_id}'."

        # 4. Sliding-window rate limiter
        now = time.time()
        history = self._call_history[agent_id]
        one_min_ago = now - 60.0
        while history and history[0] < one_min_ago:
            history.popleft()

        if len(history) >= self.max_calls_per_minute:
            return False, f"RATE_LIMITED: Agent '{agent_id}' exceeded limit of {self.max_calls_per_minute} calls/min."

        history.append(now)

        # Update metadata telemetry
        if agent_id in self._agent_metadata:
            self._agent_metadata[agent_id]["last_active"] = now
            self._agent_metadata[agent_id]["call_count"] += 1
        else:
            self._agent_metadata[agent_id] = {
                "role": "external_agent",
                "registered_at": now,
                "last_active": now,
                "call_count": 1,
            }

        return True, None

    def list_agents(self) -> list[dict[str, Any]]:
        """List all tracked agents with their live status and telemetry."""
        result = []
        for agent_id, meta in list(self._agent_metadata.items()):
            state = self._states.get(agent_id, AgentState.ACTIVE)
            policy = self._policies.get(agent_id, self.default_policy)
            result.append({
                "agent_id": agent_id,
                "role": meta.get("role", "agent"),
                "state": state.value,
                "policy": policy.value,
                "call_count": meta.get("call_count", 0),
                "last_active": meta.get("last_active", 0.0),
                "reason": self._reasons.get(agent_id, ""),
            })
        return result
