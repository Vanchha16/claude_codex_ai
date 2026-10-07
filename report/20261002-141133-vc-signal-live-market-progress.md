# Claude progress: VC Signal local live market and TradingView-style chart

Task ID: 20261002-141133-vc-signal-live-market
Source prompt: `prompt/20261002-141133-vc-signal-live-market.md`
Status: progress receipt — not the final report
Updated at: 2026-10-02

## Milestones

- [x] Approval gate checked; draft SHA-256 matches. External delivery stays OFF; no real Telegram messages.
- [x] Config: .venv/.env + root .env + config/local_settings.json + process env; aliases; redaction (tested)
- [x] Persisted data source (no demo fallback); cross-process owner lock (tested with real subprocesses)
- [x] MT5: UTC epochs, account/server context, exact symbol discovery, chart timeframes (mock-tested)
- [x] Measured Bid/Ask tick outcomes; LIVE vs DEMO labels; opt-in persistence; getMe/getChat verify (mock-tested); 101 tests pass
- [x] Lightweight Charts 5.2.1 market chart + setup/Telegram UI
- [x] 102 Python + 4 JS tests, build, browser checks (demo data)
- [ ] BLOCKED: real MT5 smoke check (no terminal running; user must start Exness MT5, select symbol)
- [x] Final report published
