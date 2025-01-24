# Plan for Implementing Graceful Shutdown

## Current Issues Analysis

1. **Signal Handler Implementation**
   - Current implementation in `main.py` tries to be too clever with threaded shutdown
   - The signal handler should be simple and direct, not spawning new threads
   - Multiple shutdown attempts can occur due to lack of proper state tracking
   - Reason: The current approach violates the principle of having a clear, single shutdown path

2. **Component Lifecycle Management**
   - Components (PriceManager, OrderManager, StateManager) have independent shutdown logic
   - No clear order of shutdown is enforced
   - Threads are not properly joined with appropriate timeouts
   - Each manager needs to check stop flags in their loops
   - Each manager has multiple threads that need tracking:
     * PriceManager: WebSocket listener + Keep-alive timer threads
     * OrderManager: Position duration monitoring thread
     * StateManager: State reconciliation thread
   - Reason: This violates PRODUCTION_DESIGN.md's requirement for graceful shutdown and resource cleanup

3. **Thread Management**
   - Daemon threads are used incorrectly, leading to potential resource leaks
   - Sleep intervals in monitoring loops are too long (5s, 10s)
   - No proper exit condition checking in loops
   - Risk of "zombie" threads in StateManager
   - Reason: This causes the application to hang during shutdown

## Configuration Management

```python
# src/config/settings.py
from datetime import timedelta

# Thread Management
MONITOR_LOOP_INTERVAL = 0.1  # Same for both local and prod

# Component Shutdown Timeouts
SHUTDOWN_TIMEOUT_ORDER = 2.0  # Longer timeout for DB operations
SHUTDOWN_TIMEOUT_PRICE = 1.0  # Shorter - no DB operations
SHUTDOWN_TIMEOUT_STATE = 2.0  # Longer for final state persistence

# WebSocket Settings
WEBSOCKET_PING_INTERVAL = timedelta(seconds=10)
WEBSOCKET_PING_TIMEOUT = timedelta(seconds=5)

# Database Settings
DB_TRANSACTION_BATCH_SIZE = 100
DB_COMMIT_INTERVAL = timedelta(seconds=1)
```

## Proposed Changes

1. **Main Application Structure**
   ```python
   def handle_signal(signum, frame):
       """Simple, direct signal handler that either initiates shutdown or forces exit"""
       logger.info("Caught signal %s, initiating shutdown...", signum)
       if app.shutting_down:
           logger.warning("Forced exit requested, calling os._exit(1)", exc_info=True)
           # Ensure logs are flushed before forced exit
           for handler in logging.getLogger().handlers:
               handler.flush()
           sys.stdout.flush()
           sys.stderr.flush()
           os._exit(1)
       app.shutdown()
   ```
   Reasoning: Simple signal handler that follows init-run-help-o1.md's example.

2. **Component Shutdown Sequence**
   ```python
   def shutdown(self):
       """Ordered shutdown of components with proper state tracking"""
       try:
           self.shutting_down = True
           
           # 1. Stop OrderManager (depends on others)
           self.order_manager.stop()
           if not self.order_manager.join(timeout=settings.SHUTDOWN_TIMEOUT_ORDER):
               logger.error("OrderManager failed to stop in time")
           
           # 2. Stop PriceManager (provides data)
           self.price_manager.stop()
           if not self.price_manager.join(timeout=settings.SHUTDOWN_TIMEOUT_PRICE):
               logger.error("PriceManager failed to stop in time")
           
           # 3. Stop StateManager (handles final state)
           self.state_manager.stop()
           if not self.state_manager.join(timeout=settings.SHUTDOWN_TIMEOUT_STATE):
               logger.error("StateManager failed to stop in time")
           
           # Final state verification
           self.verify_final_state()
           
       except Exception as e:
           logger.error("Error during shutdown", exc_info=True)
           raise
       finally:
           # Ensure all logs are flushed
           for handler in logging.getLogger().handlers:
               handler.flush()
           sys.stdout.flush()
           sys.stderr.flush()
           sys.exit(0)  # Clean exit after resources are freed
   ```
   Reasoning: Respects component dependencies and ensures clean state persistence.

