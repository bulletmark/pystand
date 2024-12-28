#!/usr/bin/python3
# PYTHON_ARGCOMPLETE_OK
'''
Command line tool to download, install, and update pre-built Python
versions from the python-build-standalone project at
https://github.com/astral-sh/python-build-standalone.
'''
from __future__ import annotations

import os
import platform
import re
import shlex
import shutil
import sys
import time
from argparse import ArgumentParser, Namespace
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

import argcomplete
import platformdirs
from packaging.version import parse as parse_version

REPO = 'python-build-standalone'
GITHUB_REPO = f'astral-sh/{REPO}'
GITHUB_SITE = f'https://github.com/{GITHUB_REPO}'
LATEST_RELEASES = f'{GITHUB_SITE}/releases.atom'
LATEST_RELEASE_TAG = f'{GITHUB_SITE}/releases/latest'

# Sample release tag for documentation/usage examples
SAMPL_RELEASE = '20240415'

PROG = Path(__file__).stem
CNFFILE = platformdirs.user_config_path(f'{PROG}-flags.conf')

# Default distributions for various platforms
DISTRIBUTIONS = {
    ('Linux', 'x86_64'): 'x86_64_v3-unknown-linux-gnu-install_only_stripped',
    ('Linux', 'aarch64'): 'aarch64-unknown-linux-gnu-install_only_stripped',
    ('Linux', 'armv7l'): 'armv7-unknown-linux-gnueabihf-install_only_stripped',
    ('Linux', 'armv8l'): 'armv7-unknown-linux-gnueabihf-install_only_stripped',
    ('Darwin', 'x86_64'): 'x86_64-apple-darwin-install_only_stripped',
    ('Darwin', 'aarch64'): 'aarch64-apple-darwin-install_only_stripped',
    ('Windows', 'x86_64'):
        'x86_64-pc-windows-msvc-shared-install_only_stripped',
    ('Windows', 'i686'): 'i686-pc-windows-msvc-shared-install_only_stripped',
}

def is_admin() -> bool:
    'Check if we are running as root'
    if platform.system() == 'Windows':
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0  # type: ignore

    return os.geteuid() == 0

def get_version() -> str:
    'Return the version of this package'
    from importlib.metadata import version
    try:
        ver = version(PROG)
    except Exception:
        ver = 'unknown'

    return ver

def fmt(version, release) -> str:
    'Return a formatted release version string'
    return f'{version} @ {release}'

def get_json(file: Path) -> dict:
    from json import load
    'Get JSON data from given file'
    try:
        with file.open() as fp:
            return load(fp)
    except Exception:
        pass

    return {}

def set_json(file: Path, data: dict) -> str | None:
    'Set JSON data to given file'
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
    'Return a GitHub handle'
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
    get_gh_handle = Github(auth=auth)  # type: ignore
    return get_gh_handle

def rm_path(path: Path) -> None:
    'Remove the given path'
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()

def unpack_zst(filename: str, extract_dir: str) -> None:
    'Unpack a zstandard compressed tar'
    import tarfile

    import zstandard
    with open(filename, 'rb') as compressed:
        dctx = zstandard.ZstdDecompressor()
        with dctx.stream_reader(compressed) as reader:
            with tarfile.open(fileobj=reader, mode='r|') as tar:
                tar.extractall(path=extract_dir)

def fetch(args: Namespace, release: str, url: str, tdir: Path) -> str | None:
    'Fetch and unpack a release file'
    from urllib.parse import unquote, urlparse
    from urllib.request import urlretrieve
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
            urlretrieve(url, cache_file)
        except Exception as e:
            error = f'Failed to fetch "{url}": {e}'

    if error:
        rm_path(cache_file)
    else:
        if filename.endswith('.zst'):
            shutil.register_unpack_format('zst', ['.zst'], unpack_zst)

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
    'Check if a string is a formal Python release tag'
    return version.replace('.', '').isdigit()

class VersionMatcher:
    'Match a version string to a list of versions'
    def __init__(self, seq: Iterable[str]) -> None:
        self.seq = sorted(seq, key=parse_version, reverse=True)

    def match(self, version: str | None, *,
              upgrade: bool = False) -> str | None:
        'Return full version string given a [possibly] part version prefix'

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
                if not upgrade or not is_release \
                        or is_release_version(full_version):
                    return full_version

        return None

