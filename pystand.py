#!/usr/bin/python3
# PYTHON_ARGCOMPLETE_OK
"""
Command line tool to download, install, and update pre-built Python
versions from the python-build-standalone project at
https://github.com/astral-sh/python-build-standalone.
"""

from __future__ import annotations

import itertools
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Iterable, Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import argcomplete
import filelock
import platformdirs
from argparse_from_file import ArgumentParser, Namespace
from packaging.version import parse as parse_version

REPO = 'python-build-standalone'
GITHUB_REPO = f'astral-sh/{REPO}'
GITHUB_SITE = f'https://github.com/{GITHUB_REPO}'
LATEST_RELEASES = f'{GITHUB_SITE}/releases.atom'
LATEST_RELEASE_TAG = f'{GITHUB_SITE}/releases/latest'
DOC = 'https://gregoryszorc.com/docs/python-build-standalone/main/'

# Sample release tag for documentation/usage examples
SAMPL_RELEASE = '20240415'

PROG = Path(__file__).stem

# Default distributions for various platforms
DISTRIBUTIONS = {
    ('Linux', 'x86_64'): 'x86_64_v3-unknown-linux-gnu-install_only_stripped',
    ('Linux', 'aarch64'): 'aarch64-unknown-linux-gnu-install_only_stripped',
    ('Linux', 'arm64'): 'aarch64-unknown-linux-gnu-install_only_stripped',
    ('Linux', 'armv7l'): 'armv7-unknown-linux-gnueabihf-install_only_stripped',
    ('Linux', 'armv8l'): 'armv7-unknown-linux-gnueabihf-install_only_stripped',
    ('Darwin', 'x86_64'): 'x86_64-apple-darwin-install_only_stripped',
    ('Darwin', 'aarch64'): 'aarch64-apple-darwin-install_only_stripped',
    ('Darwin', 'arm64'): 'aarch64-apple-darwin-install_only_stripped',
    ('Windows', 'x86_64'): 'x86_64-pc-windows-msvc-shared-install_only_stripped',
    ('Windows', 'i686'): 'i686-pc-windows-msvc-shared-install_only_stripped',
    ('Windows', 'aarch64'): 'aarch64-pc-windows-msvc-install_only_stripped',
    ('Windows', 'arm64'): 'aarch64-pc-windows-msvc-install_only_stripped',
}

CERTS = ('system', 'certifi', 'none')

# Define ANSI escape sequences for colors
# Refer https://en.wikipedia.org/wiki/ANSI_escape_code#Colors
COLORS = [
    '\033[32m',  # green
    '\033[33m',  # yellow
    '\033[35m',  # magenta
    '\033[34m',  # blue
    '\033[36m',  # cyan
    '\033[31m',  # red
    '\033[37m',  # white
    '\033[39m',  # reset to default color
]


class ColorTable:
    "Base class for color tables"

    def __init__(self, initval: str, no_color: bool) -> None:
        self.table = None if no_color else {self.parse_key(initval): COLORS[0]}
        self.next = itertools.cycle(COLORS[1:-1])

    def get_color(self, text: str) -> str:
        "Assign a new color by cycling through the available colors"
        if not self.table:
            return text

        if not (color := self.table.get(key := self.parse_key(text))):
            self.table[key] = color = next(self.next)

        return f'{color}{text}{COLORS[-1]}'

    def parse_key(self, text: str) -> str:
        "Parse text for color table key, default is full text"
        return text


class ColorRel(ColorTable):
    "Return colored release version string"

    def format(self, version: str, release: str) -> str:
        "Return a formatted release version string"
        return f'{version} @ {self.get_color(release)}'


class ColorDist(ColorTable):
    "Return colored distribution string"

    def format(self, dist: str) -> str:
        return f'distribution="{self.get_color(dist)}"'

    def parse_key(self, text: str) -> str:
        "Extract key for distribution color"
        return text.split('-', 1)[0]


def is_admin() -> bool:
    "Check if we are running as root"
    if platform.system() == 'Windows':
        import ctypes

        return ctypes.windll.shell32.IsUserAnAdmin() != 0  # type: ignore

    return os.geteuid() == 0


def get_version() -> str:
    "Return the version of this package"
    from importlib.metadata import version

    try:
        ver = version(PROG)
    except Exception:
        ver = 'unknown'

    return ver


def get_major_version(args: Namespace) -> str | None:
    '"Return the latest major version installed"'
    vers = sorted(f.name for f in args._versions.glob('[3-9]'))
    return vers[-1] if vers else None


def get_json(file: Path) -> dict[str, Any]:
    from json import load

    'Get JSON data from given file'
    try:
        with file.open() as fp:
            return load(fp)
    except Exception:
        pass

    return {}


def set_json(file: Path, data: dict[str, Any]) -> str | None:
    "Set JSON data to given file"
    from json import dump

    try:
        with file.open('w') as fp:
            dump(data, fp, indent=2)
    except Exception as e:
        return str(e)

    return None


# The gh handle is an opaque github instance handle
get_gh_handle = None


