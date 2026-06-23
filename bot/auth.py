import logging
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from typing import Any, Callable, Awaitable

log = logging.getLogger(__name__)

_approved: set[int] = set()
_admin_id: int = 0


def init(approved_users: list[int], admin_id: int) -> None:
    global _admin_id
    _approved.update(approved_users)
    _admin_id = admin_id


def is_approved(user_id: int) -> bool:
    return user_id in _approved


def is_admin(user_id: int) -> bool:
    return user_id == _admin_id


def add_user(user_id: int) -> None:
    _approved.add(user_id)


def remove_user(user_id: int) -> None:
    _approved.discard(user_id)


def list_users() -> list[int]:
    return sorted(_approved)


class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id: int | None = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id is None or not is_approved(user_id):
            log.warning("Unauthorized access attempt from user_id=%s", user_id)
            if isinstance(event, Message):
                await event.answer("⛔ Access denied.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔ Access denied.", show_alert=True)
            return
        return await handler(event, data)
