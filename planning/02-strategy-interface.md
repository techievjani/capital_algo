# Strategy Interface

## Objective

Allow strategy swapping without changing the engine, broker, risk manager, or reporting.

## Strategy Contract

Every strategy must implement the same lifecycle.

```text
initialize(strategy_config, context)
on_session_start(context)
on_bar(bar, context) -> list[Signal]
on_tick(tick, context) -> list[Signal]
on_order_update(order_update, context)
on_position_update(position_update, context)
on_session_end(context)
```

Only `initialize` and `on_bar` are required for the first ORB backtest version. The other methods exist so live trading can be added cleanly later.

## Signal Contract

Strategies emit signals, not orders.

```json
{
  "strategy_id": "orb_v1",
  "instrument": "US100",
  "action": "BUY",
  "entry_type": "MARKET",
  "reason": "breakout_above_opening_range",
  "stop_loss": 17420.5,
  "take_profit": 17580.0,
  "metadata": {
    "opening_range_high": 17480.2,
    "opening_range_low": 17420.5
  }
}
```

## Strategy Loader

The engine should load strategy by config:

```json
{
  "active_strategy": "orb",
  "strategy_config": "config/strategies/orb.json"
}
```

Swapping strategy should mean changing config only:

```json
{
  "active_strategy": "vwap",
  "strategy_config": "config/strategies/vwap.json"
}
```

## Strategy Context

The context object provides read-only access to shared runtime information:

- current timestamp
- trading session metadata
- instrument metadata
- current portfolio snapshot
- open positions
- recent bars
- config values
- mode: `backtest`, `demo`, or `live`

Strategies may read context but should not mutate account, order, or broker state directly.

## ORB Strategy Requirements

The ORB strategy should be implemented as one plugin-style strategy:

- build opening range after configured session start
- track range high and low
- emit long breakout signal above range high
- emit short breakout signal below range low
- optionally allow long-only, short-only, or both
- optionally limit trades per session
- optionally close positions at session end

## Future Strategies

Future strategies should plug into the same contract:

- VWAP mean reversion
- moving average crossover
- momentum breakout
- RSI reversal
- multi-timeframe trend following