def iter_versions(args: Namespace) -> Iterator[Path]:
    'Iterate over all version dirs'
    for f in args._versions.iterdir():
        if f.is_dir() and not f.is_symlink() \
                and f.name[0] != '.' and f.name[0].isdigit():
            yield f

def get_version_names(args: Namespace) -> list[str]:
    'Return a list of validated version names based on command line args'
    if args.all:
        if not args.skip and args.version:
            args.parser.error('Can not specify versions with '
                            '--all unless also specifying --skip.')
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

    if (unknown := given - all_names):
        s = 's' if len(unknown) > 1 else ''
        unknowns = [f'"{u}"' for u in unknown]
        sys.exit(f'Error: version{s} {", ".join(unknowns)} not found.')

    return sorted(all_names - given, key=parse_version) \
            if args.all else versions

def check_release_tag(release: str) -> str | None:
    'Check the specified release tag is valid'
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
def fetch_tags() -> Iterator[tuple[str, str]]:
    'Fetch the latest release tags from the GitHub release atom feed'
    import xml.etree.ElementTree as et
    from urllib.request import urlopen
    try:
        with urlopen(LATEST_RELEASES) as url:
            data = et.parse(url).getroot()
    except Exception:
        sys.exit('Failed to fetch latest YYYYMMDD release atom file.')

    for child in data.iter():
        for entry in child.findall('{http://www.w3.org/2005/Atom}entry'):
            tl = entry.findtext('{http://www.w3.org/2005/Atom}title')
            dt = entry.findtext('{http://www.w3.org/2005/Atom}updated')
            if tl and dt:
                yield tl, dt

def fetch_tag_latest() -> str:
    'Fetch the latest release tag from the GitHub'
    from urllib.request import urlopen
    try:
        with urlopen(LATEST_RELEASE_TAG) as url:
            data = url.geturl()
    except Exception:
        sys.exit('Failed to fetch latest YYYYMMDD release tag.')

    return data.split('/')[-1]

def get_release_tag(args: Namespace) -> str:
    'Return the release tag, or latest if not specified'
    if release := args.release:
        if err := check_release_tag(release):
            sys.exit(err)

        return release

    if args._latest_release.exists():
        stat = args._latest_release.stat()
        if time.time() < (stat.st_mtime + int(args.cache_minutes * 60)):
            return args._latest_release.read_text().strip()

    if not (tag := fetch_tag_latest()):
        sys.exit('Latest YYYYMMDD release tag timestamp file is unavailable.')

    args._latest_release.write_text(tag + '\n')
    return tag

def add_file(files: dict, tag: str, name: str, url: str) -> None:
    'Extract the implementation, version, and architecture from a filename'
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

def get_release_files(args, tag, implementation: str | None = None) -> dict:
    'Return the release files for the given tag'
    # Look for tag data in our release cache
    jfile = args._releases / tag
    if not (files := get_json(jfile)):

        # May have read this release before but it has no assets
        if jfile.exists():
            return {}

        # Not in cache so fetch it (and also store in cache)
        from github.GithubException import UnknownObjectException
        gh = get_gh(args)
        try:
            release = gh.get_repo(GITHUB_REPO).get_release(tag)
        except UnknownObjectException:
            return {}

        # Iterate over the release assets and store pertinent files in a
        # dict to return.
        for asset in release.get_assets():
            add_file(files, tag, asset.name, asset.browser_download_url)

        if not files:
            sys.exit(f'Failed to fetch any files for release {tag}')

        if error := set_json(jfile, files):
            sys.exit(f'Failed to write release {tag} file {jfile}: {error}')

    return files.get(implementation, {}) if implementation else files

def update_version_symlinks(args: Namespace) -> None:
    'Create/update symlinks pointing to latest version'
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

def purge_unused_releases(args: Namespace) -> None:
    'Purge old releases that are no longer needed and have expired'
    # Want to keep releases for versions that we currently have installed
    keep = {r for v in iter_versions(args)
            if (r := get_json(v / args._data).get('release'))}

    # Add current release to keep list (even if not currently installed)
    if args._latest_release.exists():
        keep.add(args._latest_release.read_text().strip())

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
    for path in args._downloads.iterdir():
        if path.name not in keep:
            rm_path(path)

