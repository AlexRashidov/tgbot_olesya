"""/start, команды пользователя и подписка на сообщения."""

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from bot import keyboards, texts
from bot.db import User, UserRepository
from bot.services import screens

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, user: User, repo: UserRepository, bot: Bot) -> None:
    # Метка источника из ссылки вида t.me/<bot>?start=reels
    if command.args:
        await repo.upsert(user.user_id, user.username, user.first_name, source=command.args[:64])

    if user.quiz_in_progress:
        await message.answer(texts.START_TEST_IN_PROGRESS, reply_markup=keyboards.continue_quiz())
        return
    await screens.send_start(bot, message.chat.id)


@router.message(Command("test"))
async def cmd_test(message: Message, bot: Bot) -> None:
    await screens.send_start(bot, message.chat.id)


@router.message(Command("result"))
async def cmd_result(message: Message, user: User, bot: Bot) -> None:
    await screens.send_result(bot, message.chat.id, user)


@router.message(Command("product"))
async def cmd_product(message: Message, repo: UserRepository, bot: Bot) -> None:
    await screens.send_product(bot, repo, message.chat.id)


@router.message(Command("stop"))
async def cmd_stop(message: Message, user: User, repo: UserRepository) -> None:
    await repo.set_followup_allowed(user.user_id, False)
    await message.answer(texts.OPT_OUT)


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message, user: User, repo: UserRepository) -> None:
    await repo.set_followup_allowed(user.user_id, True)
    await message.answer(texts.OPT_IN)
