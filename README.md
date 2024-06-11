## PYSTAND - Install Python Versions From The Python-Build-Standalone Project
[![PyPi](https://img.shields.io/pypi/v/pystand)](https://pypi.org/project/pystand/)
[![AUR](https://img.shields.io/aur/version/pystand)](https://aur.archlinux.org/packages/pystand/)

[`pystand`][pystand] is a command line tool to facilitate the
installation and update of pre-built Python versions from the
[`python-build-standalone`][pbs] project. The following commands are
provided:

|Command  |Description                                                           |
|---------|----------------------------------------------------------------------|
|`install`|Install one or more versions from a python-build-standalone release   |
|`update` |Update one, more, or all versions to another release                  |
|`remove` |Remove/uninstall one, more, or all versions                           |
|`list`   |List installed versions and show which have an update available       |
|`show`   |Show versions available from a release                                |
|`path`   |Show path prefix to installed version base directory                  |

By default, Python versions are sourced from the latest
`python-build-standalone` [release][pbs-rel] available but you can
optionally specify any older release. The required
[distribution](https://gregoryszorc.com/docs/python-build-standalone/main/running.html)
for your machine architecture is normally auto-detected but can be
overridden if required.

Some simple usage examples are:

```sh
$ pystand install 3.12
Version 3.12.3 @ 20240415 installed.

$ ls -l $(pystand path 3.12)/bin
total 4136
lrwxrwxrwx 1 user user       9 May 30 22:23 2to3 -> 2to3-3.12
-rwxrwxr-x 1 user user     128 Jan  1 10:00 2to3-3.12
lrwxrwxrwx 1 user user       8 May 30 22:23 idle3 -> idle3.12
-rwxrwxr-x 1 user user     126 Jan  1 10:00 idle3.12
-rwxrwxr-x 1 user user     256 Jan  1 10:00 pip
-rwxrwxr-x 1 user user     256 Jan  1 10:00 pip3
-rwxrwxr-x 1 user user     256 Jan  1 10:00 pip3.12
lrwxrwxrwx 1 user user       9 May 30 22:23 pydoc3 -> pydoc3.12
-rwxrwxr-x 1 user user     111 Jan  1 10:00 pydoc3.12
lrwxrwxrwx 1 user user      10 May 30 22:23 python -> python3.12
lrwxrwxrwx 1 user user      10 May 30 22:23 python3 -> python3.12
-rwxrwxr-x 1 user user 4206512 Jan  1 10:00 python3.12
-rwxrwxr-x 1 user user    3078 Jan  1 10:00 python3.12-config
lrwxrwxrwx 1 user user      17 May 30 22:23 python3-config -> python3.12-config

$ pystand install 3.10
Version 3.10.14 @ 20240415 installed.

$ pystand list
3.10.14 @ 20240415 distribution="x86_64-unknown-linux-gnu"
3.12.3 @ 20240415 distribution="x86_64-unknown-linux-gnu"

$ pystand show
3.8.19 @ 20240415 distribution="x86_64-unknown-linux-gnu"
3.9.19 @ 20240415 distribution="x86_64-unknown-linux-gnu"
3.10.14 @ 20240415 distribution="x86_64-unknown-linux-gnu" (installed)
3.11.9 @ 20240415 distribution="x86_64-unknown-linux-gnu"
3.12.3 @ 20240415 distribution="x86_64-unknown-linux-gnu" (installed)

$ pystand remove 3.10
Version 3.10.14 @ 20240415 removed.

$ pystand list
3.12.3 @ 20240415 distribution="x86_64-unknown-linux-gnu"
```

Here are some examples showing how to use an installed version ..

```sh
# Use uv to create a virtual environment to be run with pystand installed python:
$ uv venv -p $(pystand path 3.12) myenv

# Create a regular virtual environment to be run with pystand installed python:
$ $(pystand path -p 3.12) -m venv myenv

# Use pipx to install a package to be run with pystand installed python:
$ pipx install --python $(pystand path -p 3.12) cowsay
```

See detailed usage information in the [Usage](#usage) section that
follows.

Note that unlike nearly all similar tools such as [`pyenv`][pyenv], [`pdm
python`][pdmpy], and [`hatch python`][hatchpy], `pystand` directly
checks the [`python-build-standalone`][pbs] github site to fetch for new
[releases][pbs-rel] but those other tools require a software update
before they can see new releases. This means that Python updates are
available more quickly from `pystand` than other tools.

This utility has been developed and tested on Linux but should also work
on macOS and Windows although has not been tried on those platforms. The
latest documentation and code is available at
https://github.com/bulletmark/pystand.

## Usage

Type `pystand` or `pystand -h` to view the usage summary:

```
usage: pystand [-h] [-D DISTRIBUTION] [-B BASE_DIR] [-C CACHE_MINUTES]
                  [--purge-days PURGE_DAYS] [-V]
                  {install,update,remove,list,show,path} ...

Command line tool to install pre-built Python versions from the python-build-
standalone project.

options:
  -h, --help            show this help message and exit
  -D DISTRIBUTION, --distribution DISTRIBUTION
                        python-build-standalone "*-install_only" distribution,
                        e.g. "x86_64-unknown-linux-gnu". Default is auto-
                        detected (detected as "x86_64-unknown-linux-gnu" for
                        this current host).
  -B BASE_DIR, --base-dir BASE_DIR
                        specify pystand base dir for storing versions and
                        metadata. Default is "$HOME/.local/share/pystand"
  -C CACHE_MINUTES, --cache-minutes CACHE_MINUTES
                        cache latest release tag fetch for this many minutes,
                        before rechecking for latest. Default is 60 minutes
  --purge-days PURGE_DAYS
                        cache release file lists for this number of days after
                        last version referencing it is removed. Default is 30
                        days
  -V                    show pystand version

Commands:
  {install,update,remove,list,show,path}
    install             Install one or more versions from a python-build-
                        standalone release.
    update              Update one, more, or all versions to another release.
    remove              Remove/uninstall one, more, or all versions.
    list                List installed versions and show which have an update
                        available.
    show                Show versions available from a release.
    path                Show path prefix to installed version base directory.

Note you can set default starting global options in
$HOME/.config/pystand-flags.conf.
```

Type `pystand <command> -h` to see specific help/usage for any
individual command:

### Command `install`

```
usage: pystand install [-h] [-r RELEASE] [-f] version [version ...]

Install one or more versions from a python-build-standalone release.

positional arguments:
  version               version to install. E.g. 3.12 or 3.12.3

options:
  -h, --help            show this help message and exit
  -r RELEASE, --release RELEASE
                        install from specified python-build-standalone release
                        (e.g. 20240415), default is latest release
  -f, --force           force install even if already installed
```

### Command `update`

```
usage: pystand update [-h] [-r RELEASE] [-a] [--skip] [version ...]

Update one, more, or all versions to another release.

positional arguments:
  version               version to update (or to skip for --all --skip)

options:
  -h, --help            show this help message and exit
  -r RELEASE, --release RELEASE
                        update to specified release (e.g. 20240415), default
                        is latest release
  -a, --all             update ALL versions
  --skip                skip the specified versions when updating all (only
                        can be specified with --all)
```

### Command `remove`

```
usage: pystand remove [-h] [-a] [--skip] [-r RELEASE] [version ...]

Remove/uninstall one, more, or all versions.

positional arguments:
  version               version to remove (or to skip for --all --skip)

options:
  -h, --help            show this help message and exit
  -a, --all             remove ALL versions
  --skip                skip the specified versions when removing all (only
                        can be specified with --all)
  -r RELEASE, --release RELEASE
                        only remove versions if from specified release (e.g.
                        20240415)
```

### Command `list`

```
usage: pystand list [-h] [-v] [-r RELEASE] [version ...]

List installed versions and show which have an update available.

positional arguments:
  version               only list specified version, else all

options:
  -h, --help            show this help message and exit
  -v, --verbose         explicitly report why a version is not eligible for
                        update
  -r RELEASE, --release RELEASE
                        use specified release (e.g. 20240415) for verbose
                        compare, default is latest release
```

### Command `show`

```
usage: pystand show [-h] [-d] [release]

Show versions available from a release.

positional arguments:
  release              python-build-standalone release to show (e.g.
                       20240415), default is latest release

options:
  -h, --help           show this help message and exit
  -d, --distributions  also show all available distributions for each version
                       from the release
```

### Command `path`

```
usage: pystand path [-h] [-p] version

Show path prefix to installed version base directory.

positional arguments:
  version            version to return path for

options:
  -h, --help         show this help message and exit
  -p, --python-path  return full path to python executable
```

## Installation and Upgrade

Python 3.8 or later is required. Arch Linux users can install [`pystand`
from the AUR](https://aur.archlinux.org/packages/pystand) and skip this
section.

The easiest way to install [`pystand`][pystand] is to use [`pipx`][pipx]
(or [`pipxu`][pipxu]).

```sh
$ pipx install pystand
```

To upgrade:

```sh
$ pipx upgrade pystand
```

To uninstall:

```sh
$ pipx uninstall pystand
```

## Extrapolation of Python Versions

`pystand` extrapolates any version text you specify on the command line
to the latest available corresponding installed or release version. For
example, if you specify `pystand install 3.12` then `pystand` will look
in the release files to find the latest (i.e. highest) available
version of `3.12`, e.g. `3.12.3` (at the time of writing), and will install
that. Of course you can specify the exact version if you wish, e.g.
`3.12.3` but generally you don't need to bother. This is true for any
command that takes a version argument so be aware that this may be
confusing if there are multiple same Python minor versions, e.g.
`3.12.1` and `3.12.3`, installed from different releases. So in that
case you should specify the exact version because e.g. `pystand remove
3.12` will remove `3.12.3` which may not be what you want.

Note, consistent with this, you actually don't need to specify a
minor version, e.g. `pystand install 3` would also install `3.12.3`
(assuming `3.12.3` is the latest available version for Python 3).

After installs or updates or removals,`pystand` also maintains symbolic
links to each latest installed version in it's version directory, e.g. a
symlink `~/.local/share/pystand/versions/3.12` will be created pointing
to `~/.local/share/pystand/versions/3.12.3` so that you can optionally
hard code the symlink directory in places where it can not be set
dynamically (i.e. where using `pystand path` is not an option).

## Command Default Options

You can add default global options to a personal configuration file
`~/.config/pystand-flags.conf`. If that file exists then each line of
options will be concatenated and automatically prepended to your
`pystand` command line arguments. Comments in the file (i.e. `#` and
anything after on a line) are ignored. Type `pystand` to see all
supported options.

The global options: `--distribution`, `--base-dir`, `--cache-minutes`,
`--purge-days` are the only sensible candidates to consider setting as
defaults.

## Command Line Tab Completion

Command line shell [tab
completion](https://en.wikipedia.org/wiki/Command-line_completion) is
automatically enabled on `pystand` commands and options using
[`argcomplete`](https://github.com/kislyuk/argcomplete). You may need to
first (once-only) [activate argcomplete global
completion](https://github.com/kislyuk/argcomplete#global-completion).

## License

Copyright (C) 2024 Mark Blakeney. This program is distributed under the
terms of the GNU General Public License. This program is free software:
you can redistribute it and/or modify it under the terms of the GNU
General Public License as published by the Free Software Foundation,
either version 3 of the License, or any later version. This program is
distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or
FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License at
<http://www.gnu.org/licenses/> for more details.

[pystand]: https://github.com/bulletmark/pystand
[pbs]: https://github.com/indygreg/python-build-standalone
[pbs-rel]: https://github.com/indygreg/python-build-standalone/releases
[pipx]: https://github.com/pypa/pipx
[pipxu]: https://github.com/bulletmark/pipxu
[pyenv]: https://github.com/pyenv/pyenv
[pdm]: https://pdm-project.org/
[pdmpy]: https://pdm-project.org/en/latest/usage/project/#install-python-interpreters-with-pdm
[hatch]: https://hatch.pypa.io/
[hatchpy]: https://hatch.pypa.io/latest/tutorials/python/manage/

<!-- vim: se ai syn=markdown: -->