def show_list(args: Namespace) -> None:
    'Show a list of available releases'
    releases = {r: d for r, d in fetch_tags()}
    cached = set(p.name for p in args._releases.iterdir())
    for release in sorted(cached.union(releases)):
        if args.re_match and not re.search(args.re_match, release):
            continue

        if dt_str := releases.get(release):
            dts = datetime.fromisoformat(dt_str).astimezone().isoformat(
                    sep='_', timespec='minutes')
        else:
            dts = '......................'

        if release in cached:
            ddir = args._downloads / release
            count = len(list(ddir.iterdir())) if ddir.exists() else 0
            app = f' cached + {count} downloaded files' \
                    if count > 0 else ' cached'
        else:
            app = ''

        print(f'{release} {dts}{app}')

class COMMAND:
    'Base class for all commands'
    commands = []

    @classmethod
    def add(cls, parent) -> None:
        'Append parent command to internal list'
        cls.commands.append(parent)

def get_title(desc: str) -> str:
    'Return single title line from description'
    res = []
    for line in desc.splitlines():
        line = line.strip()
        res.append(line)
        if line.endswith('.'):
            return ' '. join(res)

    sys.exit('Must end description with a full stop.')

def remove(args: Namespace, version: str) -> None:
    'Remove a version'
    vdir = args._versions / version
    if not vdir.exists():
        return

    # Touch the associated release file to ensure it lives until the
    # full purge time has expired if this was the last version using it
    if release := get_json(vdir / args._data).get('release'):
        (args._releases / release).touch()

    shutil.rmtree(vdir)

def strip_binaries(vdir: Path, distribution: str) -> bool:
    'Strip binaries from files in a version directory'
    from subprocess import DEVNULL, run

    # Only run the strip command on Linux hosts and for Linux distributions
    was_stripped = False
    if platform.system() == 'Linux' and '-linux-' in distribution:
        for path in ('bin', 'lib'):
            base = vdir / path
            if not base.is_dir():
                continue

            for file in base.iterdir():
                if not file.is_symlink() and file.is_file():
                    cmd = f'strip -p --strip-unneeded {file}'.split()
                    try:
                        run(cmd, stderr=DEVNULL)
                    except Exception:
                        pass
                    else:
                        was_stripped = True

    return was_stripped

def install(args: Namespace, vdir: Path, release: str, distribution: str,
            files: dict) -> str | None:
    'Install a version'
    version = vdir.name

    if not (url := files[version].get(distribution)):
        return f'Arch "{distribution}" not found for release '\
                f'{release} version {version}.'

    tmpdir = args._versions / f'.{version}-tmp'
    rm_path(tmpdir)
    tmpdir.mkdir(parents=True)

    if not (error := fetch(args, release, url, tmpdir)):
        data = {'release': release, 'distribution': distribution}

        if not args.no_strip and strip_binaries(tmpdir, distribution):
            data['stripped'] = 'true'

        if (error := set_json(tmpdir / args._data, data)):
            error = f'Failed to write {version} data file: {error}'

    if error:
        shutil.rmtree(tmpdir)
    else:
        remove(args, version)
        tmpdir.replace(vdir)

    return error

