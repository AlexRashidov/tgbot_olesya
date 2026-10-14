# Бот «Таблетка от прокрастинации»

Telegram-бот для воронки: тест «Где именно ты застреваешь перед задачей?» → результат →
метод → пример → продукт → оплата → выдача материалов. Есть фоновая цепочка прогрева
(через 24 ч / ещё 48 ч / ещё 48 ч) и напоминание о незавершённом тесте.

Стек: Python 3.12+, [aiogram 3](https://docs.aiogram.dev/), SQLite через `aiosqlite`.

## Запуск

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # Linux/macOS: cp .env.example .env
```

Заполни `.env` (минимум `BOT_TOKEN` и `ADMIN_IDS`) и запусти:

```bash
python run.py
```

База создаётся автоматически по пути из `DATABASE_URL` (по умолчанию `data/bot.db`).

## Структура

```
run.py                  точка входа
bot/
  config.py             настройки из .env (токен, DATABASE_URL, ссылки, админы)
  constants.py          категории теста, статусы, теги, callback-данные, интервалы
  texts.py              ВСЕ тексты сообщений и кнопок — править здесь
  keyboards.py          inline-клавиатуры
  middlewares.py        регистрация пользователя в БД на каждое событие
  main.py               сборка бота, polling + фоновый планировщик
  db/
    database.py         подключение к SQLite и схема таблиц
    models.py           модель User
    repository.py       все SQL-запросы
  services/
    quiz.py             подсчёт результата теста (чистая логика)
    screens.py          готовые экраны: вопрос, результат, продукт, оплата
    scheduler.py        фоновые задачи: прогрев и напоминания
  handlers/
    start.py            /start, /test, /result, /product, /stop, /subscribe
    quiz.py             прохождение теста
    funnel.py           метод → пример → продукт → содержание / «пока подумаю»
    payment.py          «Купить», «Я оплатил(а)»
    admin.py            подтверждение оплаты, /paid, /stats
```

## Как поменять тексты

Все сообщения лежат в `bot/texts.py`. Поменяй текст и перезапусти бота.
Разметка HTML: `<b>жирный</b>`, `<i>курсив</i>`.

## Оплата

1. Пользователь жмёт «Купить за 2 500 ₽», получает кнопки оплаты (`PAYMENT_URL_RU`, `PAYMENT_URL_FOREIGN`)
   и статус `pending`. Само нажатие ещё не считается покупкой.
2. После оплаты он жмёт «Я оплатил(а)», и администраторам из `ADMIN_IDS` приходит заявка с кнопками
   «Подтвердить» / «Оплата не найдена».
3. После подтверждения пользователь получает статус `customer` и ссылку `MATERIALS_URL`,
   а продающая цепочка для него останавливается.

Подтвердить вручную можно и командой: `/paid <user_id>`. Статистика по воронке: `/stats`.

Автоматическое подтверждение через вебхук Т-Банка/Prodamus можно добавить позже. Для этого
достаточно вызвать `screens.complete_purchase(...)` из обработчика вебхука.

## Фоновые задачи

`services/scheduler.py` раз в `SCHEDULER_TICK_SECONDS` проверяет базу:

- прогрев 1/2/3 — только тем, кто прошёл тест, не купил и не отписался (`/stop`);
  после третьего сообщения цепочка заканчивается;
- одно напоминание через 24 ч, если тест начат и не закончен.

Состояние хранится в SQLite, поэтому после перезапуска отправки продолжаются с того же места.
Для быстрой проверки поставь в `.env` значения `DELAY_SCALE=0.0007` и `SCHEDULER_TICK_SECONDS=10`:
интервалы сожмутся примерно до 1 / 2 / 2 минут.

## Данные пользователя

Таблица `users` содержит поля из ТЗ: `test_started`, `test_completed`, `answer_1..4`, `score_*`,
`test_result`, `product_interest`, `purchase_status`, `sales_stage`, `followup_status`.
Таблица `user_tags` хранит теги `test_started`, `result_*`, `product_viewed`, `purchase_clicked`,
`payment_pending`, `customer`, `followup_opt_out`.
Источник перехода сохраняется из ссылки вида `t.me/<бот>?start=reels`.
