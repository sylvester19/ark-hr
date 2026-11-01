"""One visible queue message keeps the container awake while a batch is running."""

from __future__ import annotations


class ScaleQueue:
    def __init__(self, connection_string: str, name: str) -> None:
        from azure.storage.queue import QueueClient

        self._queue = QueueClient.from_connection_string(connection_string, name)
        try:
            self._queue.create_queue()
        except Exception:
            pass

    def hold(self) -> None:
        if any(True for _ in self._queue.peek_messages(max_messages=1)):
            return
        self._queue.send_message("batch")

    def release(self) -> None:
        messages = self._queue.receive_messages(messages_per_page=16, visibility_timeout=5)
        for message in messages:
            self._queue.delete_message(message.id, message.pop_receipt)
