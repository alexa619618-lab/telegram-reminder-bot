from .message_handler import router as message_router
from .callback_handler import router as callback_router
from .inline_handler import router as inline_router

__all__ = ["message_router", "callback_router", "inline_router"]
