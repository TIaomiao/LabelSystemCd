from __future__ import annotations

from typing import Any


def recover_interrupted_feedback_investigations(connection: Any) -> int:
    """Fail closed for read-only investigations whose supervising web process ended."""
    result = connection.exec_driver_sql(
        """
        UPDATE feedback_codex_run
        SET status = 'failed',
            phase = 'interrupted_by_restart',
            error_message = '服务重启中断了只读 Codex 调查；已保留调查产物，请人工重新发起。',
            finished_at = COALESCE(finished_at, CURRENT_TIMESTAMP),
            updated_at = CURRENT_TIMESTAMP
        WHERE status IN ('pending', 'running')
          AND phase = 'investigation'
        """
    )
    return max(0, int(result.rowcount or 0))
