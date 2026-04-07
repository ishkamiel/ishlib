# ishlib

A modular shell scripting library providing utility functions for sysadmin and
development tasks.

## Components

- **[Shell library](ishlib_shell.md)** (`ishlib.sh`): A compiled,
  self-documenting POSIX/Bash function library built from modular sources.

- **[Python library](pyishlib/index.md)** (`pyishlib`): Installer framework
  with backends for apt, brew, cargo, pip, and winget.

## Quick start

### Shell library

Source `ishlib.sh` in your script:

```sh
. /path/to/ishlib.sh
```

Or run it directly for the built-in help:

```sh
./ishlib.sh -h
```

### Python library

```python
from pyishlib import IshConfig, CommandRunner
```

See the [Python library documentation](pyishlib/index.md) for details.
