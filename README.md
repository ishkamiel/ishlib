# ishlib 2024-10-12.1422.30545d4

This is a collection of various scripts and tricks collected along the years.

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
    --text-only   - Attempt to produce texst-only
    --tag TAG     - use the given TAG for docstrings (default is DOCSTIRNG)
    --no-newlines - prevent insertion of newlines
```
##### Returns:

```
      0
```

#### Print and debug helpers

The print functions all follow the same pattern, i.e, they print a short tag
followed by the all arguments colorized as specified by global color tags.
At present, all printouts are to sdtderr. All functions return 0, or in
case of failure, never returns.

#### `ish_say ...`

#### `ish_warn ...`

#### `ish_fail ...`

Prints the args and then calls `exit 1`

#### `ish_say_dry_run ...`

Prints the args with the dry_run tag, mainly for internal use.

#### `ish_debug ...`

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

#### `has_prefix str prefx`

Source:

##### Arguments:

```
      str - string to look into
      prefix - the prefix to check for
```
##### Returns:

```
      0 - if prefix is found
      1 - if prefix isn't found
```

#### `download_file url dst`

Attempts to download file at $url to $dst, creating the containing directory
if needed. Will first try curl, then wget, and finally ish_fail if neither is
available.

##### Arguments:

```
      url - the URL to download
      dst - the filename to save to
```
##### Returns:

```
      0 - on success
      1 - bad arguments given
      2 - when neither curl nor wget was found
      x - error code from curl/wget
```

has_command cmd
---------------

Checks if a command exists, either as an executable in the path, or as a shell
function. Returns 0 if found, 1 otherwise. No output.

##### Arguments:

```
      cmd - name of binary or function to check for
```
##### Returns:

```
      0 - if command was found
      1 - if command not found
      2 - if argument was missing
```

substr string start [end] [--var result_var]

#### `strlen string [--var result_var]`

#### `ish_prepend_to_path`

Add path to beginning of  $PATH unless it already exists.

### Bash-only functions

#### `array_from_ssv var str`

Read space-separated values into an array variable.

##### Arguments:

```
      var - the name of an array variable to populate
      str - the string to split
```
##### Returns:

```
      0 - on success
      1 - on failure
```

strstr haystack needle [pos_var]
--------------------------------

Finds needle in given haystack, if pos_var is given, then also stores the
position of the found variable into ${!pos_var}.

##### Arguments:

```
        haystack - the string to look in
        needle - the string to search for
        pos_var - name of a variable for positionli
    Side-effects:
        ${!pos_var} - set to -1 on ish_fail, otherwise to the position of needle
```
##### Returns:

```
        0 - if needle was found
        1 - otherwise
```

#### `find_or_install var [installer [args...]]`
-----------------------------

Tries to find and set path for command defined by the variable named var,
i.e., ${!var}. Will also update the var variable with a full path if
applicable.

##### Arguments:

```
      var       - Indirect reference to command
      installer - Optional installer function
      args      - Additional argumednts to installer function
    Side effects:
      ${!var} - the variable named by var is set to the found or installed cmd
```
##### Returns:

```
      0 - if cmd found or installed
      1 - if cmd not found, nor successfully installed
```

#### `dump $var1 [var2 var3 ...]`
-----------------

Will call dumpVariable for each member of vars.

##### Globals:

```
```
##### Arguments:

```
      varN - name of a variable to dump
```
##### Returns:

```
      0 - if all varN were bound
      n - number of unbound varN encountered
```

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

#### `git_clone_or_update [-b branch] [--update-submodules] url dir`

##### Arguments:

```
      url                   - the git remote URL
      dir                   - The destianation directory
      --update_submodules   - Run submodule update after clone
      -b|--branch branch      - Specify branch to checkout / update
      -c|--commit           - Also checkokut specific commit
```
##### Globals:

```
      bin_git               - Path to git (default : git)
      DRY_RUN               - Respects dry-run flag
```
##### Returns:

```
      0 - on success
      1 - on failure
```

#### `copy_function src dst`

Copies the src function to a new function named dst.

Source: https://stackoverflow.com/a/18839557

##### Arguments:

```
      src - the name to rename from
      dst - the name to rename to
```
##### Returns:

```
      0 - on success
      1 - on failure
```

#### `rename_function src dst`

Renames the src function to dst.

Source: https://stackoverflow.com/a/18839557

##### Arguments:

```
      src - the name to rename from
      dst - the name to rename to
```
##### Returns:

```
      0 - on success
      1 - on failure
```
