# ishlib 2021-04-03.1332.be44ba0

This is a collection of various scripts and tricks collected along the years.

DISCLAIMER: This is ostly just for playing around with bash / shell scripts,
so no guarantees that this is in a stable state at any given time.

The script is meant to be sourced elsewhere, but can be invoked as
`./ishlib.sh -h` flag to show the same documentation as below. The source
files in `./src` need not be manually used, they are already in `ishlib.sh`.

The documentation contains references to original sources where available,
but in practice this has been accumulated along the years, so many sources
are likely listed. Feel free to drop me a note if you notice some source or
acknowledgement that is missing.

## Known bugs and issues

- Documentation for `dry_run` is wrong.

## Documentation

### POSIX-compliant functions

#### `ishlib_version`

Print out the version of ishlib loaded.

#### `print_docstrings file [options]`

Prints out specific docstrings found in the given file. Default is to just
print the here-documents as they are. However, the script can optionally try
to convert to plain text or markdown. Note that the conversion relies very
specific and largely undocumented conventions followed in ishlib.sh, and will
likely misbehave in other contexts.

##### Arguments:

```
    file          - the file to read for here-documents
    --markdown    - Attempt to produce markdown
    --text-only   - Attempt to remove markdown notations
    --tag TAG     - use the given TAG for docstrings (default is DOCSTIRNG)
    --no-newlines - prevent insertion of newlines
```

##### Returns:

```
      0
```


#### Print and debug helpers

The print functions all follow the same pattern, i.e, they print a short tag
followed by the all arguments colorized as specificed by global color tags.
At present, all printouts are to sdtderr. All functions return 0, or, ine
case of fail, never returns.

#### `say ...`

#### `warn ...`

#### `fail ...`

Prints the args and then calls `exit 1`

#### `say_dry_run ...`

Prints the args with the dry_run tag, mainly for internal use.

#### `debug ...`

##### Globals:

```
      DEBUG - does nothing unless DEBUG=1
```


#### `ishlib_debug ...`

##### Globals:

```
      DEBUG        - does nothing unless DEBUG=1
      ISHLIB_DEBUG - does nothing unless this is 1
```


#### `substr string start [end] [--var result_var]`

#### `strlen string [--var result_var]`

#### `do_or_dry [--bg [--pid=pid_var]] cmd [args...]`

TODO: merge do_or_dry_bg here using the above cmdline args

#### `do_or_dry_bg pid_var cmd [args...]`

TODO: merge do_or_dry_bg here using the above cmdline args

#### `is_dry`

Just a convenience function for checking DRY_RUN in constructs like:
`if is_dry; then ...; fi`.

##### Returns:

```
      0       - if $DRY_RUN is 1
      1       - if $DRY_RUN is not 1
```

