"""
Two-Phase Confirmation Engine (PRD Section 14 & 15).
Manages pending configuration actions, timeouts, approval tokens, and execution callbacks.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional
from config.settings import settings
from mikrotik.base import OperationResult

logger = logging.getLogger(__name__)


@dataclass
class PendingAction:
    token: str
    user_id: int
    device_name: str
    action_name: str
    arguments: Dict[str, Any]
    description: str
    created_at: float = field(default_factory=time.time)
    timeout_seconds: int = 300
    callback: Optional[Callable[[], OperationResult]] = None

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.timeout_seconds

    @property
    def time_remaining_seconds(self) -> int:
        remaining = int(self.timeout_seconds - (time.time() - self.created_at))
        return max(0, remaining)


class ConfirmationManager:
    def __init__(self):
        # Map token -> PendingAction
        self._pending_by_token: Dict[str, PendingAction] = {}
        # Map user_id -> token (one active confirmation per user)
        self._user_active_token: Dict[int, str] = {}

    def create_pending_action(
        self,
        user_id: int,
        device_name: str,
        action_name: str,
        arguments: Dict[str, Any],
        description: str,
        callback: Optional[Callable[[], OperationResult]] = None,
    ) -> PendingAction:
        """Register a new action that requires user confirmation."""
        # Clean up any existing action for this user
        if user_id in self._user_active_token:
            old_token = self._user_active_token[user_id]
            self._pending_by_token.pop(old_token, None)

        token = f"conf_{uuid.uuid4().hex[:8]}"
        action = PendingAction(
            token=token,
            user_id=user_id,
            device_name=device_name,
            action_name=action_name,
            arguments=arguments,
            description=description,
            timeout_seconds=settings.confirmation_timeout_seconds,
            callback=callback,
        )

        self._pending_by_token[token] = action
        self._user_active_token[user_id] = token
        return action

    def get_pending_for_user(self, user_id: int) -> Optional[PendingAction]:
        """Retrieve active pending action for a user."""
        token = self._user_active_token.get(user_id)
        if not token:
            return None
        action = self._pending_by_token.get(token)
        if not action:
            self._user_active_token.pop(user_id, None)
            return None
        if action.is_expired:
            self.cancel_action(token)
            return None
        return action

    def get_action_by_token(self, token: str) -> Optional[PendingAction]:
        action = self._pending_by_token.get(token)
        if action and action.is_expired:
            self.cancel_action(token)
            return None
        return action

    def execute_action(self, token: str) -> OperationResult:
        """Approve and execute the pending action."""
        action = self.get_action_by_token(token)
        if not action:
            return OperationResult(
                success=False,
                message="Aksi konfirmasi tidak ditemukan atau telah kedaluwarsa (expired).",
            )

        try:
            if action.callback:
                result = action.callback()
            else:
                # Fallback to direct tool call
                from mikrotik.tools import TOOL_REGISTRY
                tool_func = TOOL_REGISTRY.get(action.action_name)
                if not tool_func:
                    return OperationResult(success=False, message=f"Tool '{action.action_name}' tidak ditemukan.")
                
                import inspect
                sig = inspect.signature(tool_func)
                has_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
                if has_kwargs:
                    exec_args = action.arguments
                else:
                    exec_args = {k: v for k, v in action.arguments.items() if k in sig.parameters}

                try:
                    raw_res = tool_func(**exec_args)
                    msg = raw_res.get("message") or (f"✅ Aksi '{action.action_name}' berhasil dieksekusi." if raw_res.get("success") else f"❌ Gagal: {raw_res.get('error', 'Terjadi kesalahan.')}")
                    result = OperationResult(
                        success=raw_res.get("success", False),
                        message=msg,
                        data=raw_res.get("data"),
                        error=raw_res.get("error"),
                        device=action.device_name,
                    )
                except Exception as ex:
                    logger.exception("Error executing action '%s': %s", action.action_name, ex)
                    result = OperationResult(
                        success=False,
                        message=f"❌ Gagal mengeksekusi '{action.action_name}': {str(ex)}",
                        error=str(ex),
                        device=action.device_name,
                    )
            return result
        finally:
            self.cancel_action(token)

    def cancel_action(self, token: str) -> bool:
        """Cancel and remove a pending action."""
        action = self._pending_by_token.pop(token, None)
        if action and action.user_id in self._user_active_token:
            if self._user_active_token[action.user_id] == token:
                self._user_active_token.pop(action.user_id, None)
        return action is not None


confirmation_manager = ConfirmationManager()
