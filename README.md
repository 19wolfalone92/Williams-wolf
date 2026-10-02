# Williams Binance Bot + Android Dashboard 4.5

Исправленная рабочая версия проекта из публичного репозитория `19wolfalone92/Williams`.

## Что исправлено

- Исправлена структура Android Gradle-проекта: теперь есть нормальный `app/src/main/...` и `app/build.gradle.kts`.
- `run_server.py` больше не импортирует несуществующий `api.server`.
- Backtester и загрузка исторических свечей приведены к совместимой сигнатуре.
- Recovery больше не считает произвольный BTC на аккаунте позицией бота.
- Entry orders получают уникальный `WILLV4_ENTRY_*` clientOrderId для безопасного восстановления.
- `last_signal_candle` не записывается до успешного BUY: временная ошибка API не теряет сигнал.
- При ошибке OCO заполненный BUY не уничтожается массовым `cancel_open_orders`; следующий recovery пытается восстановить защиту.
- Android WebSocket получил автоматический reconnect с exponential backoff.
- Backend WebSocket корректно обрабатывает `eventStreamTerminated` и переподключение user stream.
- Binance API keys можно ввести в Android Settings; на телефоне они хранятся через AndroidX Security/Keystore-backed encrypted storage. На сервере ключи держатся в памяти, если переданы из приложения.
- По умолчанию сохраняется `TESTNET=true`; LIVE требует явного `ALLOW_LIVE=true`.
- Добавлен health/status API и runtime-конфигурация Binance credentials.

## Безопасность

Не вставляйте реальные ключи в Git. Для первого запуска используйте Binance Spot Testnet. Для LIVE обязательно HTTPS/WSS и отдельный длинный `MOBILE_API_TOKEN` (минимум 32 символа). Сервер теперь отказывает в работе API, если токен не настроен. HTTP для Android отключён в release manifest; локальный Testnet лучше подключать через HTTPS даже в домашней сети.

## Запуск backend

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python recovery_test.py
python run_server.py
```

Windows activation: `.venv\\Scripts\\activate`.

## Android

Открыть корень проекта в Android Studio. Backend URL задаётся в приложении. В Settings вводятся Mobile API token и Binance Testnet API Key/Secret. После сохранения приложение вызывает `/api/v1/config/binance`.

### Важно

Текущая среда выполнения не содержит Android SDK/Gradle distribution, поэтому здесь выполнены статические проверки Python и recovery/backtester, но финальный APK в этой среде не собирался. Проект подготовлен для сборки Android Studio.

## Binance WebSocket

Проект использует современный Spot user-data flow: `POST /sapi/v1/userListenToken` + `userDataStream.subscribe.listenToken`. Binance указывает срок действия listen token до 24 часов и событие `eventStreamTerminated` при окончании подписки; backend создаёт новый token и переподключается. См. официальную документацию Binance.


## 4.5 improvements

- Recovery reconciles bot-owned orders by client IDs instead of trusting arbitrary asset balances or unrelated OCO lists.
- A closed historical bot trade cannot be resurrected by later unrelated BTC deposits.
- Balance discrepancies enter `RECONCILE_REQUIRED` instead of creating potentially unsafe TP/SL orders.
- SQLite uses WAL + busy timeout for better crash/restart behavior.
- API authentication refuses missing/weak `MOBILE_API_TOKEN`.
- Android automatically re-sends saved Binance credentials to the backend after restart.
- Release Android builds disable cleartext HTTP; debug builds may use local HTTP for Testnet/LAN development.
- START is disabled in the app until Binance credentials are configured.
