from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core.filters import Filters
from scraper.models import Listing


def listing_notification_keyboard(listing: Listing) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="🔗 Открыть объявление", url=listing.url)],
        [
            InlineKeyboardButton(text="🚫 Заблокировать автора", callback_data=f"block:{listing.id}"),
            InlineKeyboardButton(text="⏸ Пауза 1 час", callback_data="pause:60"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def filters_menu_keyboard(filters: Filters) -> InlineKeyboardMarkup:
    """Быстрые переключатели поверх текстовых команд /set, /district, /rooms."""
    photo_label = "📷 Только с фото: вкл" if filters.only_with_photo else "📷 Только с фото: выкл"
    promoted_label = "🚫 VIP/ТОП скрыты" if filters.skip_promoted else "✅ VIP/ТОП показываются"
    buttons = [
        [InlineKeyboardButton(text=photo_label, callback_data="toggle:only_with_photo")],
        [InlineKeyboardButton(text=promoted_label, callback_data="toggle:skip_promoted")],
        [InlineKeyboardButton(text="🗑 Очистить районы", callback_data="clear_districts")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_filters")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
