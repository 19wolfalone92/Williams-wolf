# Williams Bot 4.5.1 — build status

- Python compileall: PASS
- Recovery tests: 5/5 PASS
- FastAPI health/auth smoke: PASS
- Binance real-order execution: NOT RUN (no credentials)
- Android APK: project prepared; local environment has no Android SDK/Gradle distribution, so APK binary could not be produced here.
- Default mode: Binance Spot Testnet; live trading remains disabled unless explicitly enabled by server configuration.

## Safety improvements
- Bot-owned order/client-ID reconciliation
- Pre-existing wallet assets are not treated as bot positions
- Closed bot trades cannot be resurrected by unrelated wallet balances
- Missing OCO is recreated only for an identified open bot trade
- Balance mismatch enters reconcile-required state
- Stop waits briefly for the old trading thread to exit before credentials can be replaced
- Mobile credentials can be cleared through authenticated API and Android UI
- Android WebSocket reconnect uses bounded exponential backoff and handles onClosed/onFailure