3. **Manager Base Class Implementation**
   ```python
   class BaseManager:
       def __init__(self):
           self.threads = []  # Track all threads
           self.should_run = False
           
       def register_thread(self, thread):
           """Register a thread for tracking"""
           self.threads.append(thread)
           
       def run(self):
           self.should_run = True
           while self.should_run:
               try:
                   # Do work
                   pass
               except Exception as e:
                   logger.error("Error in manager loop", exc_info=True)
               time.sleep(settings.MONITOR_LOOP_INTERVAL)
               
       def stop(self):
           """Stop all threads and cleanup resources"""
           self.should_run = False
           
           # Stop all threads with timeout
           for thread in self.threads:
               if thread.is_alive():
                   thread.join(timeout=1.0)
                   if thread.is_alive():
                       logger.error(f"Thread {thread.name} failed to stop")
           
           # Close resources (WebSocket, DB connections)
           self.cleanup_resources()
           
       def cleanup_resources(self):
           """Implement in subclass to cleanup specific resources"""
           pass
   ```
   Reasoning: Ensures proper thread tracking and cleanup across all managers.

## Implementation Plan

1. **Phase 1: Signal Handler Refactoring**
   - Simplify signal handling in main.py
   - Add shutdown state tracking
   - Remove threaded shutdown approach
   - Add comprehensive logging with exc_info=True
   - Ensure log flushing before exit
   Reason: Establish a solid foundation for shutdown process

2. **Phase 2: Component Shutdown Enhancement**
   - Add should_run flags to all components
   - Implement proper thread cleanup with configurable timeouts
   - Add resource cleanup in finally blocks
   - Verify WebSocket connections are closed
   - Ensure DB transactions are committed/rolled back
   - Add transaction batching for faster commits
   Reason: Ensure each component can stop cleanly

3. **Phase 3: State Management**
   - Ensure final state is saved before exit
   - Add state verification after save
   - Implement proper cleanup of resources
   - Add DB transaction safety checks
   - Verify no "zombie" threads in StateManager
   - Add transaction batching for final state save
   Reason: Maintain system state integrity

4. **Phase 4: Thread Management**
   - Refactor all monitoring loops to check should_run
   - Implement thread registration and tracking
   - Add proper exit conditions and timeouts
   - Implement REST fallback during normal operation
   - Add exception handling with full stack traces
   Reason: Improve shutdown responsiveness

## Manager-Specific Thread Handling

1. **PriceManager Threads**
   ```python
   class PriceManager(BaseManager):
       def __init__(self):
           super().__init__()
           self.ws_thread = None
           self.keepalive_thread = None
           
       def start(self):
           # Start WebSocket listener
           self.ws_thread = threading.Thread(
               target=self._run_websocket,
               name="WebSocketListener"
           )
           self.register_thread(self.ws_thread)
           self.ws_thread.start()
           
           # Start keep-alive timer
           self.keepalive_thread = threading.Thread(
               target=self._run_keepalive,
               name="KeepAliveTimer"
           )
           self.register_thread(self.keepalive_thread)
           self.keepalive_thread.start()
   ```

2. **OrderManager Thread**
   ```python
   class OrderManager(BaseManager):
       def start(self):
           self.monitor_thread = threading.Thread(
               target=self._monitor_positions,
               name="PositionMonitor"
           )
           self.register_thread(self.monitor_thread)
           self.monitor_thread.start()
   ```

3. **StateManager Thread**
   ```python
   class StateManager(BaseManager):
       def start(self):
           self.reconcile_thread = threading.Thread(
               target=self._reconcile_state,
               name="StateReconciliation"
           )
           self.register_thread(self.reconcile_thread)
           self.reconcile_thread.start()
   ```

## Testing Plan

