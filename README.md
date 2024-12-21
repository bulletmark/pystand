## PYSTAND - Install Python Versions From The Python-Build-Standalone Project
[![PyPi](https://img.shields.io/pypi/v/pystand)](https://pypi.org/project/pystand/)
[![AUR](https://img.shields.io/aur/version/pystand)](https://aur.archlinux.org/packages/pystand/)

[`pystand`][pystand] is a command line tool to facilitate the download,
installation, and update of pre-built Python versions from the
[`python-build-standalone`][pbs] project. The following commands are
provided:

|Command  |Description                                                           |
|---------|----------------------------------------------------------------------|
|`install`|Install one or more versions from a python-build-standalone release   |
|`update` (or `upgrade`) |Update one, more, or all versions to another release   |
|`remove` (or `uninstall`) |Remove/uninstall one, more, or all versions          |
|`list`   |List installed versions and show which have an update available       |
|`show`   |Show versions available from a release                                |
|`path`   |Show path prefix to installed version base directory                  |

By default, Python versions are sourced from the latest
`python-build-standalone` [release][pbs-rel] available (e.g.
"`20240415`") but you can optionally specify any older release. The
required
[distribution](https://gregoryszorc.com/docs/python-build-standalone/main/running.html)
for your machine architecture is normally auto-detected. By default, the
_`install_only_stripped`_ build of the distribution is installed but you
can choose to [install any other
build/distribution](#installing-other-builds/distributions) instead, or
in parallel.

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
3.10.14 @ 20240415 distribution="x86_64-unknown-linux-gnu-install_only_stripped"
3.12.3 @ 20240415 distribution="x86_64-unknown-linux-gnu-install_only_stripped"

$ pystand show
3.8.19 @ 20240415 distribution="x86_64-unknown-linux-gnu-install_only_stripped"
3.9.19 @ 20240415 distribution="x86_64-unknown-linux-gnu-install_only_stripped"
3.10.14 @ 20240415 distribution="x86_64-unknown-linux-gnu-install_only_stripped" (installed)
3.11.9 @ 20240415 distribution="x86_64-unknown-linux-gnu-install_only_stripped"
3.12.3 @ 20240415 distribution="x86_64-unknown-linux-gnu-install_only_stripped" (installed)

$ pystand remove 3.10
Version 3.10.14 @ 20240415 removed.

$ pystand list
3.12.3 @ 20240415 distribution="x86_64-unknown-linux-gnu-install_only_stripped"
```

Here are some examples showing how to use an installed version ..

```sh
# Use uv to create a virtual environment to be run with latest pystand
# installed python 3.12:
$ uv venv -p $(pystand path 3.12) myenv

# Create a regular virtual environment to be run with latest pystand
# installed python 3.12:
$ $(pystand path -p 3.12) -m venv myenv

# Use pipx to install a package to be run with pystand installed python
# specific version 3.11.1:
$ pipx install --python $(pystand path -p 3.11.1) cowsay
```

See detailed usage information in the [Usage](#usage) section that
follows.

Note that similar tools such as [`pdm python`][pdmpy], [`hatch
python`][hatchpy], and [`rye toolchain`][ryepy] also use
[`python-build-standalone`][pbs] build releases. However, `pystand` is
unique because it directly checks the [`python-build-standalone`][pbs]
github site for new [releases][pbs-rel]. Those other tools
require a software update before they can fetch and use new
[`python-build-standalone`][pbs] releases. This means that new Python
versions and updates are always available more quickly from `pystand`
than those other tools.

This utility has been developed and tested on Linux but should also work
on macOS and Windows although has not been tried on those platforms. The
latest documentation and code is available at
https://github.com/bulletmark/pystand.

## Usage

Type `pystand` or `pystand -h` to view the usage summary:

```
usage: pystand [-h] [-D DISTRIBUTION] [-P PREFIX_DIR] [-C CACHE_DIR]
                  [-M CACHE_MINUTES] [--purge-days PURGE_DAYS]
                  [--github-access-token GITHUB_ACCESS_TOKEN] [--no-strip]
                  [-V]
                  {install,update,upgrade,remove,uninstall,list,show,path} ...

Command line tool to download, install, and update pre-built Python versions
from the python-build-standalone project at https://github.com/astral-
sh/python-build-standalone.

options:
  -h, --help            show this help message and exit
  -D DISTRIBUTION, --distribution DISTRIBUTION
                        python-build-standalone distribution. Default is
                        "x86_64_v3-unknown-linux-gnu-install_only_stripped for
                        this host
  -P PREFIX_DIR, --prefix-dir PREFIX_DIR
                        specify prefix dir for storing versions. Default is
                        "$HOME/.local/share/pystand"
  -C CACHE_DIR, --cache-dir CACHE_DIR
                        specify cache dir for downloads. Default is
                        "$HOME/.cache/pystand"
  -M CACHE_MINUTES, --cache-minutes CACHE_MINUTES
                        cache latest YYYYMMDD release tag fetch for this many
                        minutes, before rechecking for latest. Default is 60
                        minutes
  --purge-days PURGE_DAYS
                        cache YYYYMMDD release file lists and downloads for
                        this number of days after last version referencing
                        that release is removed. Default is 90 days
  --github-access-token GITHUB_ACCESS_TOKEN
                        optional Github access token. Can specify to reduce
                        rate limiting.
  --no-strip            do not strip downloaded binaries
  -V, --version         just show pystand version

Commands:
  {install,update,upgrade,remove,uninstall,list,show,path}
    install             Install one or more versions from a python-build-
                        standalone release.
    update (upgrade)    Update one, more, or all versions to another release.
    remove (uninstall)  Remove/uninstall one, more, or all versions.
    list                List installed versions and show which have an update
                        available.
    show                Show versions available from a release.
    path                Show path prefix to installed version base directory.

Some commands offer aliases as shown in brackets above. Note you can set
default starting global options in $HOME/.config/pystand-flags.conf.
```

Type `pystand <command> -h` to see specific help/usage for any
individual command:

### Command `install`

```
usage: pystand install [-h] [-r RELEASE] [-f] [-s] version [version ...]

Install one or more versions from a python-build-standalone release.

positional arguments:
  version               version to install. E.g. 3.12 or 3.12.3

options:
  -h, --help            show this help message and exit
  -r RELEASE, --release RELEASE
                        install from specified python-build-standalone
                        YYYYMMDD release (e.g. 20240415), default is latest
                        release
  -f, --force           force install even if already installed
  -s, --include-source  also install source files if available in distribution
                        download
```

### Command `update`

```
usage: pystand update [-h] [-r RELEASE] [-a] [--skip] [-k] [version ...]

Update one, more, or all versions to another release.

positional arguments:
  version               version to update (or to skip for --all --skip)

options:
  -h, --help            show this help message and exit
  -r RELEASE, --release RELEASE
                        update to specified YYYMMDD release (e.g. 20240415),
                        default is latest release
  -a, --all             update ALL versions
  --skip                skip the specified versions when updating all (only
                        can be specified with --all)
  -k, --keep            keep old version after updating (but only if different
                        version number)

aliases: upgrade
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
                        only remove versions if from specified YYYMMDD release
                        (e.g. 20240415)

aliases: uninstall
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
                        use specified YYYYMMDD release (e.g. 20240415) for
                        verbose compare, default is latest release
```

### Command `show`

```
usage: pystand show [-h] [-l | -r RELEASE] [-a] [re_match]

Show versions available from a release. View available releases and their
distributions at https://github.com/astral-sh/python-build-
standalone/releases.

positional arguments:
  re_match              show only versions+distributions matching this regular
                        expression pattern

options:
  -h, --help            show this help message and exit
  -l, --list            just list recent releases
  -r RELEASE, --release RELEASE
                        python-build-standalone YYYYMMDD release to show (e.g.
                        20240415), default is latest release
  -a, --all             show all available distributions for each version from
                        the release
```

### Command `path`

```
usage: pystand path [-h] [-p] [-r] [-c | version]

Show path prefix to installed version base directory.

positional arguments:
  version            version number to show path for

options:
  -h, --help         show this help message and exit
  -p, --python-path  add path to python executable
  -r, --resolve      fully resolve given version
  -c, --cache-path   just show path to cache dir
```

## Installation and Upgrade

Python 3.8 or later is required. Arch Linux users can install [`pystand`
from the AUR](https://aur.archlinux.org/packages/pystand) and skip this
section.

The easiest way to install [`pystand`][pystand] is to use [`pipx`][pipx]
(or [`pipxu`][pipxu], or [`uv tool`][uvtool]).

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

For all commands except the `path` command, `pystand` extrapolates
version text you specify on the command line to the latest available
corresponding installed or release version. For example, if you specify
`pystand install 3.12` then `pystand` will look in the release files to
find the latest (i.e. highest) available version of `3.12`, e.g.
`3.12.3` (at the time of writing), and will install that. Of course you
can specify the exact version if you wish, e.g. `3.12.3` but generally
you don't need to bother. This is true for any command that takes a
version argument so be aware that this may be confusing if there are
multiple same Python minor versions, e.g. `3.12.1` and `3.12.3`,
installed from different releases. So in that case you should specify
the exact version because e.g. `pystand remove 3.12` will remove
`3.12.3` which may not be what you want.

Note, consistent with this, you actually don't need to specify a
minor version, e.g. `pystand install 3` would also install `3.12.3`
(assuming `3.12.3` is the latest available version for Python 3).

After installs or updates or removals,`pystand` also maintains symbolic
links to each latest installed version in it's version directory, e.g. a
symlink `~/.local/share/pystand/versions/3.12` will be created pointing
to `~/.local/share/pystand/versions/3.12.3` so that you can optionally
hard code the symlink directory in places where it can not be set
dynamically (i.e. where using `pystand path` is not an option).

You can exploit these symlinks when you create virtual environments
using the `pystand path` command (or just hard code the actual link/path
for your environment/platform). E.g. The following creates a virtual
environment which runs with whatever the currently latest installed
Python 3.12 version is:

```sh
# Use uv to create a virtual environment to be run with a symlink to
# currently latest installed python 3.12:
$ uv venv -p $(pystand path 3.12)
```

So if you then update to a new version of Python 3.12 using `pystand`,
e.g. from 3.12.3 to 3.12.4, the virtual environment will automatically
use the new Python version. However, if you for some reason want to
create the virtual environment with a specific version of Python that is
never changed, then just specify that exact version when you create the
virtual environment, e.g.:

```sh
# Use uv to create a virtual environment to be run with specific pystand
# installed python 3.12.2:
$ uv venv -p $(pystand path 3.12.2)

# If you can't be bothered to look up the current latest version, then
# the following command will do the same thing as above because it
# resolves the symlink to the current latest 3.12 version at the time
# you run this command:
$ uv venv -p $(pystand path -r 3.12)
```

## Installing Other Builds/Distributions

The _`install_only_stripped`_ distribution build is installed by default
for your running machine architecture. See description of
distributions/builds
[here](https://gregoryszorc.com/docs/python-build-standalone/main/running.html#obtaining-distributions).
However, you can choose to install other distributions/builds (even for
other architectures). E.g. If we use a standard modern Linux x86_64
machine as an example, the default distribution is
_`x86_64-unknown-linux-gnu-install_only_stripped`_ and the versions for
these are installed by default at `~/.local/share/pystand/<version>`.

However, let's say you want to experiment with the new free-threaded
3.13 build, installed to a different directory. E.g.:

```sh
$ mkdir ./3.13-freethreaded
$ cd ./3.13-freethreaded

$ pystand -P. -D x86_64-unknown-linux-gnu-freethreaded+lto-full install 3.13
$ ./3.13/bin/python -V
Python 3.13.0

$ pystand -P . list
3.13.0 @ 20241016 distribution="x86_64_v4-unknown-linux-gnu-freethreaded+lto-full"
```

Note you can set a different default distribution by specifying
`--distribution` as a [default option](#command-default-options).

### Searching for Available Versions and Distributions

The `show` command can be used to search for distributions as seen in the
following examples.

```sh

List all the versions installed on this system (at the default location):

```sh
$ pystand list
3.8.20 @ 20241002 distribution="x86_64-unknown-linux-gnu-install_only_stripped"
3.9.20 @ 20241016 distribution="x86_64-unknown-linux-gnu-install_only_stripped"
3.12.7 @ 20241016 distribution="x86_64-unknown-linux-gnu-install_only_stripped"
3.13.0 @ 20241016 distribution="x86_64-unknown-linux-gnu-install_only_stripped"
```

The above shows versions 3.9, 3.12, and 3.13 are installed from the latest
release 20241016. Version 3.8 is installed from the previous release
20241002 (and is not available in the latest release otherwise it would
be shown with an update message).

Now show all available versions from the latest release:

```sh
$ pystand show
3.9.20 @ 20241016 distribution="x86_64-unknown-linux-gnu-install_only_stripped" (installed)
3.10.15 @ 20241016 distribution="x86_64-unknown-linux-gnu-install_only_stripped"
3.11.10 @ 20241016 distribution="x86_64-unknown-linux-gnu-install_only_stripped"
3.12.7 @ 20241016 distribution="x86_64-unknown-linux-gnu-install_only_stripped" (installed)
3.13.0 @ 20241016 distribution="x86_64-unknown-linux-gnu-install_only_stripped" (installed)
```

We can see that versions 3.9, 3.12, and 3.13 are already installed (as
we also knew from list output), and that 3.10 and 3.11 are also available.

What is available from the previous release 20241002?

```sh
$ pystand show -r 20241002
3.8.20 @ 20241002 distribution="x86_64-unknown-linux-gnu-install_only_stripped" (installed)
3.9.20 @ 20241002 distribution="x86_64-unknown-linux-gnu-install_only_stripped"
3.10.15 @ 20241002 distribution="x86_64-unknown-linux-gnu-install_only_stripped"
3.11.10 @ 20241002 distribution="x86_64-unknown-linux-gnu-install_only_stripped"
3.12.7 @ 20241002 distribution="x86_64-unknown-linux-gnu-install_only_stripped"
3.13.0rc3 @ 20241002 distribution="x86_64-unknown-linux-gnu-install_only_stripped"
```

Let's install one of the threaded builds of Python 3.13. We can use the
`-a/-all` option to show all available distributions and then give the
`show` command a [regular
expression](https://en.wikipedia.org/wiki/Regular_expression) to filter
the output (this is really just a shorthand for piping the output of
`show -a` to grep). E.g.:

```sh
$ pystand show -a 3.13.*x86_64.*unknown-linux-gnu.*thread
3.13.0 @ 20241016 distribution="x86_64-unknown-linux-gnu-freethreaded+debug-full"
3.13.0 @ 20241016 distribution="x86_64-unknown-linux-gnu-freethreaded+pgo+lto-full"
3.13.0 @ 20241016 distribution="x86_64-unknown-linux-gnu-freethreaded+pgo-full"
3.13.0 @ 20241016 distribution="x86_64_v2-unknown-linux-gnu-freethreaded+debug-full"
3.13.0 @ 20241016 distribution="x86_64_v2-unknown-linux-gnu-freethreaded+pgo+lto-full"
3.13.0 @ 20241016 distribution="x86_64_v2-unknown-linux-gnu-freethreaded+pgo-full"
3.13.0 @ 20241016 distribution="x86_64_v3-unknown-linux-gnu-freethreaded+debug-full"
3.13.0 @ 20241016 distribution="x86_64_v3-unknown-linux-gnu-freethreaded+pgo+lto-full"
3.13.0 @ 20241016 distribution="x86_64_v3-unknown-linux-gnu-freethreaded+pgo-full"
3.13.0 @ 20241016 distribution="x86_64_v4-unknown-linux-gnu-freethreaded+debug-full"
3.13.0 @ 20241016 distribution="x86_64_v4-unknown-linux-gnu-freethreaded+lto-full"
3.13.0 @ 20241016 distribution="x86_64_v4-unknown-linux-gnu-freethreaded+noopt-full"
```

So let's install the
`x86_64_v3-unknown-linux-gnu-freethreaded+pgo+lto-full` build of Python
3.13 (to the default location):

```sh
$ pystand -D x86_64_v3-unknown-linux-gnu-freethreaded+pgo+lto-full install 3.13
Version "3.13.0" is already installed.
```

An error is given because the version is already installed. We can
overwrite that with the `-f/--force` option:

```sh
$ pystand -D x86_64_v3-unknown-linux-gnu-freethreaded+pgo+lto-full install -f 3.13
Version 3.13.0 @ 20241016 installed.
```

Now we can see the new version distribution is installed:

```sh

$ pystand list
3.8.20 @ 20241002 distribution="x86_64-unknown-linux-gnu-install_only_stripped"
3.9.20 @ 20241016 distribution="x86_64-unknown-linux-gnu-install_only_stripped"
3.12.7 @ 20241016 distribution="x86_64-unknown-linux-gnu-install_only_stripped"
3.13.0 @ 20241016 distribution="x86_64_v3-unknown-linux-gnu-freethreaded+pgo+lto-full"

$ pystand show
3.9.20 @ 20241016 distribution="x86_64-unknown-linux-gnu-install_only_stripped" (installed)
3.10.15 @ 20241016 distribution="x86_64-unknown-linux-gnu-install_only_stripped"
3.11.10 @ 20241016 distribution="x86_64-unknown-linux-gnu-install_only_stripped"
3.12.7 @ 20241016 distribution="x86_64-unknown-linux-gnu-install_only_stripped" (installed)
3.13.0 @ 20241016 distribution="x86_64-unknown-linux-gnu-install_only_stripped"
3.13.0 @ 20241016 distribution="x86_64_v3-unknown-linux-gnu-freethreaded+pgo+lto-full" (installed)
```

Note that `pystand` caches all downloaded files (at least for a period
specified by `--purge-days`) so you can easily switch between different
versions/distributions quite quickly. You can also choose to install any
distribution/build in a specific directory using the `-P/--prefix-dir`
global option if you want to keep different distributions separate and
available in parallel.

## Command Default Options

You can add default global options to a personal configuration file
`~/.config/pystand-flags.conf`. If that file exists then each line of
options will be concatenated and automatically prepended to your
`pystand` command line arguments. Comments in the file (i.e. `#` and
anything after on a line) are ignored. Type `pystand` to see all
supported options.

The global options: `--distribution`, `--prefix-dir`, `--cache-dir`,
`--cache-minutes`, `--purge-days`, `--github-access-token`,
`--no-strip`, are the only sensible candidates to consider setting
as defaults.

## Github API Rate Limiting

This tool minimises and caches Github API responses and file downloads
from the [`python-build-standalone`][pbs] repository. However, if you
install many different versions particularly across various releases,
you may get rate limited by Github so the command can block and you will
see "backoff" messages reported. You can create a Github access token to
gain increased rate limits. Create a token in your Github account under
`Settings -> Developer settings -> Personal access tokens`. You can use
either a Github "fine-grained" or "classic" token. Specify the token on
the command line with `--github-access-token`, or set that as a [default
option](#command-default-options).

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
[pbs]: https://github.com/astral-sh/python-build-standalone
[pbs-rel]: https://github.com/astral-sh/python-build-standalone/releases
[pipx]: https://github.com/pypa/pipx
[pipxu]: https://github.com/bulletmark/pipxu
[uvtool]: https://docs.astral.sh/uv/guides/tools/#installing-tools
[pyenv]: https://github.com/pyenv/pyenv
[pdm]: https://pdm-project.org/
[pdmpy]: https://pdm-project.org/en/latest/usage/project/#install-python-interpreters-with-pdm
[hatch]: https://hatch.pypa.io/
[hatchpy]: https://hatch.pypa.io/latest/tutorials/python/manage/
[ryepy]: https://rye.astral.sh/guide/toolchains/#fetching-toolchains

<!-- vim: se ai syn=markdown: -->