def get_gh(args: Namespace) -> Any:
    "Return a GitHub handle"
    # The gh handle is a global to lazily create it only if/when needed
    global get_gh_handle
    if get_gh_handle:
        return get_gh_handle

    if args.github_access_token:
        from github.Auth import Token

        auth = Token(args.github_access_token)
    else:
        auth = None

    # Save this handle globally for future use
    from github import Github

    get_gh_handle = Github(auth=auth)
    return get_gh_handle


def rm_path(path: Path) -> bool:
    "Remove the given path"
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()
    else:
        return False

    return True


def register_zst() -> None:
    "Register custom zstandard unpacker"
    import tarfile

    from zstandard import ZstdDecompressor

    def unpack_zst(filename: str, extract_dir: str) -> None:
        "Unpack a zstandard compressed tar"
        with open(filename, 'rb') as compressed:
            dctx = ZstdDecompressor()
            with dctx.stream_reader(compressed) as reader:
                with tarfile.open(fileobj=reader, mode='r|') as tar:
                    tar.extractall(path=extract_dir)

    shutil.register_unpack_format('zst', ['.zst'], unpack_zst)


def fetch(args: Namespace, release: str, url: str, tdir: Path) -> str | None:
    "Fetch and unpack a release file"
    from urllib.parse import unquote, urlparse

    error = None
    tmpdir = tdir.with_name(f'{tdir.name}-tmp')
    rm_path(tmpdir)
    tmpdir.mkdir(parents=True)

    filename_q = Path(urlparse(url).path).name
    filename = unquote(filename_q)
    cache_file = args._downloads / release / filename
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    if not cache_file.exists():
        try:
            with urlopen(url, context=args._cert) as urlp, cache_file.open('wb') as fp:
                shutil.copyfileobj(urlp, fp)
        except Exception as e:
            error = f'Failed to fetch "{url}": {e}'

    if error:
        rm_path(cache_file)
    else:
        # Register custom zstandard handler (only if Python < 3.14 which has built-in support)
        if filename.endswith('.zst') and sys.version_info < (3, 14):
            register_zst()

        try:
            shutil.unpack_archive(cache_file, tmpdir)
        except Exception as e:
            error = f'Failed to unpack "{url}": {e}'
        else:
            pdir = tmpdir / 'python'
            idir = pdir / 'install'
            if idir.exists():
                # This is a source distribution, copy the source if
                # requested
                if args.include_source:
                    srcdir = idir / 'src'
                    for subpath in pdir.iterdir():
                        if subpath.name != idir.name:
                            srcdir.mkdir(parents=True, exist_ok=True)
                            subpath.replace(srcdir / subpath.name)

                pdir = idir

            pdir.replace(tdir)

    rm_path(tmpdir)
    return error


def is_release_version(version: str) -> bool:
    "Check if a string is a formal Python release tag"
    return version.replace('.', '').isdigit()


class VersionMatcher:
    "Match a version string to a list of versions"

    def __init__(self, seq: Iterable[str]) -> None:
        self.seq = sorted(seq, key=parse_version, reverse=True)

    def match(self, version: str | None, *, upgrade: bool = False) -> str | None:
        "Return full version string given a [possibly] part version prefix"

        # If no version specified, return the latest release version
        if not version:
            for version in self.seq:
                if is_release_version(version):
                    return version
            return None

        if version in self.seq:
            return version

        is_release = is_release_version(version)
        major_only = '.' not in version

        if major_only:
            upgrade = True
        elif upgrade:
            version = version.rsplit('.', 1)[0]

        if not version.endswith('.'):
            version += '.'

        # Only allow upgrade of formal release to another formal
        # release.
        for full_version in self.seq:
            if full_version.startswith(version):
                if not upgrade or not is_release or is_release_version(full_version):
                    return full_version

        return None


def iter_versions(args: Namespace) -> Iterator[Path]:
    "Iterate over all version dirs"
    for f in args._versions.iterdir():
        if (
            f.is_dir()
            and not f.is_symlink()
            and f.name[0] != '.'
            and f.name[0].isdigit()
        ):
            yield f


def get_version_names(args: Namespace) -> list[str]:
    "Return a list of validated version names based on command line args"
    if args.all:
        if not args.skip and args.version:
            args.parser.error(
                'Can not specify versions with --all unless also specifying --skip.'
            )
    else:
        if args.skip:
            args.parser.error('--skip can only be specified with --all.')

        if not args.version:
            args.parser.error('Must specify at least one version, or --all.')

    all_names = set(f.name for f in iter_versions(args))

    # Upconvert all user specified partial version names to full version names
    matcher = VersionMatcher(all_names)
    versions = [(matcher.match(v) or v) for v in args.version]

    given = set(versions)

    if unknown := given - all_names:
        s = 's' if len(unknown) > 1 else ''
        unknowns = [f'"{u}"' for u in unknown]
        sys.exit(f'Error: version{s} {", ".join(unknowns)} not found.')

    return sorted(all_names - given, key=parse_version) if args.all else versions


