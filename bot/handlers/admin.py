"""Команды администратора: ручное подтверждение оплаты и статистика."""

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, Filter
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot import texts
from bot.config import Settings
from bot.constants import Cb
from bot.db import UserRepository
from bot.services import screens

router = Router(name="admin")


class IsAdmin(Filter):
    async def __call__(self, event: TelegramObject, settings: Settings) -> bool:
        user = getattr(event, "from_user", None)
        return user is not None and user.id in settings.admin_ids


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


async def _confirm(user_id: int, repo: UserRepository, settings: Settings, bot: Bot) -> str:
    user = await repo.get(user_id)
    if user is None:
        return texts.ADMIN_USER_NOT_FOUND.format(user_id=user_id)
    if user.is_customer:
        return texts.ADMIN_ALREADY_CUSTOMER.format(user_id=user_id)
    await screens.complete_purchase(bot, repo, settings, user_id)
    return texts.ADMIN_CONFIRMED.format(user_id=user_id)


@router.message(Command("paid"))
async def cmd_paid(message: Message, command: CommandObject, repo: UserRepository, settings: Settings,
                   bot: Bot) -> None:
    if not command.args or not command.args.strip().isdigit():
        await message.answer(texts.ADMIN_PAID_USAGE)
        return
    await message.answer(await _confirm(int(command.args.strip()), repo, settings, bot))


@router.message(Command("stats"))
async def cmd_stats(message: Message, repo: UserRepository) -> None:
    await message.answer(texts.ADMIN_STATS.format(**await repo.stats()))


@router.callback_query(F.data.startswith(f"{Cb.ADMIN_CONFIRM_PREFIX}:"))
async def confirm_payment(callback: CallbackQuery, repo: UserRepository, settings: Settings, bot: Bot) -> None:
    user_id = int(callback.data.rsplit(":", 1)[1])
    result = await _confirm(user_id, repo, settings, bot)
    await callback.answer()
    await callback.message.edit_text(f"{callback.message.html_text}\n\n{result}")


@router.callback_query(F.data.startswith(f"{Cb.ADMIN_REJECT_PREFIX}:"))
async def reject_payment(callback: CallbackQuery, repo: UserRepository, bot: Bot) -> None:
    user_id = int(callback.data.rsplit(":", 1)[1])
    await repo.reset_payment(user_id)
    await bot.send_message(user_id, texts.PAYMENT_REJECTED)
    await callback.answer()
    await callback.message.edit_text(
        f"{callback.message.html_text}\n\n{texts.ADMIN_REJECTED.format(user_id=user_id)}"
    )
