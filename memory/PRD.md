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
- MongoDB collections: settings, account, positions, trades, signals, logs, equity, config (clave, IA, Telegram, revisión automática).
- Frontend React dashboard (Spanish): header controls, KPIs, watchlist, lightweight-charts candles+EMA+RSI+markers, plan panel, positions/history/backtest tabs, AI signals log, settings, terminal log.
- QA helper: /app/scripts/inject_signal.py SYMBOL side [noai]

## Implemented (2026-06)
- Live market analysis, 3 strategies + multi-mode, HTF filter, AI approval with min confidence, paper execution with fees 0.055% + slippage, SL/TP/breakeven/trailing, daily loss pause, max positions, drawdown tracking, equity curve, backtest on 1000 real candles, reset account, logs.
- Tested: iteration_1 backend 100%, frontend 95% → minor UI fixes applied (mobile header wrap, Spanish validation, KPI grid, blocked signals stored as BLOQUEADA, risk recheck inside lock).

## Implemented (2026-06, iteration 2 · "plan de crecimiento")
- Paper account initial balance set to $500 (engine.INITIAL_BALANCE); POST /api/account/reset accepts optional {initial_balance}.
- Bybit lot-size enforcement (risk.LOT_SIZES, qty step floor, MIN_NOTIONAL 5 USDT) in live sizing and backtest; backtest now uses account initial balance + symbol, returns expectancy_r / rejected_lot / strategy_stats.
- GET /api/performance: live trade stats by strategy/symbol/side/reason + AI decision counts → "Rendimiento" tab.
- POST /api/plan (plan.py): compound growth plan with phases (semilla → crecimiento → consolidación → ingreso, risk 1% → 1.5%, 100% reinvest until target capital, then withdraw 80%), 4 scenarios (2.5% / 4% / 6% / backtest-derived Monte Carlo median), months to reach target monthly income, Monte Carlo (3000 sims × 12 months) on backtest R-multiples with concurrency factor, per-symbol & per-strategy backtest breakdown → "Plan de crecimiento" tab (GrowthPlan + plan/*.jsx).
- Result for $500 → $1.000/mes with 0 deposits: conservador 12a2m, base 7a, optimista 4a4m, backtest(2.3%/mes) 13a4m. Monthly deposits shorten it drastically.
- Tested: iteration_2 backend 15/15 (one numpy int64 serialization bug fixed by tester), frontend all flows pass.

## Implemented (2026-06, iteration 3 · optimizador + chequeo del plan + IA)
- optimizer.py: 54-combo grid (SL 1–3×ATR, TP 2–6×ATR with R:R≥1.5, ATR 10/14/20) per pair, robust pick = Van Tharp SQN averaged over 3×3 grid neighbours; backtest.py refactored into scan_signals()+simulate() (signals independent of SL/TP → fast); strategies accept params {sl_atr,tp_atr}; build_df(atr_period). Settings.symbol_params[symbol] applied by the live engine, plan backtests and /backtest. UI tab "Optimizador" (compare baseline vs optimum, heatmap, apply/remove, multi-pair summary).
- Plan check-in (plan.build_checkin + engine.checkin): phase criteria evaluated on real paper stats (validación: ≥60 ops, PF≥1.3, DD≤10%, ≥28 días; semilla: 2× capital, DD<12%; crecimiento: $5k, PF≥1.3, ≥100 ops; consolidación: capital objetivo; ingreso: ganancia 30d ≥ meta, DD≤15%). Settings persist plan_scenario/plan_target_monthly/plan_monthly_deposit/plan_phase; "Avanzar a fase" button sets plan_phase + phase risk; alert dot on Plan tab; daily PLAN log at UTC rollover; `checkin` included in /dashboard.
- AI buttons (POST /api/ai/advise scope optimizer|plan): Claude receives settings, account, real performance, check-in and optimizer/backtest results, returns JSON {summary, changes, notes}; backend applies whitelisted changes with caps (risk≤1.5%, lev≤5, max_pos≤5, ≥2 symbols) and returns applied/previous → UI AiAdvice component with "Deshacer".
- Tested: iteration_3 backend 18/18, frontend all flows pass; 2 minor state bugs fixed (heatmap ATR reset per pair, applied state derived from settings).

## Implemented (2026-06, iteration 4 · acceso, ajustes, Telegram, revisión automática)
- Auth: single shared password (no username), bcrypt hash in Mongo `config` doc seeded from INITIAL_PASSWORD env (BlackCat2233@), JWT HS256 (JWT_SECRET env, 7 días) con token_version para invalidar sesiones al cambiar clave; brute force 5 intentos/IP → 15 min (IP = último X-Forwarded-For) + contador global (20). Routers: public (/api/, /api/auth/login), api (protegido), cron (/api/cron/*, Bearer WEBHOOK_CRON_SECRET). Frontend: Login.jsx, token en localStorage, interceptores axios, evento auth:logout.
- Ajustes (vista completa desde el header): Seguridad (cambio de clave), IA (proveedor/modelo/API key propia o clave Emergent, probar conexión), Telegram (token, detectar chat ID vía getUpdates, toggles por tipo de alerta, prueba), Revisión IA automática (activa, diaria/semanal + día, aplicar o solo avisar, ejecutar ahora, última revisión), Cuenta paper (reiniciar con capital personalizado). Backend: config.py (ConfigStore, secretos enmascarados), notify.py (Telegram HTML), review.py (contexto IA compartido, apply_ai_changes, run_auto_review).
- Telegram hooks en engine: apertura/cierre, límite diario, decisiones de Claude, resumen diario + plan (00:00 UTC), resultado/errores de revisión automática.
- Cron `.emergent/crons.yml` ai-review-daily (08:00 UTC) → POST /api/cron/ai-review decide si toca (frecuencia/día, >20h desde la última) y lanza la revisión en background con manejo de errores.
- Prompt del asesor endurecido: cambios estructurales (pares/estrategia/riesgo) solo con ≥30 operaciones reales; backtest/optimizador solo justifican symbol_params.
- Tested: iteration_4 backend 28/29 (fallo del 502 por ingress → ahora 424), frontend completo OK; fixes: XFF spoof, merge de alertas, task de cron con try/except.

## Known constraints
- Bybit API blocks the US server region (CloudFront 403) → prices from Bitget perps mirror. Real Bybit order execution requires running from an allowed region.

## Backlog
- P1: Bybit Testnet/Mainnet live executor (signed v5 orders) when hosted in allowed region
- P1: Telegram notifications for entries/exits/AI decisions
- P1: One-click disable of a losing pair/strategy from the Rendimiento tab
- P2: Walk-forward validation of optimizer params (in-sample/out-of-sample), AI backtest sampling
- P2: Funding-rate & news sentiment context for AI
