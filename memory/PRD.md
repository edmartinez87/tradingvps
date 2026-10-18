# PRD · Bybit AI Trader (Paper Trading 24/7)

## Original problem statement
"Hola! me gustaría construir un script para que analice en tiempo real el mercado de criptomonedas, haga entradas siguiendo un plan de trading y haga el trading en automático las 24 horas, la plataforma a conectar de preferencia seria bybit, el resto de sugerencias y mejoras a tu criterio, analizando casos de éxito anteriores"

## User choices
- Paper trading with real live data (no API keys)
- USDT perpetual futures (long/short)
- AI confirmation: Claude Sonnet (claude-sonnet-5-5 via Emergent LLM key)
- Conservative risk: 1% per trade, max 3 positions, 3x, daily loss limit 5%
- Strategy: default multi-strategy

## Architecture
- Backend FastAPI (/app/backend): market.py (Bybit v5 → auto-fallback to Bitget USDT-FUTURES when geo-blocked), indicators.py (EMA/RSI/MACD/ATR/BB/ADX/Donchian), strategies.py (trend_ema, mean_reversion, breakout_turtle), risk.py (sizing, SL/TP, breakeven+trailing), ai_advisor.py (Claude), engine.py (24/7 asyncio loops: monitor 5s, scan every N sec, auto-resume on restart), backtest.py, server.py (routes).
- MongoDB collections: settings, account, positions, trades, signals, logs, equity.
- Frontend React dashboard (Spanish): header controls, KPIs, watchlist, lightweight-charts candles+EMA+RSI+markers, plan panel, positions/history/backtest tabs, AI signals log, settings, terminal log.
- QA helper: /app/scripts/inject_signal.py SYMBOL side [noai]

## Implemented (2026-06)
- Live market analysis, 3 strategies + multi-mode, HTF filter, AI approval with min confidence, paper execution with fees 0.055% + slippage, SL/TP/breakeven/trailing, daily loss pause, max positions, drawdown tracking, equity curve, backtest on 1000 real candles, reset account, logs.
- Tested: iteration_1 backend 100%, frontend 95% → minor UI fixes applied (mobile header wrap, Spanish validation, KPI grid, blocked signals stored as BLOQUEADA, risk recheck inside lock).

## Known constraints
- Bybit API blocks the US server region (CloudFront 403) → prices from Bitget perps mirror. Real Bybit order execution requires running from an allowed region.

## Backlog
- P1: Bybit Testnet/Mainnet live executor (signed v5 orders) when hosted in allowed region
- P1: Telegram notifications for entries/exits/AI decisions
- P2: Per-strategy performance stats, walk-forward/parameter optimization in backtest, AI backtest sampling
- P2: Funding-rate & news sentiment context for AI