def check_release_tag(release: str) -> str | None:
    "Check the specified release tag is valid"
    if not release.isdigit() or len(release) != len(SAMPL_RELEASE):
        return 'Release must be a YYYYMMDD string.'

    try:
        _ = date.fromisoformat(f'{release[:4]}-{release[4:6]}-{release[6:]}')
    except Exception:
        return 'Release must be a YYYYMMDD date string.'

    return None


# Note we use a simple direct URL fetch to get the latest tag info
# because it is much faster than using the GitHub API, and has no
# rate-limits.
def fetch_tags(args: Namespace) -> Iterator[tuple[str, str]]:
    "Fetch the latest release tags from the GitHub release atom feed"
    import xml.etree.ElementTree as et

    try:
        with urlopen(LATEST_RELEASES, context=args._cert) as url:
            data = et.parse(url).getroot()
    except Exception:
        sys.exit('Failed to fetch latest YYYYMMDD release atom file.')

    for child in data.iter():
        for entry in child.findall('{http://www.w3.org/2005/Atom}entry'):
            tl = entry.findtext('{http://www.w3.org/2005/Atom}title')
            dt = entry.findtext('{http://www.w3.org/2005/Atom}updated')
            if tl and dt:
                yield tl, dt


def fetch_tag_latest(args: Namespace) -> str:
    "Fetch the latest release tag from the GitHub"
    try:
        with urlopen(LATEST_RELEASE_TAG, context=args._cert) as url:
            data = url.geturl()
    except Exception:
        sys.exit('Failed to fetch latest YYYYMMDD release tag.')

    return data.split('/')[-1]


def get_release_tag(args: Namespace) -> str:
    "Return the release tag, or latest if not specified"
    if (
        hasattr(args, 'release')
        and (release := args.release)
        and isinstance(release, str)
    ):
        if err := check_release_tag(release):
            sys.exit(err)

        return release

    if args._latest_release.exists():
        stat = args._latest_release.stat()
        if time.time() < (stat.st_mtime + int(args.cache_minutes * 60)):
            return args._latest_release.read_text().strip()

    if not (tag := fetch_tag_latest(args)):
        sys.exit('Latest YYYYMMDD release tag timestamp file is unavailable.')

    args._latest_release.write_text(tag + '\n')
    return tag


def add_file(files: dict[str, Any], tag: str, name: str, url: str) -> None:
    "Extract the implementation, version, and architecture from a filename"
    if name.endswith('.tar.zst'):
        name = name[:-8]
    elif name.endswith('.tar.gz'):
        name = name[:-7]
    else:
        return

    impl, ver, arch = name.split('-', 2)

    # Modern releases have a '+' in the name to separate the version
    if '+' in ver:
        ver, filetag = ver.split('+')
        if filetag != tag:
            return

    if impl not in files:
        files[impl] = {}

    vers = files[impl]

    if ver not in vers:
        vers[ver] = {}

    vers[ver][arch] = url


def get_release_files(args, tag) -> dict[str, Any]:
    "Return the release files for the given tag"
    # Look for tag data in our release cache
    jfile = args._releases / tag
    if not (files := get_json(jfile)):
        # May have read this release before but it has no assets
        if jfile.exists():
            return {}

        # Not in cache so fetch it (and also store in cache)
        gh = get_gh(args)
        try:
            release = gh.get_repo(GITHUB_REPO).get_release(tag)
        except Exception as e:
            print(f'Error: {str(e)}', file=sys.stderr)
            return {}

        # Iterate over the release assets and store pertinent files in a
        # dict to return.
        for asset in release.get_assets():
            add_file(files, tag, asset.name, asset.browser_download_url)

        if not files:
            sys.exit(f'Failed to fetch any files for release {tag}')

        if error := set_json(jfile, files):
            sys.exit(f'Failed to write release {tag} file {jfile}: {error}')

    return files.get(args._implementation, {})


def update_version_symlinks(args: Namespace) -> None:
    "Create/update symlinks pointing to latest version"
    base = args._versions
    if not base.exists():
        return

    # Record all the existing symlinks and version dirs
    oldlinks = {}
    vers = []
    for path in base.iterdir():
        if path.name[0] != '.' and path.name[0].isdigit():
            if path.is_symlink():
                oldlinks[path.name] = os.readlink(str(path))
            else:
                vers.append(path.name)

    # Create a map of all the new major version links
    newlinks_all = defaultdict(set)
    pre_releases = set(v for v in vers if not is_release_version(v))
    for namevers in vers:
        while '.' in namevers[:-1]:
            namevers_major = namevers.rsplit('.', maxsplit=1)[0]
            newlinks_all[namevers_major].add(namevers)

            if namevers in pre_releases:
                pre_releases.add(namevers_major)

            namevers = namevers_major

    # Find the latest version for each major version, but ensure we
    # don't link a major release to pre-released version, if it also can
    # point to released versions.
    newlinks = {}
    for ver, cands in newlinks_all.items():
        if ver in pre_releases and (rels := (cands - pre_releases)):
            cands = rels

        newlinks[ver] = sorted(cands, key=parse_version)[-1]

    # Remove all old or invalid existing links
    for name, tgt in oldlinks.items():
        new_tgt = newlinks.get(name)
        if not new_tgt or new_tgt != tgt:
            (base / name).unlink()

    # Create all needed new links
    for name, tgt in newlinks.items():
        old_tgt = oldlinks.get(name)
        if not old_tgt or old_tgt != tgt:
            (base / name).symlink_to(tgt, target_is_directory=True)


