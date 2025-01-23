Below is a list of areas in the current “implementation_plan.md” that could use more clarity or explicit detail, based on the requirements and details from “instructions.md” and “cursor-further-questions.md”:

1. Partial vs. Full Fills
 - The plan references general order tracking but does not clarify whether partial fills are handled or whether the system ignores them and requires orders to fill entirely.
- The user specifically wants to “sell the same amount that was bought,” implying no partial selling. How do we handle a Binance order that gets partially filled?

2. Indefinite Hold (No Stop-Loss)
 - The plan states “No stop-loss needed as using SPOT orders without leverage,” but it does not explicitly confirm that the system will hold onto a position indefinitely until it can meet the profit threshold.
 - Clarify whether the system should ever cancel unprofitable BUY–SELL pairs if they remain open for a long time.

3. Exact Fee Incorporation
 - The plan mentions a 0.1% buy fee and 0.1% sell fee (0.2% total), and a 0.3% minimum profit. However, from “cursor-further-questions.md,” the user wants at least 0.3% net “after fees.”
 - Confirm precisely how the profit calculator will add up fees vs. the “MIN_PROFIT_PERCENTAGE=0.3.” (i.e., is the code using 0.3% + 0.2% = 0.5% total, or some other method that ensures 0.3% net profit remains after subtracting fees?)

4. Single-Trade Volume vs. Maximum Caps
 - The plan’s environment variable “MAX_SELL_VALUE_USDC=100” is consistent with the user’s request, but the user also mentioned that each BUY order would be about 10 USDC.
 - Clarify whether 10 USDC is just an example, or if it should be enforced in code as the default (with 100 USDC as a strict maximum).

5. Handling Multiple or Consecutive BUY Orders
 - The plan references “Multiple BUY orders consolidation” under the State Manager, but the user’s clarifications mostly describe a single BUY → single SELL flow.
 - If the code truly supports multiple pending BUYs, clarify how that logic should consolidate them or track separate trades.

6. Real-Time Order Fill Updates
 - The plan includes a “Price Manager” for WebSocket-based price updates, but it does not specify whether there is a user-data WebSocket or alternative approach for real-time fill notifications.
 - The user’s notes mention the importance of not placing a SELL until the BUY is confirmed. Should the system monitor order fills using Binance’s user-data stream, or poll with REST?

7. Exponential Backoff and 15-Minute Timeout
 - The plan does mention “exponential backoff” and “15-minute timeout” for WebSocket reconnection, but it would help to spell out in detail whether the system does a graceful shutdown at 15 minutes or attempts indefinite retries.
 - The user specifically wants the script to “stop after 15 minutes of unsuccessful WebSocket reconnection attempts”—the plan might clarify how that is implemented (e.g., exit the program or switch to REST-API-only mode).

8. State Persistence on Shutdown
 - The plan references “System state persistence” but does not explicitly confirm that on restart the system will reconcile all previously open BUY or SELL orders with the Binance API.
 - The user wants to ensure no redundant BUYs get placed if there is already an active BUY on the exchange. Clarify if the plan includes a reconciliation step at startup.

9. No Stop-Loss Means Potentially Infinite Wait
 - Because the user does not want to sell at a loss, the plan should confirm that the system will not attempt to close trades below the BUY price (apart from error-handling or forced manual override).
 - This condition could lead to indefinite open positions, which should be stated so it’s clear there is no forced liquidation.

10. Logging & Rotation Details
 - The plan mentions a logging configuration in “4.2,” but the user also wants 100 MB file-size rotation.
 - Clarify how the plan implements log rotation—are we relying on Python’s built-in RotatingFileHandler or a third-party library? This detail may need to be spelled out.

11. Testing for Edge Cases
 - The plan’s testing strategy references unit tests and integration tests but is fairly high-level.
 - Because the user wants to handle indefinite holds and no partial fill, tests for these edge conditions (partial order fills, extremely long holds, repeated WebSocket disconnects) might need to be explicitly enumerated.

12. Future AI/Strategy Integration
 - The plan touches on “Future Extension Points” for advanced strategies, but the user has specifically mentioned they might consult an AI or a more complex logic once the basic system is stable.
 - This might be worth highlighting in the plan so that the architecture easily accommodates an additional “strategy” layer or AI calls in the future.

---
By clarifying these points, you’ll ensure that the “implementation_plan.md” fully aligns with the user’s desired approach for swing trading, real-time order management, and long-term maintainability.

# Implementation Plan Questions and Answers

## Questions and Clarifications

1. **Partial vs. Full Fills**
Question:
- The plan references general order tracking but does not clarify whether partial fills are handled or whether the system ignores them and requires orders to fill entirely.
- The user specifically wants to "sell the same amount that was bought," implying no partial selling. How do we handle a Binance order that gets partially filled?

Answer:
- For BUY orders that get partially filled:
  - Monitor and work with the filled portion immediately
  - Track the remaining unfilled portion separately
  - When the remaining portion fills, handle it as a separate trade
- Each filled portion (whether partial or complete) gets its own corresponding SELL order
- Remove "Multiple BUY orders consolidation" from State Manager as we'll maintain strict 1:1 BUY:SELL relationship

2. **Indefinite Hold (No Stop-Loss)**
Question:
- The plan states "No stop-loss needed as using SPOT orders without leverage," but it does not explicitly confirm that the system will hold onto a position indefinitely until it can meet the profit threshold.
- Clarify whether the system should ever cancel unprofitable BUY–SELL pairs if they remain open for a long time.

Answer:
- Confirm: System will hold positions indefinitely until profit threshold is met
- No automatic cancellation of unprofitable positions
- Add explicit logging for long-held positions (e.g., log when position has been held for 24h, 48h, etc.)
- Add position age tracking to database schema

