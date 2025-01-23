# Questions and Answers for Swing Trading Automation

## Initial Questions

1. **Trading Strategy Specifics**:
   - Q: What is your target profit threshold percentage for swing trades?
   - Q: Do you want to implement any specific conditions for placing BUY orders, or will the system only manage SELL orders for existing BUY positions?
   - A: Minimum profit is 0.3% from the value of the BUY order (before Binance fees). System will only sell BUY positions which were fulfilled. Will sell the same amount that was bought.

2. **Technical Requirements**:
   - Q: Do you prefer SQLite (as suggested) or would you like to use a different database system?
   - Q: Should we implement both WebSocket (real-time) and REST API fallback for price updates?
   - A: Version 1 will use SQLite due to small data amount and single client usage. SQLite file will be stored in same folder as code. Implement both WebSocket for real-time updates and REST API as fallback. When using REST API, 5-second refresh rate is acceptable.

3. **Deployment & Environment**:
   - Q: Will this be running continuously on a server, or executed manually when needed?
   - Q: Do you already have Binance API credentials with appropriate permissions?
   - A: Will be executed manually during development. Future plans include continuous server operation. Binance API credentials with required permissions are available. All secrets will be stored in .env file.

4. **Risk Management**:
   - Q: Would you like to implement position size limits or maximum order values?
   - Q: Should we implement stop-loss functionality alongside the profit-taking logic?
   - A: Will always sell same volume as bought. Hard-coded SELL limit of 100 USDC (BUY positions under 50 USDC). No stop-loss needed as using SPOT orders without leverage. If price drops below BUY price, wait indefinitely for market recovery.

## Additional Clarifications

1. **Order Execution**:
   - BUY orders are not partial
   - SELL orders will not be partial
   - Always trading specific volume

2. **Profit Calculation**:
   - Minimum profit 0.3% includes Binance fees (0.1% buy + 0.1% sell)
   - Example: BUY at 100 USDC + 0.1 USDC fee
   - Target: End up with 100.3 USDC after sell (including sell fee)
   - SELL price must be calculated to achieve this net profit

3. **System State Management**:
   - System can be stopped with CTRL+C
   - State stored in SQLite DB
   - On restart, system resumes from last saved state

4. **Testing**:
   - Implement simple unit tests

5. **Architecture**:
   - Code structure should allow easy integration of additional decision layers in future development

6. **Logging**:
   - Logs stored in file next to SQLite DB
   - Customizable verbosity
   - Log network errors and API rate limits
   - Rotate logs when file exceeds 100MB

7. **Error Handling**:
   - Stop script after 15 minutes of unsuccessful WebSocket reconnection attempts
   - Use exponential backoff for reconnection attempts
   - Graceful shutdown after 15 minutes of failed reconnection
   - Leave existing orders open on Binance during shutdown