def keeplist(args: Namespace) -> set[str]:
    "Return a set of release names to keep"
    keep = {
        r for v in iter_versions(args) if (r := get_json(v / args._data).get('release'))
    }

    # Add current release to keep list (even if not currently installed)
    if args._latest_release.exists():
        keep.add(args._latest_release.read_text().strip())

    return keep


def purge_unused_releases(args: Namespace) -> None:
    "Purge old releases that are no longer needed and have expired"
    # Want to keep releases for versions that we currently have installed
    keep = keeplist(args)

    # Purge any release lists that are no longer used and have expired
    now_secs = time.time()
    end_secs = args.purge_days * 86400
    for path in args._releases.iterdir():
        if path.name not in keep:
            if (path.stat().st_mtime + end_secs) < now_secs:
                path.unlink()
            else:
                keep.add(path.name)

    # Purge any downloads for releases that have expired
    if args._downloads.is_dir():
        for path in args._downloads.iterdir():
            if path.name not in keep:
                rm_path(path)


def show_list(args: Namespace) -> None:
    "Show a list of available releases"
    latest = parse_version(args._release)
    releases = {r: d for r, d in fetch_tags(args)}
    cached = set(p.name for p in args._releases.iterdir())
    for release in sorted(cached.union(releases)):
        if args.re_match and not re.search(args.re_match, release):
            continue

        if dt_str := releases.get(release):
            dts = (
                datetime.fromisoformat(dt_str)
                .astimezone()
                .isoformat(sep='_', timespec='minutes')
            )
        else:
            dts = '......................'

        if release in cached:
            ddir = args._downloads / release
            count = len(list(ddir.iterdir())) if ddir.exists() else 0
            app = f' cached + {count} downloaded files' if count > 0 else ' cached'
        else:
            app = ''

        pre = ' pre-release' if parse_version(release) > latest else ''

        print(f'{release} {dts}{app}{pre}')


def get_title(desc: str) -> str:
    "Return single title line from description"
    res = []
    for line in desc.splitlines():
        line = line.strip()
        res.append(line)
        if line.endswith('.'):
            return ' '.join(res)

    sys.exit('Must end description with a full stop.')


def remove(args: Namespace, version: str) -> None:
    "Remove a version"
    vdir = args._versions / version
    if not vdir.exists():
        return

    # Touch the associated release file to ensure it lives until the
    # full purge time has expired if this was the last version using it
    if release := get_json(vdir / args._data).get('release'):
        (args._releases / release).touch()

    shutil.rmtree(vdir)


def strip_binaries(vdir: Path, distribution: str) -> bool:
    "Strip binaries from files in a version directory"

    # Only run the strip command on Linux hosts and for Linux distributions
    was_stripped = False
    if platform.system() == 'Linux' and '-linux-' in distribution:
        for path in ('lib',):
            base = vdir / path
            if not base.is_dir():
                continue

            for file in base.iterdir():
                if not file.is_symlink() and file.is_file():
                    cmd = f'strip -p --strip-unneeded {file}'.split()
                    try:
                        subprocess.run(cmd, stderr=subprocess.DEVNULL)
                    except Exception:
                        pass
                    else:
                        was_stripped = True

    return was_stripped


def install(
    args: Namespace, vdir: Path, release: str, distribution: str, files: dict[str, Any]
) -> str | None:
    "Install a version"
    version = vdir.name

    if not (url := files[version].get(distribution)):
        return (
            f'Arch "{distribution}" not found for release {release} version {version}.'
        )

    tmpdir = args._versions / f'.{version}-tmp'
    rm_path(tmpdir)
    tmpdir.mkdir(parents=True)

    if not (error := fetch(args, release, url, tmpdir)):
        data = {'release': release, 'distribution': distribution}

        if not args.no_strip and strip_binaries(tmpdir, distribution):
            data['stripped'] = 'true'

        if error := set_json(tmpdir / args._data, data):
            error = f'Failed to write {version} data file: {error}'

    if error:
        shutil.rmtree(tmpdir)
    else:
        remove(args, version)
        tmpdir.replace(vdir)

    return error