3. **Exact Fee Incorporation**
Question:
- The plan mentions a 0.1% buy fee and 0.1% sell fee (0.2% total), and a 0.3% minimum profit. However, from "cursor-further-questions.md," the user wants at least 0.3% net "after fees."
- Confirm precisely how the profit calculator will add up fees vs. the "MIN_PROFIT_PERCENTAGE=0.3."

Answer:
- Profit calculation formula needs to ensure 0.3% net profit AFTER fees
- Example calculation for 100 USDC BUY:
  1. BUY cost = 100 USDC + 0.1 USDC (fee) = 100.1 USDC total cost
  2. Target net profit = 0.3% of 100 USDC = 0.3 USDC
  3. Required final amount = 100.1 USDC + 0.3 USDC = 100.4 USDC
  4. Account for sell fee (0.1%): Required SELL price = 100.4 / (1 - 0.001)
- Add unit tests specifically for these calculations

4. **Single-Trade Volume vs. Maximum Caps**
Question:
- The plan's environment variable "MAX_SELL_VALUE_USDC=100" is consistent with the user's request, but the user also mentioned that each BUY order would be about 10 USDC.
- Clarify whether 10 USDC is just an example, or if it should be enforced in code as the default.

Answer:
- Process ALL filled BUY orders under configurable maximum (default 100 USDC)
- No minimum order size enforcement (rely on Binance's minimum order size)
- Add validation to reject orders above MAX_SELL_VALUE_USDC
- Remove any references to default order sizes from the plan

5. **Handling Multiple or Consecutive BUY Orders**
Question:
- The plan references "Multiple BUY orders consolidation" under the State Manager, but the user's clarifications mostly describe a single BUY → single SELL flow.
- If the code truly supports multiple pending BUYs, clarify how that logic should consolidate them or track separate trades.

Answer:
- Remove multiple BUY consolidation feature
- Implement strict 1:1 BUY:SELL relationship
- Each BUY order (or partial fill) gets tracked independently
- Update database schema to reflect this simpler relationship

6. **Real-Time Order Fill Updates**
Question:
- The plan includes a "Price Manager" for WebSocket-based price updates, but it does not specify whether there is a user-data WebSocket or alternative approach for real-time fill notifications.
- The user's notes mention the importance of not placing a SELL until the BUY is confirmed.

Answer:
- Implement both market data and user data WebSocket streams
- Use user data stream for real-time order status updates
- Fallback to REST API order status polling when WebSocket is down
- Add explicit order state validation before placing SELL orders

7. **Exponential Backoff and 15-Minute Timeout**
Question:
- The plan mentions "exponential backoff" and "15-minute timeout" for WebSocket reconnection, but it would help to spell out in detail whether the system does a graceful shutdown at 15 minutes or attempts indefinite retries.

Answer:
- Implement 15-minute absolute timeout for WebSocket reconnection attempts
- Use exponential backoff starting at 1 second, doubling each attempt
- After 15 minutes of failed reconnection:
  1. Log error state
  2. Save all current state to database
  3. Perform graceful shutdown
  4. Exit program with non-zero status code
- No fallback to REST-only mode - require manual restart

8. **State Persistence on Shutdown**
Question:
- The plan references "System state persistence" but does not explicitly confirm that on restart the system will reconcile all previously open BUY or SELL orders with the Binance API.
- The user wants to ensure no redundant BUYs get placed if there is already an active BUY on the exchange.

Answer:
- On startup:
  1. Load state from local database
  2. Fetch all open orders from Binance API
  3. Reconcile local state with Binance state
  4. Log any discrepancies
  5. Update local state to match Binance
- Add startup reconciliation status to logging

9. **No Stop-Loss Means Potentially Infinite Wait**
Question:
- Because the user does not want to sell at a loss, the plan should confirm that the system will not attempt to close trades below the BUY price (apart from error-handling or forced manual override).
- This condition could lead to indefinite open positions, which should be stated so it's clear there is no forced liquidation.

Answer:
- Confirm: No automatic liquidation or stop-loss
- Add position duration tracking and logging
- Add API endpoint or command-line option for manual position closure if needed
- Document clearly that positions may be held indefinitely

10. **Logging & Rotation Details**
Question:
- The plan mentions a logging configuration in "4.2," but the user also wants 100 MB file-size rotation.
- Clarify how the plan implements log rotation.

Answer:
- Use Python's RotatingFileHandler
- Configure:
  - Maximum file size: 100 MB
  - Keep last 5 backup files
  - UTC timestamps
  - JSON format for machine readability
  - Include correlation IDs for tracking related events
- Add separate error log stream

11. **Testing for Edge Cases**
Question:
- The plan's testing strategy references unit tests and integration tests but is fairly high-level.
- Because the user wants to handle indefinite holds and no partial fill, tests for these edge conditions might need to be explicitly enumerated.

Answer:
- Add specific test cases:
  1. Partial fill handling
  2. Long-running position tracking
  3. WebSocket disconnection scenarios
  4. Database state recovery
  5. Profit calculation edge cases
  6. Order size validation
  7. Manual shutdown and restart
- Include integration tests with Binance testnet

12. **Future AI/Strategy Integration**
Question:
- The plan touches on "Future Extension Points" for advanced strategies, but the user has specifically mentioned they might consult an AI or a more complex logic once the basic system is stable.

Answer:
- Implement Strategy interface as planned
- Add event system for price updates and order status changes
- Prepare hooks for external decision making
- Document integration points for future AI components
- Keep core trading logic separate from strategy decisions
