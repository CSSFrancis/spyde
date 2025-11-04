# Logging in SpyDE

## Overview

SpyDE uses Python's built-in `logging` module for all application output. All `print()` statements have been replaced with appropriate logging calls to provide better control and visibility into application behavior.

## Configuration

Logging is configured centrally in `spyde/logging_config.py` and initialized when the application starts in `main_window.py:main()`.

### Setting Log Level

There are two ways to set the logging level:

#### 1. Via the GUI (Recommended)

Use the menu: **View → Set Log Level** and select from:
- **DEBUG**: Show all diagnostic information
- **INFO**: Show general informational messages (default)
- **WARNING**: Show only warnings and errors
- **ERROR**: Show only errors
- **CRITICAL**: Show only critical errors

The log level can be changed at any time while the application is running, and changes take effect immediately.

#### 2. Via Environment Variable

- **LOG_LEVEL**: Set the logging level at startup (DEBUG, INFO, WARNING, ERROR, CRITICAL)
  - Default: `INFO` in production
  - For debugging, set `LOG_LEVEL=DEBUG`

Example:
```bash
export LOG_LEVEL=DEBUG
spyde
```

## Usage in Code

### Creating a Logger

Each module should create its own logger at the module level:

```python
import logging

logger = logging.getLogger(__name__)
```

### Logging Messages

Use appropriate logging levels:

```python
# Debug - Detailed diagnostic information
logger.debug("Processing data with shape: %s", data.shape)

# Info - General informational messages
logger.info("Signal loaded: %s", signal)

# Warning - Something unexpected but not critical
logger.warning("Could not find tool button for action %s", action_name)

# Error - An error occurred but the application can continue
logger.error("Plot update failed: %s", result)

# Critical - A serious error that may prevent the application from continuing
logger.critical("Unable to initialize Dask client")
```

### Exception Logging

For exceptions, use `logger.exception()` inside an except block:

```python
try:
    process_data()
except Exception as e:
    logger.exception("Failed to process data: %s", e)
    raise
```

This automatically includes the traceback in the log output.

## Best Practices

1. **Use string formatting with %**: Instead of f-strings, use `%s` placeholders
   ```python
   # Good
   logger.info("Loading file: %s", filename)
   
   # Avoid
   logger.info(f"Loading file: {filename}")
   ```
   This is more efficient because string formatting only happens if the log level is enabled.

2. **Choose appropriate log levels**:
   - `DEBUG`: Detailed information for diagnosing problems
   - `INFO`: Confirmation that things are working as expected
   - `WARNING`: Something unexpected happened, but the software is still working
   - `ERROR`: A serious problem occurred
   - `CRITICAL`: The program may be unable to continue

3. **No print statements**: Use logging instead. Print statements should only be used in:
   - Example scripts that demonstrate usage
   - Test output that should always be visible

4. **Third-party library logging**: Overly verbose third-party loggers are suppressed in `logging_config.py` to reduce noise.

## Testing Logging

To verify logging is working in a module:

```python
import os
os.environ['LOG_LEVEL'] = 'DEBUG'

from spyde.logging_config import setup_logging
setup_logging()

# Your code with logging calls
```

## Output Format

The default log format is:
```
%(asctime)s - %(name)s - %(levelname)s - %(message)s
```

Example output:
```
2025-11-04 15:04:16 - spyde.main_window - INFO - Starting Dask LocalCluster with 4 workers
2025-11-04 15:04:16 - spyde.signal_tree - DEBUG - Created Signal Tree with root signal: <Signal>
```