def to_human(num, prec: int | None = None) -> str:
    "Convert a number of bytes to a human-readable format"
    units = ('B', 'K', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y')
    for unit in units:
        if abs(num) < 1024.0 or unit == units[-1]:
            return f'{round(num, prec)}{unit}'
        num /= 1024.0

    return ''


def show_cache_size(path: Path, args: Namespace) -> None:
    "Show the size of the cache directory"
    total = 0
    for spath in sorted(path.iterdir()):
        size = (
            sum(p.stat().st_size for p in spath.iterdir())
            if spath.is_dir()
            else spath.stat().st_size
        )
        total += size
        size_str = f'{size}B' if args.no_human_readable else to_human(size)
        name = (
            str(spath) if spath.is_dir() else f'{spath.parent.name}{os.sep}{spath.name}'
        )
        print(f'{size_str}\t{name}')

    if not args.no_total:
        size_str = f'{total}B' if args.no_human_readable else to_human(total, 2)
        print(f'{size_str}\tTOTAL')


def create_cert(option: str) -> ssl.SSLContext | None:
    "Create an SSL context for HTTPS connections based on the specified certificate store"

    if not option or option == 'system':
        return None

    if option == 'certifi':
        import certifi

        return ssl.create_default_context(cafile=certifi.where())

    assert option == 'none'
    return ssl._create_unverified_context()


def run_uv(args: Namespace, cmd: list[str], cmdopts: list[str]) -> str | None:
    "Run a uv command with the specified or latest installed python version"
    if not (vers := (args.python or get_major_version(args))):
        return 'No installed python version found.'

    py = args._versions / vers
    if not py.is_dir():
        return f'No installed python {py.name} version found.'

    # Resolve to at least minor version if only major version specified
    if '.' not in py.name:
        py = py.resolve()
        py = py.with_name(py.stem)

    subprocess.run(cmd + ['-p', py] + cmdopts)


def main() -> str | None:
    "Main code"
    distro_default = DISTRIBUTIONS.get((platform.system(), platform.machine()))
    distro_help = distro_default or '?unknown?'

    p = '/opt' if is_admin() else platformdirs.user_data_dir()
    prefix_dir = str(Path(p, PROG))
    cache_dir = platformdirs.user_cache_path() / PROG

    # Parse arguments
    opt = ArgumentParser(
        description=__doc__,
        epilog='Some commands offer aliases as shown in parentheses above. '
        'Note you can set default starting global options in #FROM_FILE_PATH#.',
    )

    # Set up main/global arguments
    opt.add_argument(
        '-D',
        '--distribution',
        help=f'{REPO} distribution. Default is "{distro_help}" for this host. '
        f'Run "{PROG} show -a" to see all distributions. See {DOC}',
    )
    opt.add_argument(
        '-P',
        '--prefix-dir',
        default=prefix_dir,
        help='specify prefix dir for storing versions. Default is "%(default)s".',
    )
    opt.add_argument(
        '-C',
        '--cache-dir',
        default=str(cache_dir),
        help='specify cache dir for downloads. Default is "%(default)s".',
    )
    opt.add_argument(
        '-M',
        '--cache-minutes',
        default=60,
        type=float,
        help='cache latest YYYYMMDD release tag fetch for this '
        'many minutes, before rechecking for latest. '
        'Default is %(default)d minutes.',
    )
    opt.add_argument(
        '--purge-days',
        default=90,
        type=int,
        help='cache YYYYMMDD release file lists and downloads for '
        'this number of days after last version referencing that '
        'release is removed. Default is %(default)d days.',
    )
    opt.add_argument(
        '--github-access-token',
        help='optional Github access token. Can specify to reduce rate limiting.',
    )
    opt.add_argument(
        '--no-strip', action='store_true', help='do not strip downloaded binaries'
    )
    opt.add_argument(
        '--no-color', action='store_true', help='do not use color in output'
    )
    opt.add_argument(
        '--cert',
        choices=CERTS,
        help=f'specify which SSL certificates to use for HTTPS requests. Default="{CERTS[0]}".',
    )
    opt.add_argument(
        '-V', '--version', action='store_true', help=f'just show {PROG} version'
    )
    cmd = opt.add_subparsers(title='Commands', dest='cmdname')

    # Add each command ..
    for name in globals():
        if not name[0].islower() or not name.endswith('_'):
            continue

        cls = globals()[name]
        name = name[:-1]

        if hasattr(cls, 'doc'):
            desc = cls.doc.strip()
        elif cls.__doc__:
            desc = cls.__doc__.strip()
        else:
            return f'Must define a docstring for command class "{name}".'

        aliases = cls.aliases if hasattr(cls, 'aliases') else []
        title = get_title(desc)
        cmdopt = cmd.add_parser(name, description=desc, help=title, aliases=aliases)

        # Set up this commands own arguments, if it has any
        if hasattr(cls, 'init'):
            cls.init(cmdopt)

        # Set the function to call
        cmdopt.set_defaults(func=cls.run, name=name, parser=cmdopt)

    # Command arguments are now defined, so we can set up argcomplete
    argcomplete.autocomplete(opt)
    args = opt.parse_args()

    if 'func' not in args:
        if args.version:
            print(get_version())
            return None

        opt.print_help()
        return None

    distribution = args.distribution or distro_default
    if not distribution:
        return 'Unknown system + machine distribution. Please specify using -D/--distribution option.'

    # Only use color for terminal output
    if not sys.stdout.isatty():
        args.no_color = True

    # Keep some useful info in the namespace passed to the command
    prefix_dir = Path(args.prefix_dir).expanduser().resolve()
    cache_dir = Path(args.cache_dir).expanduser().resolve()

    args._implementation = 'cpython'  # at the moment, only support CPython
    args._distribution = distribution
    args._fmtdist = ColorDist(distribution, args.no_color).format
    args._data = f'{PROG}.json'

    args._versions = prefix_dir
    args._versions.mkdir(parents=True, exist_ok=True)
    args._downloads = cache_dir / 'downloads'
    args._downloads.mkdir(parents=True, exist_ok=True)
    args._releases = cache_dir / 'releases'
    args._releases.mkdir(parents=True, exist_ok=True)
    args._latest_release = cache_dir / 'latest_release'
    args._cert = create_cert(args.cert)

    # Only allow one instance of this program to run (to read/write prefix and cache dirs)
    locks = [filelock.FileLock(d / '.lock') for d in (prefix_dir, cache_dir)]

    try:
        with locks[0].acquire(blocking=False), locks[1].acquire(blocking=False):
            args._release = get_release_tag(args)
            args._fmtrel = ColorRel(args._release, args.no_color).format
            result = args.func(args)
            purge_unused_releases(args)
            update_version_symlinks(args)
    except filelock.Timeout:
        return f'ERROR: Another instance of {PROG} is already running.'

    return result


# COMMAND
class install_:
    doc = f'Install one, more, or all versions from a {REPO} release.'

    @staticmethod
    def init(parser: ArgumentParser) -> None:
        parser.add_argument(
            '-r',
            '--release',
            help=f'install from specified {REPO} '
            f'YYYYMMDD release (e.g. {SAMPL_RELEASE}), '
            'default is latest release',
        )
        parser.add_argument(
            '-a', '--all', action='store_true', help='install ALL versions from release'
        )
        parser.add_argument(
            '-A',
            '--all-prerelease',
            action='store_true',
            help='install ALL versions from release, including pre-releases',
        )
        parser.add_argument(
            '--skip',
            action='store_true',
            help='skip the specified versions when '
            'installing all (only can be specified with --all)',
        )
        parser.add_argument(
            '-f',
            '--force',
            action='store_true',
            help='force install even if already installed',
        )
        parser.add_argument(
            '-s',
            '--include-source',
            action='store_true',
            help='also install source files if available in distribution download',
        )
        parser.add_argument(
            'version', nargs='*', help='version to install. E.g. 3.12 or 3.12.3'
        )

    @staticmethod
    def run(args: Namespace) -> str | None:
        release = args._release
        files = get_release_files(args, release)
        if not files:
            return f'Release "{release}" not found, or has no compatible files.'

        matcher = VersionMatcher(files)

        if args.all_prerelease:
            args.all = True

        if args.all:
            if not args.skip and args.version:
                args.parser.error(
                    'Can not specify versions with --all unless also specifying --skip.'
                )

            skips = set(v for ver in args.version if (v := matcher.match(ver)))

            args.version = [
                v
                for v in files
                if (args.all_prerelease or is_release_version(v)) and v not in skips
            ]

        else:
            if args.skip:
                args.parser.error('--skip can only be specified with --all.')

            if not args.version:
                args.parser.error('Must specify at least one version, or --all.')

        for version in args.version:
            full_version = matcher.match(version)
            if not full_version:
                return f'Version {args._fmtrel(version, release)} not found.'

            version = full_version
            vdir = args._versions / version

            if vdir.exists() and not args.force:
                print(
                    f'Version {args._fmtrel(version, release)} is already installed.',
                    file=sys.stderr,
                )
                continue

            if error := install(args, vdir, release, args._distribution, files):
                return error

            print(f'Version {args._fmtrel(version, release)} installed.')


# COMMAND
class update_:
    "Update one, more, or all versions to another release."

    aliases = ['upgrade']

    @staticmethod
    def init(parser: ArgumentParser) -> None:
        parser.add_argument(
            '-r',
            '--release',
            help='update to specified YYYMMDD release (e.g. '
            f'{SAMPL_RELEASE}), default is latest release',
        )
        parser.add_argument(
            '-a', '--all', action='store_true', help='update ALL versions'
        )
        parser.add_argument(
            '--skip',
            action='store_true',
            help='skip the specified versions when '
            'updating all (only can be specified with --all)',
        )
        parser.add_argument(
            '-k',
            '--keep',
            action='store_true',
            help='keep old version after updating (but only '
            'if different version number)',
        )
        parser.add_argument(
            'version', nargs='*', help='version to update (or to skip for --all --skip)'
        )

    @staticmethod
    def run(args: Namespace) -> str | None:
        release_target = args._release
        files = get_release_files(args, release_target)
        if not files:
            return f'Release "{release_target}" not found.'

        matcher = VersionMatcher(files)
        for version in get_version_names(args):
            vdir = args._versions / version
            if not (data := get_json(vdir / args._data)):
                continue

            if (release := data.get('release')) == release_target:
                continue

            if not (nextver := matcher.match(version, upgrade=True)):
                continue

            distribution = data.get('distribution')
            if not distribution or distribution not in files.get(nextver, {}):
                continue

            if nextver == version and args.keep and release:
                print(
                    f'Error: {args._fmtrel(version, release)} would not be kept '
                    f'if update to {args._fmtrel(nextver, release_target)} '
                    f'{args._fmtdist(distribution)}',
                    file=sys.stderr,
                )
                continue

            new_vdir = args._versions / nextver
            if not release or (nextver != version and new_vdir.exists()):
                continue

            print(
                f'{args._fmtrel(version, release)} updating to '
                f'{args._fmtrel(nextver, release_target)} '
                f'{args._fmtdist(distribution)} ..'
            )

            # If the source was originally included, then include it in
            # the update.
            args.include_source = (vdir / 'src').is_dir()

            if error := install(args, new_vdir, release_target, distribution, files):
                return error

            if nextver != version and not args.keep:
                remove(args, version)


# COMMAND
class remove_:
    "Remove/uninstall one, more, or all versions."

    aliases = ['uninstall']

    @staticmethod
    def init(parser: ArgumentParser) -> None:
        parser.add_argument(
            '-a', '--all', action='store_true', help='remove ALL versions'
        )
        parser.add_argument(
            '--skip',
            action='store_true',
            help='skip the specified versions when '
            'removing all (only can be specified with --all)',
        )
        parser.add_argument(
            '-r',
            '--release',
            help='only remove versions if from specified '
            f'YYYMMDD release (e.g. {SAMPL_RELEASE})',
        )
        parser.add_argument(
            'version', nargs='*', help='version to remove (or to skip for --all --skip)'
        )

    @staticmethod
    def run(args: Namespace) -> str | None:
        release_del = args.release
        if release_del and (err := check_release_tag(release_del)):
            return err

        for version in get_version_names(args):
            dfile = args._versions / version / args._data
            release = get_json(dfile).get('release') or '?'
            if not release_del or release == release_del:
                remove(args, version)
                print(f'Version {args._fmtrel(version, release)} removed.')


# COMMAND
class list_:
    "List installed versions and show which have an update available."

    @staticmethod
    def init(parser: ArgumentParser) -> None:
        parser.add_argument(
            '-v',
            '--verbose',
            action='store_true',
            help='explicitly report why a version is not eligible for update',
        )
        parser.add_argument(
            '-r',
            '--release',
            help='use specified YYYYMMDD release '
            f'(e.g. {SAMPL_RELEASE}) for verbose compare, '
            'default is latest release',
        )
        parser.add_argument(
            'version', nargs='*', help='only list specified version, else all'
        )

    @staticmethod
    def run(args: Namespace) -> str | None:
        release_target = args._release
        files = get_release_files(args, release_target)
        if not files:
            return f'Release "{release_target}" not found.'

        matcher = VersionMatcher(files)
        args.all = not args.version
        args.skip = False
        for version in get_version_names(args):
            vdir = args._versions / version
            if not (data := get_json(vdir / args._data)):
                continue

            release = data.get('release')
            if not (distribution := data.get('distribution')):
                distribution = '?'
            upd = ''
            app = ''
            if release_target and release != release_target:
                if not (nextver := matcher.match(version, upgrade=True)):
                    if args.verbose:
                        app = (
                            ' not eligible for update because '
                            f'release {release_target} does not provide '
                            'this version.'
                        )
                else:
                    new_vdir = args._versions / nextver
                    if nextver != version and new_vdir.exists():
                        if args.verbose:
                            nrelease = get_json(new_vdir / args._data).get(
                                'release', '?'
                            )
                            app = (
                                f' not eligible for '
                                f'update because {args._fmtrel(nextver, nrelease)} '
                                'is already installed.'
                            )
                    else:
                        # May not be updatable if newer release does not support
                        # this same distribution anymore
                        if nextver and distribution in files.get(nextver, {}):
                            upd = (
                                f' updatable to {args._fmtrel(nextver, release_target)}'
                            )
                        elif args.verbose:
                            app = (
                                ' not eligible for update because '
                                f'{args._fmtrel(nextver, release_target)} does '
                                f'not provide {args._fmtdist(distribution)}.'
                            )

            if release:
                print(
                    f'{args._fmtrel(version, release)}{upd} '
                    f'{args._fmtdist(distribution)}{app}'
                )


# COMMAND
class show_:
    doc = f"""
    Show versions available from a release.

    View available releases and their distributions at
    {GITHUB_SITE}/releases.
    """

    @staticmethod
    def init(parser: ArgumentParser) -> None:
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            '-l', '--list', action='store_true', help='just list recent releases'
        )
        group.add_argument(
            '-r',
            '--release',
            help=f'{REPO} YYYYMMDD release to show (e.g. '
            f'{SAMPL_RELEASE}), default is latest release',
        )
        parser.add_argument(
            '-a',
            '--all',
            action='store_true',
            help='show all available distributions for each version from the release',
        )
        parser.add_argument(
            're_match',
            nargs='?',
            help='show only versions+distributions '
            'matching this regular expression pattern',
        )

    @staticmethod
    def run(args: Namespace) -> str | None:
        if args.all and args.list:
            args.parser.error('Can not specify --all with --list.')

        if args.list:
            args.release = False
            show_list(args)
            return None

        release = args._release
        files = get_release_files(args, release)
        if not files:
            return f'Error: release "{release}" not found.'

        installed = {}
        for vdir in iter_versions(args):
            data = get_json(vdir / args._data)
            if data.get('release') == release and (distro := data.get('distribution')):
                installed[vdir.name] = distro

        installable = False
        for version in sorted(files, key=parse_version):
            installed_distribution = installed.get(version)
            for distribution in files[version]:
                app = ' (installed)' if distribution == installed_distribution else ''
                if args.all or app or distribution == args._distribution:
                    if distribution == args._distribution:
                        installable = True

                    if not args.re_match or re.search(
                        args.re_match, f'{version}+{distribution}'
                    ):
                        print(
                            f'{args._fmtrel(version, release)} '
                            f'{args._fmtdist(distribution)}{app}'
                        )
        if not installable:
            print(
                f'Warning: no {args._fmtdist(args._distribution)} '
                f'versions found in release "{release}".'
            )


