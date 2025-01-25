Explanation of the Errors
From the log traces, the two primary issues appear to be:
Unexpected keyword arguments passed to the logger
The Python standard logging library (i.e., the built-in logging.Logger) does not allow arbitrary keyword arguments (e.g., url, symbol, error) to be passed directly to methods such as logger.info() and logger.error(). When you call something like:
» self.logger.info("Started market data WebSocket", url=self.ws_url)
the standard logging machinery sees an extra keyword argument (url) that it does not recognize. Standard Python logging supports a specific set of keywords such as exc_info, stack_info, etc. Arbitrary fields need to be placed inside the extra= dictionary if you remain on the built-in Python logger. For example:
» self.logger.info("Started market data WebSocket", extra={"url": self.ws_url})
However, your code imports and configures Structlog (“import structlog”), which does allow passing arbitrary key-value pairs in log calls. The error strongly suggests that, at runtime, Python is actually using the standard logging.Logger methods instead of the intended Structlog pipeline, leading to the “unexpected keyword argument” errors.
In short, there is a mismatch between:
The Structlog configuration (which allows “key=value” pairs in log calls).
The instantiated loggers (which might be falling back to standard logging.Logger).
Calling join(...) on OrderManager
Near the bottom of the log, there is:
» AttributeError: 'OrderManager' object has no attribute 'join'
That means somewhere in the shutdown process, the code does:
» self.order_manager.join(timeout=SHUTDOWN_TIMEOUT_ORDER)
But the OrderManager class is not a thread (or at least does not appear to extend Python’s Thread class or define a .join()). This causes an AttributeError. If you need to wait for background tasks in OrderManager, you might implement your own method like order_manager.stop() or order_manager.wait_for_completion(), rather than calling .join() on it directly.

Why These Errors Happen
• Structlog vs. standard logging
Structlog is typically configured to wrap Python’s logging, converting the underlying messages into a JSON or key-value format. If Structlog is not configured correctly, or if the code is using a plain Python logger instead of the Structlog-augmented one, logging calls with arbitrary named parameters (e.g., url=...) will cause a TypeError.
• No .join() method in OrderManager
.join() is a method for threads or thread-like objects. If OrderManager is simply a class that spawns threads internally, calling .join() on it directly won’t work unless that method is explicitly implemented.
---
How to Resolve
Ensure Structlog is actually handling the log calls
Double-check that each module’s logger is acquired via Structlog’s functions (for example, using something like logger = structlog.get_logger(__name__)) rather than calling logging.getLogger(__name__).
If you need structured logs from standard logging.Logger, place your extra fields in extra={...}:
» self.logger.info("Message", extra={"url": self.ws_url})
Usually, you want consistent usage of either Structlog or standard logging in key-value style, but mixing them can easily lead to confusion.
Fix the shutdown logic for OrderManager
If OrderManager internally starts threads, you might:
Provide a method like def join_all_threads(self, timeout: float) -> bool: that joins underlying threads.
Or, if you do not need to wait on threads individually, then just call OrderManager.stop(), ensuring any worker threads are signaled to exit.
Remove or replace self.order_manager.join(timeout=SHUTDOWN_TIMEOUT_ORDER) unless OrderManager is truly a subclass of threading.Thread.
Once these two issues are addressed, the “unexpected keyword argument” and “no attribute ‘join’” errors should no longer occur.