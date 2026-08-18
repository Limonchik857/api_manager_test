"""Сигнал повторной попытки для узлов (Phase 4)."""


class RetrySignal(Exception):
    """Узел сообщает о временной ошибке, которую можно повторить.

    Executor решает: запланировать retry через Celery (countdown с
    экспоненциальным backoff) или зафиксировать ошибку.
    """

    def __init__(self, message='Временная ошибка, повторим позже'):
        super().__init__(message)
        self.message = message