def main() -> str | None:
    'Main code'
    distro_default = DISTRIBUTIONS.get((platform.system(), platform.machine()))
    distro_help = distro_default or '?unknown?'

    p = '/opt' if is_admin() else platformdirs.user_data_dir()
    prefix_dir = str(Path(p, PROG))
    cache_dir = platformdirs.user_cache_path() / PROG

    # Parse arguments
    opt = ArgumentParser(description=__doc__,
            epilog='Some commands offer aliases as shown in brackets above. '
                'Note you can set default starting global options in '
                f'{CNFFILE}.')

    # Set up main/global arguments
    opt.add_argument('-D', '--distribution',
                     help=f'{REPO} distribution. '
                     f'Default is "{distro_help} for this host')
    opt.add_argument('-P', '--prefix-dir', default=prefix_dir,
                     help='specify prefix dir for storing '
                     'versions. Default is "%(default)s"')
    opt.add_argument('-C', '--cache-dir', default=str(cache_dir),
                     help='specify cache dir for downloads. '
                     'Default is "%(default)s"')
    opt.add_argument('-M', '--cache-minutes', default=60, type=float,
                     help='cache latest YYYYMMDD release tag fetch for this '
                     'many minutes, before rechecking for latest. '
                     'Default is %(default)d minutes')
    opt.add_argument('--purge-days', default=90, type=int,
                     help='cache YYYYMMDD release file lists and downloads for '
                     'this number of days after last version referencing that '
                     'release is removed. Default is %(default)d days')
    opt.add_argument('--github-access-token',
                     help='optional Github access token. Can specify to reduce '
                     'rate limiting.')
    opt.add_argument('--no-strip', action='store_true',
                     help='do not strip downloaded binaries')
    opt.add_argument('-V', '--version', action='store_true',
                     help=f'just show {PROG} version')
    cmd = opt.add_subparsers(title='Commands', dest='cmdname')

    # Add each command ..
    for cls in COMMAND.commands:
        name = cls.__name__[1:]

        if hasattr(cls, 'doc'):
            desc = cls.doc.strip()
        elif cls.__doc__:
            desc = cls.__doc__.strip()
        else:
            return f'Must define a docstring for command class "{name}".'

        aliases = cls.aliases if hasattr(cls, 'aliases') else []
        title = get_title(desc)
        cmdopt = cmd.add_parser(name, description=desc, help=title,
                                aliases=aliases)

        # Set up this commands own arguments, if it has any
        if hasattr(cls, 'init'):
            cls.init(cmdopt)

        # Set the function to call
        cmdopt.set_defaults(func=cls.run, name=name, parser=cmdopt)

    # Command arguments are now defined, so we can set up argcomplete
    argcomplete.autocomplete(opt)

    # Merge in default args from user config file. Then parse the
    # command line.
    cnffile = CNFFILE.expanduser()
    if cnffile.is_file():
        with cnffile.open() as fp:
            lines = [re.sub(r'#.*$', '', line).strip() for line in fp]
        cnflines = ' '.join(lines).strip()
    else:
        cnflines = ''

    args = opt.parse_args(shlex.split(cnflines) + sys.argv[1:])

    if 'func' not in args:
        if args.version:
            print(get_version())
            return None

        opt.print_help()
        return None

    distribution = args.distribution or distro_default
    if not distribution:
        sys.exit('Unknown system + machine distribution. Please specify '
                'using -D/--distribution option.')

    # Keep some useful info in the namespace passed to the command
    prefix_dir = Path(args.prefix_dir).expanduser().resolve()
    cache_dir = Path(args.cache_dir).expanduser().resolve()

    args._distribution = distribution
    args._data = f'{PROG}.json'

    args._versions = prefix_dir
    args._versions.mkdir(parents=True, exist_ok=True)

    args._downloads = cache_dir / 'downloads'
    args._downloads.mkdir(parents=True, exist_ok=True)
    args._releases = cache_dir / 'releases'
    args._releases.mkdir(parents=True, exist_ok=True)
    args._latest_release = cache_dir / 'latest_release'

    result = args.func(args)
    purge_unused_releases(args)
    update_version_symlinks(args)
    return result

@COMMAND.add
class _install(COMMAND):
    doc = f'Install one or more versions from a {REPO} release.'

    @staticmethod
    def init(parser: ArgumentParser) -> None:
        parser.add_argument('-r', '--release',
                            help=f'install from specified {REPO} '
                            f'YYYYMMDD release (e.g. {SAMPL_RELEASE}), '
                            'default is latest release')
        parser.add_argument('-f', '--force', action='store_true',
                            help='force install even if already installed')
        parser.add_argument('-s', '--include-source', action='store_true',
                            help='also install source files if available in '
                            'distribution download')
        parser.add_argument('version', nargs='+',
                            help='version to install. E.g. 3.12 or 3.12.3')

    @staticmethod
    def run(args: Namespace) -> str | None:
        release = get_release_tag(args)
        files = get_release_files(args, release, 'cpython')
        if not files:
            return f'Release "{release}" not found, or has no compatible files.'

        matcher = VersionMatcher(files)
        for version in args.version:
            full_version = matcher.match(version)
            if not full_version:
                return f'Version {fmt(version, release)} not found.'

            version = full_version
            vdir = args._versions / version

            if vdir.exists() and not args.force:
                return f'Version "{version}" is already installed.'

            if error := install(args, vdir, release, args._distribution, files):
                return error

            print(f'Version {fmt(version, release)} installed.')

