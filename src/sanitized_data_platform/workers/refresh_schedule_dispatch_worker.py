from __future__ import annotations

from sanitized_data_platform.application.services import RefreshScheduleDispatchService


class RefreshScheduleDispatchWorker:
    def __init__(self, dispatch: RefreshScheduleDispatchService) -> None:
        self._dispatch = dispatch

    def dispatch_due_schedules(self):
        return self._dispatch.dispatch_due_schedules()