# COMMAND
class path_:
    "Show path prefix to installed version base directory."

    @staticmethod
    def init(parser: ArgumentParser) -> None:
        parser.add_argument(
            '-p',
            '--python-path',
            action='store_true',
            help='add path to python executable',
        )
        parser.add_argument(
            '-r', '--resolve', action='store_true', help='fully resolve given version'
        )
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            '-c',
            '--cache-path',
            action='store_true',
            help='just show path to cache dir',
        )
        group.add_argument('version', nargs='?', help='version number to show path for')

    @staticmethod
    def run(args: Namespace) -> str | None:
        version = args.version
        if args.cache_path or not version:
            if args.python_path:
                args.parser.error('Can not specify --python-path.')

            print(args._downloads.parent if args.cache_path else args._versions)
        else:
            path = args._versions / version
            if not path.exists():
                return f'Version {version} is not installed.'

            if args.resolve:
                path = path.resolve()

            if args.python_path:
                basepath = path
                path = basepath / 'bin' / 'python'
                if not path.exists():
                    path = basepath / 'python.exe'
                    if not path.exists():
                        return f'Error: Can not find python executable in "{basepath}"'

            print(path)


# COMMAND
class cache_:
    "Show size of release download caches."

    @staticmethod
    def init(parser: ArgumentParser) -> None:
        parser.add_argument(
            '-T', '--no-total', action='store_true', help='do not show total cache size'
        )
        parser.add_argument(
            '-H',
            '--no-human-readable',
            action='store_true',
            help='show sizes in bytes, not human readable format',
        )
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            '-r',
            '--remove',
            action='store_true',
            help='remove download cache[s] instead of showing size',
        )
        group.add_argument(
            '-R',
            '--remove-all-unused',
            action='store_true',
            help='remove caches for all currently unused releases instead of showing size',
        )
        parser.add_argument(
            'release', nargs='*', help='show cache size for given release[s] only'
        )

    @staticmethod
    def run(args: Namespace) -> str | None:
        if args.remove_all_unused:
            if args.release:
                args.parser.error(
                    'Can not specify --remove-all-unused with release names.'
                )

            keep = keeplist(args)
            for release in args._downloads.iterdir():
                if (name := release.name) not in keep and name.isdigit():
                    if rm_path(release):
                        print(f'Removed cache for release {name}.')

        elif args.release:
            for release in args.release:
                # Allow user to include cache path in release name
                path = (args._downloads / release).expanduser()

                if err := check_release_tag(path.name):
                    return err

                if not path.exists():
                    return f'No cache for release {release}.'

                if args.remove:
                    if rm_path(args._downloads / release):
                        print(f'Removed cache for release {release.name}.')
                else:
                    show_cache_size(path, args)
        else:
            if args.remove:
                if rm_path(args._downloads):
                    print('Removed download cache.')
            else:
                show_cache_size(args._downloads, args)