@COMMAND.add
class _update(COMMAND):
    'Update one, more, or all versions to another release.'
    aliases = ['upgrade']

    @staticmethod
    def init(parser: ArgumentParser) -> None:
        parser.add_argument('-r', '--release',
                            help='update to specified YYYMMDD release (e.g. '
                            f'{SAMPL_RELEASE}), default is latest release')
        parser.add_argument('-a', '--all', action='store_true',
                            help='update ALL versions')
        parser.add_argument('--skip', action='store_true',
                            help='skip the specified versions when '
                            'updating all (only can be specified with --all)')
        parser.add_argument('-k', '--keep', action='store_true',
                            help='keep old version after updating (but only '
                            'if different version number)')
        parser.add_argument('version', nargs='*',
                            help='version to update (or to skip for '
                            '--all --skip)')

    @staticmethod
    def run(args: Namespace) -> str | None:
        release_target = get_release_tag(args)
        files = get_release_files(args, release_target, 'cpython')
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

            if nextver == version and args.keep:
                print(f'Error: {fmt(version, release)} would not be kept '
                      f'if update to {fmt(nextver, release_target)} '
                      f'distribution="{distribution}"', file=sys.stderr)
                continue

            new_vdir = args._versions / nextver
            if nextver != version and new_vdir.exists():
                continue

            print(f'{fmt(version, release)} updating to '
                  f'{fmt(nextver, release_target)} '
                  f'distribution="{distribution}" ..')

            # If the source was originally included, then include it in
            # the update.
            args.include_source = (vdir / 'src').is_dir()

            if error := install(args, new_vdir, release_target, distribution,
                                files):
                return error

            if nextver != version and not args.keep:
                remove(args, version)

@COMMAND.add
class _remove(COMMAND):
    'Remove/uninstall one, more, or all versions.'
    aliases = ['uninstall']

    @staticmethod
    def init(parser: ArgumentParser) -> None:
        parser.add_argument('-a', '--all', action='store_true',
                            help='remove ALL versions')
        parser.add_argument('--skip', action='store_true',
                            help='skip the specified versions when '
                            'removing all (only can be specified with --all)')
        parser.add_argument('-r', '--release',
                            help='only remove versions if from specified '
                            f'YYYMMDD release (e.g. {SAMPL_RELEASE})')
        parser.add_argument('version', nargs='*',
                            help='version to remove (or to skip for '
                            '--all --skip)')

    @staticmethod
    def run(args: Namespace) -> str | None:
        release_del = args.release
        if release_del and \
                (err := check_release_tag(release_del)):
            return err

        for version in get_version_names(args):
            dfile = args._versions / version / args._data
            release = get_json(dfile).get('release') or '?'
            if not release_del or release == release_del:
                remove(args, version)
                print(f'Version {fmt(version, release)} removed.')

@COMMAND.add
class _list(COMMAND):
    'List installed versions and show which have an update available.'
    @staticmethod
    def init(parser: ArgumentParser) -> None:
        parser.add_argument('-v', '--verbose', action='store_true',
                            help='explicitly report why a version is '
                            'not eligible for update')
        parser.add_argument('-r', '--release',
                            help='use specified YYYYMMDD release '
                            f'(e.g. {SAMPL_RELEASE}) for verbose compare, '
                            'default is latest release')
        parser.add_argument('version', nargs='*',
                            help='only list specified version, else all')

    @staticmethod
    def run(args: Namespace) -> str | None:
        release_target = get_release_tag(args)
        files = get_release_files(args, release_target, 'cpython')
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
            distribution = data.get('distribution')
            upd = ''
            app = ''
            if release_target and release != release_target:
                nextver = matcher.match(version, upgrade=True)
                if not nextver:
                    if args.verbose:
                        app = ' not eligible for update because '\
                                f'release {release_target} does not provide '\
                                'this version.'
                else:
                    new_vdir = args._versions / nextver
                    if nextver != version and new_vdir.exists():
                        if args.verbose:
                            nrelease = get_json(
                                    new_vdir / args._data).get('release', '?')
                            app = f' not eligible for '\
                                    f'update because {fmt(nextver, nrelease)} '\
                                    'is already installed.'
                    else:
                        # May not be updatable if newer release does not support
                        # this same distribution anymore
                        if nextver and distribution in files.get(nextver, {}):
                            upd = ' updatable to '\
                                    f'{fmt(nextver, release_target)}'
                        elif args.verbose:
                            app = ' not eligible for update because '\
                                    f'{fmt(nextver, release_target)} does '\
                                    'not provide '\
                                    f'distribution="{distribution}".'

            print(f'{fmt(version, release)}{upd} '
                    f'distribution="{distribution}"{app}')

