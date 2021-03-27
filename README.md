# ishlib 2021-03-27.1320.88aee6b

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

ishlib_version
--------------
  
  Print out the version of ishlib loaded. Is redefined for bash.
  
  Arguments:
      -
  Returns:
      0
    
`print_docstrings file [options]`

Prints out specific docstrings found in the given file. Default is to just
print the here-documents as they are. However, the script can optionally try
to convert to plain text or markdown. Note that the conversion relies very
specific and largely undocumented conventions followed in ishlib.sh, and will
likely misbehave in other contexts.

  Arguments:
      file - the file to read for here-documents
    Options:
      --markdown - Attempt to produce markdown
      --text-only - Attempt to remove markdown notations
      --tag TAG - use the given TAG for docstrings (default is DOCSTIRNG)
      --no-newlines - prevent insertion of newlines
  Returns:
      0
    
print_DOCSTRINGs
----------------
  
  Prints out documentation (i.e., the anonymous DOCSTRINGs).
  
  Arguments:
      -
  Returns:
      0
    
say ...
-------
  
  Prints the given args to stderr, but only if DEBUG=1.
  
  Globals:
      ish_ColorDebug - printed before arguments (e.g., to set color)
      ish_ColorNC - printed after arguments (e.g., to reset color)
  Arguments:
      ... - all arguments are printed
  Returns:
      0 - always

`ishlib_debug ...`

Passes args to debug, but only if ISHLIB_DEBUG is set to 1.

  Globals:
      ISHLIB_DEBUG - does nothing unless this is 1
  Arguments:
      ... - all arguments are printed
  Returns:
      0 - always

say ...
-------
  
  Prints the given args to stderr.
  
  Globals:
      ish_ColorSay - printed before arguments (e.g., to set color)
      ish_ColorNC - printed after arguments (e.g., to reset color)
  Arguments:
      ... - all arguments are printed
  Returns:
      0 - always

warn ...
--------
  
  Prints the given args to stderr.
  
  Globals:
      ish_ColorWarn - printed before arguments (e.g., to set color)
      ish_ColorNC - printed after arguments (e.g., to reset color)
  Arguments:
      ... - all arguments are printed
  Returns:
      0 - always

fail ...
--------
  
  Prints the given args to stderr and then exits with the value 1.
  
  Globals:
      ish_ColorFail - printed before arguments (e.g., to set color)
      ish_ColorNC - printed after arguments (e.g., to reset color)
  Arguments:
      ... - all arguments are printed
  Returns:
      never returns
    
dry_run ...
--------
  
  Prints the given args to stderr and then exits with the value 1.
  
  Globals:
      ish_ColorDryRun - printed before arguments (e.g., to set color)
      ish_ColorNC - printed after arguments (e.g., to reset color)
  Arguments:
      ... - all arguments are printed
  Returns:
      never returns
    
has_prefix str prefx

Source: 

  Arguments:
      str - string to look into
      prefix - the prefix to check for
  Returns:
      0 - if prefix is found
      1 - if prefix isn't found
    
download_file $url $dst
-----------------------
  
  Attempts to download file at $url to $dst, creating the containing directory
  if needed. Will first try curl, then wget, and finally fail if neither is
  awailable.
  
  Arguments:
      url - the URL to download
      dsg - the filename to store the download at
  Returns: 
      0 - on success
      1 - bad arguments given
      2 - when neither curl nor wget was found
      x - error code from curl/wget
    
has_command cmd
---------------
  
  Checks if a comman exists, either as an executable in the path, or as a shell
  function. Returns 0 if found, 1 otherwise. No output.
  
  Arguments:
      cmd - name of binary or function to check for
  Returns:
      0 - if command was found
      1 - if command not found
      2 - if argument was missing

### Bash-only functions

array_from_ssv var str
----------------------
  
  Read space-separated values into an array variable.
  
  Arguments:
      var - the name of an array varialbe to populate
      str - the string to split
  Returns:
      0 - on success
      1 - on failure
    
strstr haystack needle [pos_var]
--------------------------------
  
  Finds needle in given haystack, if pos_var is given, then also stores the
  position of the found variable into ${!pos_var}.
  
  Arguments: 
        haystack - the string to look in
        needle - the string to search for
        pos_var - name of a variable for positionli
    Side-effects:
        ${!pos_var} - set to -1 on fail, otherwise to the position of needle
  Returns:
        0 - if needle was found
        1 - otherwise
    
find_or_install var [installer [installer args]]
-----------------------------
  
  Tries to find and set path for command defined by the variable named var,
  i.e., ${!var}. Will also update the var variable with a full path if
  applicable.
  
  Arguments:
      var - name of variable holding command
      installer - optional installer function
      install_path - where the installer will install the binary
    Side effects:
      ${!var} - the variable named by var is set to the found or installed cmd
  Returns:
      0 - if cmd found or installed
      1 - if cmd not found, nor successfully installed
    
dump var1 [var2 var3 ...]
-----------------
  
  Will call dumpVariable for each member of vars.
  
  Globals:
  Arguments:
      varN - name of a variable to dump
  Returns:
      0 - if all varN were bound
      n - number of unbound varN encountered

do_or_dry cmd ...

do_or_dry cmd ...

git_clone_or_update url dir

  Arguments:
      url - the git repository remote
      dir - the local directory for the repository
  Globals:
      bin_git - if specified, will use the given command in place of git
  Returns:
      0 - on success
      x - on failure, either 1 or return value of git

copy_function src dst
----------------------
  
  Copies the src function to a new function named dst.
  
  Source: https://stackoverflow.com/a/18839557
  
  Arguments:
      src - the name to rename from
      dst - the name to rename to
  Returns:
      0 - on success
      1 - on failure
    
rename_function src dst
-----------------------
  
  Renames the src function to dst.
  
  Source: https://stackoverflow.com/a/18839557
  
  Arguments:
      src - the name to rename from
      dst - the name to rename to
  Returns:
      0 - on success
      1 - on failure
    