# COMMAND
class uv_:
    __doc__ = f'Run a uv command using a version of python installed by {PROG}.'

    @staticmethod
    def init(parser: ArgumentParser) -> None:
        parser.add_argument(
            '-p',
            '--python',
            help='version of python to use, e.g. "3.12", default is latest release version',
        )

        parser.add_argument('command', help='uv command to run')
        parser.add_argument('subcommand', nargs='?', help='optional uv sub-command')

        parser.add_argument(
            'uv_args_for_command',
            nargs='*',
            help='optional extra arguments to pass to uv command [sub-command], start any options with "-- "',
        )

    @staticmethod
    def run(args: Namespace) -> str | None:
        cmd = ['uv', args.command]
        if args.subcommand:
            cmd.append(args.subcommand)

        return run_uv(args, cmd, args.uv_args_for_command)


# COMMAND
class uvx_:
    __doc__ = f'Run a program using uvx and a version of python installed by {PROG}.'

    @staticmethod
    def init(parser: ArgumentParser) -> None:
        parser.add_argument(
            '-p',
            '--python',
            help='version of python to use, e.g. "3.12", default is latest release version',
        )

        parser.add_argument('program', help='uvx program to run')
        parser.add_argument(
            'uvx_args_for_program',
            nargs='*',
            help='optional extra arguments to pass to uvx program, start any options with "-- "',
        )

    @staticmethod
    def run(args: Namespace) -> str | None:
        return run_uv(args, ['uvx'], [args.program] + args.uvx_args_for_program)


if __name__ == '__main__':
    sys.exit(main())