@COMMAND.add
class _show(COMMAND):
    doc = f'''
    Show versions available from a release.

    View available releases and their distributions at
    {GITHUB_SITE}/releases.
    '''

    @staticmethod
    def init(parser: ArgumentParser) -> None:
        group = parser.add_mutually_exclusive_group()
        group.add_argument('-l', '--list', action='store_true',
                           help='just list recent releases')
        group.add_argument('-r', '--release',
                           help=f'{REPO} YYYYMMDD release to show (e.g. '
                           f'{SAMPL_RELEASE}), default is latest release')
        parser.add_argument('-a', '--all', action='store_true',
                            help='show all available distributions for '
                            'each version from the release')
        parser.add_argument('re_match', nargs='?',
                            help='show only versions+distributions '
                            'matching this regular expression pattern')

    @staticmethod
    def run(args: Namespace) -> str | None:
        if args.all and args.list:
            args.parser.error('Can not specify --all with --list.')

        if args.list:
            show_list(args)
            return None

        release = get_release_tag(args)
        files = get_release_files(args, release, 'cpython')
        if not files:
            return f'Error: release "{release}" not found.'

        installed = {}
        for vdir in iter_versions(args):
            data = get_json(vdir / args._data)
            if data.get('release') == release and \
                    (distro := data.get('distribution')):
                installed[vdir.name] = distro

        installable = False
        for version in sorted(files, key=parse_version):
            installed_distribution = installed.get(version)
            for distribution in files[version]:
                app = ' (installed)' \
                        if distribution == installed_distribution else ''
                if args.all or app \
                        or distribution == args._distribution:
                    if distribution == args._distribution:
                        installable = True

                    if not args.re_match or \
                            re.search(args.re_match,
                                      f'{version}+{distribution}'):
                        print(f'{fmt(version, release)} '
                            f'distribution="{distribution}"{app}')
        if not installable:
            print(f'Warning: no distribution="{args._distribution}" '
                  'versions found in ' f'release "{release}".')

@COMMAND.add
class _path(COMMAND):
    'Show path prefix to installed version base directory.'
    @staticmethod
    def init(parser: ArgumentParser) -> None:
        parser.add_argument('-p', '--python-path', action='store_true',
                            help='add path to python executable')
        parser.add_argument('-r', '--resolve', action='store_true',
                            help='fully resolve given version')
        group = parser.add_mutually_exclusive_group()
        group.add_argument('-c', '--cache-path', action='store_true',
                           help='just show path to cache dir')
        group.add_argument('version', nargs='?',
                           help='version number to show path for')

    @staticmethod
    def run(args: Namespace) -> str | None:
        version = args.version
        if args.cache_path or not version:
            if args.python_path:
                args.parser.error('Can not specify --python-path.')

            print(args._downloads.parent if args.cache_path else args._versions)
        else:
            path = args._versions / version
            if not path.is_symlink() or not path.exists():
                return f'Version "{version}" is not installed.'

            if args.resolve:
                path = path.resolve()

            if args.python_path:
                basepath = path
                path = basepath / 'bin' / 'python'
                if not path.exists():
                    path = basepath / 'python.exe'
                    if not path.exists():
                        return 'Error: Can not find python executable in '\
                                f'"{basepath}"'

            print(path)

if __name__ == '__main__':
    sys.exit(main())
