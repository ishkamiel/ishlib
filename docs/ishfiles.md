# ishfiles CLI

`ishfiles` manages dotfiles and package installations from an ishfiles
repository.

## Commands

### apply

Apply dotfiles from the ishfiles source folder to the target directory,
then install any packages defined in the package configuration.

```bash
ishfiles apply [files...]
```

When *files* are given, only those dotfiles are applied.  Package
installation always runs for all configured packages.

### install

Install packages defined in the ishfiles package configuration without
touching dotfiles.

```bash
ishfiles install [packages...]
```

When *packages* are given, only those named packages are installed.
Use `--dry-run` to see which packages would be installed.

### add

Add a file from the target directory into the ishfiles source repository.

```bash
ishfiles add [-f|--force] <files...>
```

### diff

Show pending changes between the source repository and the target
directory without applying anything.

```bash
ishfiles diff [files...]
```

### git

Run a git command inside the ishfiles source repository.  File-path
arguments are automatically translated between target and source names.

```bash
ishfiles git <git-args...>
```

## Global Options

| Flag | Description |
|------|-------------|
| `-s, --source DIR` | Path to ishfiles source folder (default: `~/.local/share/ishfiles`) |
| `-t, --target DIR` | Target directory for dotfile installation (default: `$HOME`) |
| `-c, --config FILE` | Path to config file (default: `~/.config/ishfiles/config.toml`) |
| `-n, --dry-run` | Show what would be done without making changes |
| `-v, --verbose` | Enable verbose output |
| `--debug` | Enable debug output |
| `-q, --quiet` | Suppress non-essential output |

## Package Configuration

Package definitions are read from `<source>/ishconfig/packages.toml` (preferred)
or `<source>/ishconfig/packages.json`.  The format matches the pyishlib installer
configuration schema.

### TOML example

```toml
[ripgrep]
cargo = "ripgrep"
cmd = "rg"

[bat]
apt = "bat"
cargo = "bat"
cmd = "bat"
pref = ["cargo"]

[python3-toml]
apt = "python3-toml"
pip = "toml"
ubuntu = true
```

### JSON example

```json
{
  "ripgrep": {
    "cargo": "ripgrep",
    "cmd": "rg"
  },
  "bat": {
    "apt": "bat",
    "cargo": "bat",
    "cmd": "bat",
    "pref": ["cargo"]
  }
}
```

### Package fields

| Field | Type | Description |
|-------|------|-------------|
| `apt` | string | Debian/Ubuntu package name |
| `brew` | string | Homebrew formula name |
| `cargo` | string | Cargo crate name |
| `pip` | string | PyPI package name |
| `winget` | string | Windows Package Manager ID |
| `cmd` | string | Command name used to check if already installed |
| `pref` | list | Preferred installer order (e.g. `["cargo", "apt"]`) |
| `ubuntu` | bool | Only install on Ubuntu |
| `gnome` | bool | Only install on GNOME desktop |
