# Risk Management

## Objective

Make risk controls strategy-independent and impossible for a strategy to bypass.

## Risk Pipeline

```text
Signal
  -> Risk validation
  -> Position sizing
  -> Order validation
  -> Execution
```

## Global Controls

Minimum first version:

- max risk per trade
- max trades per day
- max open positions
- max daily loss
- long/short permissions
- instrument enable/disable
- live-trading kill switch

## Signal Validation

A signal may be rejected if:

- instrument is disabled
- live trading is not explicitly allowed
- max trades for the day/session is reached
- daily loss limit is reached
- existing exposure conflicts with the signal
- stop loss is missing or invalid
- calculated position size is invalid
- market is outside configured trading session

Rejected signals should be recorded with a reason.

## Position Sizing

Position sizing should be based on account risk, stop distance, and instrument constraints.

The strategy may suggest stop loss and take profit, but it should not decide final size.

## Live Safety

Live mode should include:

- explicit `allow_live_trading: true`
- environment confirmation
- maximum order size cap
- max daily loss kill switch
- duplicate order protection
- cooldown after repeated failures