1. **Unit Tests**
   ```python
   def test_graceful_shutdown():
       """Test graceful shutdown sequence"""
       app = Application()
       app.start()
       
       # Verify all threads are running
       assert len(app.price_manager.threads) == 2
       assert len(app.order_manager.threads) == 1
       assert len(app.state_manager.threads) == 1
       
       # Simulate active trading
       time.sleep(1)
       
       # Trigger shutdown
       os.kill(os.getpid(), signal.SIGINT)
       
       # Verify cleanup
       assert not app.price_manager.is_running()
       assert not app.order_manager.is_running()
       assert app.final_state_verified
       
       # Verify all threads stopped
       assert all(not t.is_alive() for t in app.price_manager.threads)
       assert all(not t.is_alive() for t in app.order_manager.threads)
       assert all(not t.is_alive() for t in app.state_manager.threads)
   ```

2. **Integration Tests**
   ```python
   def test_forced_shutdown():
       """Test forced shutdown during active operations"""
       app = Application()
       app.start()
       
       # Simulate partial fill
       app.order_manager.handle_partial_fill(...)
       
       # Force shutdown during DB operation
       os.kill(os.getpid(), signal.SIGINT)
       os.kill(os.getpid(), signal.SIGINT)
       
       # Verify DB state is not corrupted
       assert verify_db_integrity()
       
       # Verify logs were flushed
       with open('app.log', 'r') as f:
           logs = f.read()
           assert "Forced exit requested" in logs
   ```

## Verification Steps

1. **Basic Shutdown**
   - Single Ctrl+C initiates graceful shutdown
   - All components stop in order with appropriate timeouts:
     * OrderManager: 2s (DB operations)
     * PriceManager: 1s (no DB operations)
     * StateManager: 2s (final state save)
   - Final state is saved and verified
   - All threads are joined
   - Resources are cleaned up
   - Logs are flushed

2. **Forced Shutdown**
   - Double Ctrl+C forces immediate exit
   - System logs forced shutdown with stack trace
   - DB integrity is maintained through transaction batching
   - No resource leaks
   - Logs are flushed before exit

3. **Resource Cleanup**
   - WebSocket connections close properly
   - DB connections close with transaction safety
   - No zombie threads remain
   - Logs show cleanup sequence
   - All file handles are closed

## Success Criteria

1. Application stops within 5 seconds of first Ctrl+C (sum of component timeouts)
2. No hanging threads or connections
3. State is properly saved with verification
4. Logs show clean shutdown sequence with stack traces
5. Resources are properly cleaned up
6. Integration tests pass for both graceful and forced shutdown
7. REST fallback works during normal operation
8. No DB corruption on forced exit
9. All logs are properly flushed before exit

## Monitoring and Logging

1. **Enhanced Logging**
   ```python
   logger.info("Starting shutdown sequence")
   try:
       # Shutdown logic
   except Exception as e:
       logger.error("Shutdown error", exc_info=True)
   finally:
       logger.info("Shutdown complete", extra={
           "final_state": state_summary,
           "cleanup_status": cleanup_results,
           "active_threads": [t.name for t in threading.enumerate()],
           "db_connections": db.pool.size()
       })
       # Ensure logs are flushed
       for handler in logging.getLogger().handlers:
           handler.flush()
       sys.stdout.flush()
       sys.stderr.flush()
   ```

2. **State Verification**
   ```python
   def verify_final_state(self):
       """Verify database state and resource cleanup"""
       try:
           # Verify DB state
           assert self.db.verify_integrity()
           
           # Check for active threads
           active_threads = threading.enumerate()
           assert len(active_threads) == 1  # Only main thread
           
           # Verify WebSocket closure
           assert all(ws.closed for ws in self.websockets)
           
           # Verify DB connections are closed
           assert self.db.pool.size() == 0
           
       except AssertionError as e:
           logger.error("State verification failed", exc_info=True)
           raise
   ```

This plan addresses all points from init-run-help-o1.md and includes the specific implementation details requested in init-run-help-o1-plan-o1.md while maintaining compliance with PRODUCTION_DESIGN.md's architecture and requirements. It specifically addresses thread management, DB commit timeouts, log flushing, and configuration consistency between local and production environments. 