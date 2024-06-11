#!/usr/bin/python3
# PYTHON_ARGCOMPLETE_OK
'''
Command line tool to install pre-built Python versions from the
python-build-standalone project.
'''
from __future__ import annotations

import json
import os
import platform
import re
import shlex
import shutil
import sys
import time
import urllib.request
from argparse import ArgumentParser, Namespace
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

import argcomplete
import platformdirs
from packaging.version import parse as parse_version

REPO_OWNER = 'indygreg'
REPO = 'python-build-standalone'
GITHUB_REPO = f'{REPO_OWNER}/{REPO}'
LATEST_RELEASE_URL = f'https://raw.githubusercontent.com/{GITHUB_REPO}'\
        '/latest-release/latest-release.json'

PROG = Path(__file__).stem
CNFFILE = platformdirs.user_config_path(f'{PROG}-flags.conf')

# Default distributions for various platforms
DISTRIBUTIONS = {
    ('Linux', 'x86_64'): 'x86_64-unknown-linux-gnu',
    ('Linux', 'aarch64'): 'aarch64-unknown-linux-gnu',
    ('Linux', 'armv7l'): 'armv7-unknown-linux-gnueabihf',
    ('Linux', 'armv8l'): 'armv7-unknown-linux-gnueabihf',
    ('Darwin', 'x86_64'): 'x86_64-apple-darwin',
    ('Darwin', 'aarch64'): 'aarch64-apple-darwin',
    ('Windows', 'x86_64'): 'x86_64-pc-windows-msvc',
    ('Windows', 'i686'): 'i686-pc-windows-msvc',
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
    'Get JSON data from given file'
    try:
        with file.open() as fp:
            return json.load(fp)
    except Exception:
        pass

    return {}

def set_json(file: Path, data: dict) -> Optional[str]:
    'Set JSON data to given file'
    try:
        with file.open('w') as fp:
            json.dump(data, fp, indent=2)
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

    from github import Github
    get_gh_handle = Github()  # type: ignore
    return get_gh_handle

def rm_path(path: Path) -> None:
    'Remove the given path'
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()

class VersionMatcher:
    'Match a version string to a list of versions'
    def __init__(self, seq: Iterable[str]) -> None:
        self.seq = sorted(seq, key=parse_version, reverse=True)

    def match(self, version: str, *,
              upconvert_minor: bool = False) -> Optional[str]:
        'Return full version string given a [possibly] part version prefix'
        if version in self.seq:
            return version

        if upconvert_minor:
            version = version.rsplit('.', 1)[0]

        if not version.endswith('.'):
            version += '.'

        for full_version in self.seq:
            if full_version.startswith(version):
                return full_version

        return None

def iter_versions(args: Namespace) -> Iterator[Path]:
    'Iterate over all version dirs'
    for f in args._versions.iterdir():
        if f.is_dir() and not f.is_symlink() and not f.name.startswith('.'):
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

def get_latest_release_tag(args: Namespace) -> str:
    'Return the latest release tag'
    if args._latest_release.exists():
        stat = args._latest_release.stat()
        if time.time() < (stat.st_mtime + int(args.cache_minutes * 60)):
            return args._latest_release.read_text().strip()

    # Note this simple URL fetch is much faster than using the GitHub
    # API, and has no rate-limits, so we use it to get the latest
    # release tag.
    try:
        with urllib.request.urlopen(LATEST_RELEASE_URL) as url:
            data = json.load(url)
    except Exception:
        sys.exit('Failed to fetch latest release tag.')

    tag = data.get('tag')

    if not tag:
        sys.exit('Latest release tag timestamp file is corrupted.')

    args._latest_release.write_text(tag + '\n')
    return tag

def get_release_files(args, tag, implementation: Optional[str] = None) -> dict:
    'Return the release files for the given tag'
    # Look for tag data in our release cache
    jfile = args._releases / tag
    if not (files := get_json(jfile)):
        # Not in cache so fetch it (and also store in cache)
        gh = get_gh(args)
        try:
            release = gh.get_repo(GITHUB_REPO).get_release(tag)
        except Exception:
            return {}

        # Iterate over the release assets and store the files in a dict to
        # return
        end = '-install_only.tar.gz'
        for file in release.get_assets():
            name = file.name
            if not name.endswith(end):
                continue

            name = name[:-len(end)]
            impl_ver, rest = name.split('+', maxsplit=1)
            impl, ver = impl_ver.split('-', maxsplit=1)
            rest = rest.split('-', maxsplit=1)[1]

            if impl not in files:
                files[impl] = defaultdict(dict)

            files[impl][ver][rest] = file.browser_download_url

        if error := set_json(jfile, files):
            sys.exit(f'Failed to write release {tag} file {jfile}: {error}')

    return files.get(implementation, {}) if implementation else files

def update_version_symlinks(args: Namespace) -> None:
    'Create/update symlinks pointing to latest version'
    base = args._versions
    if not base.exists():
        return

    # Record of all the existing symlinks and version dirs
    oldlinks = {}
    vers = []
    for path in base.iterdir():
        if not path.name.startswith('.'):
            if path.is_symlink():
                oldlinks[path.name] = os.readlink(str(path))
            else:
                vers.append(path)

    # Create a map of all the new major version links
    newlinks_all = defaultdict(list)
    for path in vers:
        namevers = path.name
        while '.' in namevers[:-1]:
            namevers_major = namevers.rsplit('.', maxsplit=1)[0]
            newlinks_all[namevers_major].append(namevers)
            namevers = namevers_major

    newlinks = {k: sorted(v, key=parse_version)[-1] for k, v in
                newlinks_all.items()}

    # Remove all old or invalid existing links
    for name, tgt in oldlinks.items():
        new_tgt = newlinks.get(name)
        if not new_tgt or new_tgt != tgt:
            path = Path(base / name)
            path.unlink()

    # Create all needed new links
    for name, tgt in newlinks.items():
        old_tgt = oldlinks.get(name)
        if not old_tgt or old_tgt != tgt:
            path = Path(base / name)
            path.symlink_to(tgt, target_is_directory=True)

def purge_unused_releases(args: Namespace) -> None:
    'Purge old releases that are no longer needed and have expired'
    releases = set(f.name for f in args._releases.iterdir())
    keep = set()
    if args._latest_release.exists():
        keep.add(args._latest_release.read_text().strip())

    for version in iter_versions(args):
        if (release := get_json(version / args._data).get('release')):
            keep.add(release)

    for release in releases - keep:
        rdir = args._releases / release
        stat = rdir.stat()
        if time.time() > (stat.st_mtime + args.purge_days * 86400):
            rdir.unlink()

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

def install(args: Namespace, vdir: Path, release: str, distribution: str,
            files: dict) -> Optional[str]:
    'Install a version'
    version = vdir.name

    if not (file := files[version].get(distribution)):
        return f'Arch "{distribution}" not found for release '\
                f'{release} version {version}.'

    tmpdir = args._versions / f'.{version}-tmp'
    rm_path(tmpdir)
    tmpdir.mkdir()
    tmpdir_py = tmpdir / 'python'
    error = None

    try:
        urllib.request.urlretrieve(file, tmpdir / 'tmp.tar.gz')
        shutil.unpack_archive(tmpdir / 'tmp.tar.gz', tmpdir)
    except Exception as e:
        error = f'Failed to fetch "{version}": {e}'

    if not error:
        data = {'release': release, 'distribution': distribution}
        if (error := set_json(tmpdir_py / args._data, data)):
            error = f'Failed to write {version} data file: {error}'

    if not error:
        remove(args, version)
        tmpdir_py.replace(vdir)

    shutil.rmtree(tmpdir)
    return error

def main() -> Optional[str]:
    'Main code'
    distro_default = DISTRIBUTIONS.get((platform.system(), platform.machine()))
    distro_help = distro_default if distro_default else '?unknown?'

    base_dir = Path('/opt' if is_admin() else
                    platformdirs.user_data_dir()) / PROG

    # Parse arguments
    opt = ArgumentParser(description=__doc__,
              epilog='Note you can set default starting global options '
                         f'in {CNFFILE}.')

    # Set up main/global arguments
    opt.add_argument('-D', '--distribution',
                     help=f'{REPO} "*-install_only" '
                     'distribution, e.g. "x86_64-unknown-linux-gnu". '
                     f'Default is auto-detected (detected as "{distro_help}" '
                     'for this current host).')
    opt.add_argument('-B', '--base-dir', default=str(base_dir),
                     help=f'specify {PROG} base dir for storing '
                     'versions and metadata. Default is "%(default)s"')
    opt.add_argument('-C', '--cache-minutes', default=60, type=float,
                     help='cache latest release tag fetch for this many '
                     'minutes, before rechecking for latest. '
                     'Default is %(default)d minutes')
    opt.add_argument('--purge-days', default=30, type=int,
                     help='cache release file lists for this number '
                     'of days after last version referencing it is removed. '
                     'Default is %(default)d days')
    opt.add_argument('-V', action='store_true',
                     help=f'show {PROG} version')
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

        title = get_title(desc)
        cmdopt = cmd.add_parser(name, description=desc, help=title)

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

    if args.V:
        print(get_version())

    if 'func' not in args:
        if not args.V:
            opt.print_help()
        return None

    distribution = args.distribution or distro_default
    if not distribution:
        sys.exit('Unknown system + machine distribution. Please specify '
                'using -D/--distribution option.')

    # Keep some useful info in the namespace passed to the command
    base_dir = Path(args.base_dir).expanduser()

    args._distribution = distribution
    args._data = f'{PROG}.json'
    args._latest_release = base_dir / 'latest_release'
    args._latest_release.parent.mkdir(parents=True, exist_ok=True)
    args._versions = base_dir / 'versions'
    args._versions.mkdir(parents=True, exist_ok=True)
    args._releases = base_dir / 'releases'
    args._releases.mkdir(parents=True, exist_ok=True)

    result = args.func(args)
    update_version_symlinks(args)
    purge_unused_releases(args)
    return result

@COMMAND.add
class _install(COMMAND):
    doc = f'Install one or more versions from a {REPO} release.'

    @staticmethod
    def init(parser: ArgumentParser) -> None:
        parser.add_argument('-r', '--release',
                            help=f'install from specified {REPO} '
                            'release (e.g. 20240415), '
                            'default is latest release')
        parser.add_argument('-f', '--force', action='store_true',
                            help='force install even if already installed')
        parser.add_argument('version', nargs='+',
                            help='version to install. E.g. 3.12 or 3.12.3')

    @staticmethod
    def run(args: Namespace) -> Optional[str]:
        release = args.release or get_latest_release_tag(args)
        files = get_release_files(args, release, 'cpython')
        if not files:
            return f'Release "{release}" not found.'

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
    @staticmethod
    def init(parser: ArgumentParser) -> None:
        parser.add_argument('-r', '--release',
                            help='update to specified release (e.g. 20240415), '
                            'default is latest release')
        parser.add_argument('-a', '--all', action='store_true',
                            help='update ALL versions')
        parser.add_argument('--skip', action='store_true',
                            help='skip the specified versions when '
                            'updating all (only can be specified with --all)')
        parser.add_argument('version', nargs='*',
                            help='version to update (or to skip for '
                            '--all --skip)')

    @staticmethod
    def run(args: Namespace) -> Optional[str]:
        release_target = args.release or get_latest_release_tag(args)
        files = get_release_files(args, release_target, 'cpython')
        if not files:
            return f'Release "{release_target}" not found.'

        matcher = VersionMatcher(files)
        for version in get_version_names(args):
            if not (data := get_json(args._versions / version / args._data)):
                continue

            release = data.get('release')
            if release == release_target:
                continue

            nextver = matcher.match(version, upconvert_minor=True)
            new_vdir = args._versions / nextver
            if nextver != version and new_vdir.exists():
                continue

            distribution = data.get('distribution')
            if not distribution or distribution not in files.get(nextver, {}):
                continue

            print(f'{fmt(version, release)} updating to '
                  f'{fmt(nextver, release_target)} '
                  f'distribution="{distribution}" ..')

            if error := install(args, new_vdir, release_target, distribution,
                                files):
                return error

            if nextver != version:
                remove(args, version)

@COMMAND.add
class _remove(COMMAND):
    'Remove/uninstall one, more, or all versions.'
    @staticmethod
    def init(parser: ArgumentParser) -> None:
        parser.add_argument('-a', '--all', action='store_true',
                            help='remove ALL versions')
        parser.add_argument('--skip', action='store_true',
                            help='skip the specified versions when '
                            'removing all (only can be specified with --all)')
        parser.add_argument('-r', '--release',
                            help='only remove versions if from '
                            'specified release (e.g. 20240415)')
        parser.add_argument('version', nargs='*',
                            help='version to remove (or to skip for '
                            '--all --skip)')

    @staticmethod
    def run(args: Namespace) -> Optional[str]:
        for version in get_version_names(args):
            dfile = args._versions / version / args._data
            release = get_json(dfile).get('release') or '?'
            if not args.release or release == args.release:
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
                            help='use specified release (e.g. 20240415) for '
                            'verbose compare, default is latest release')
        parser.add_argument('version', nargs='*',
                            help='only list specified version, else all')

    @staticmethod
    def run(args: Namespace) -> Optional[str]:
        release_target = args.release or get_latest_release_tag(args)
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
                nextver = matcher.match(version, upconvert_minor=True)
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
                        upd = f' updatable to {fmt(nextver, release_target)}'
                    elif args.verbose:
                        app = f' not eligible for update because '\
                                f'{fmt(nextver, release_target)} does '\
                                f'not provide distribution="{distribution}".'

            print(f'{fmt(version, release)}{upd} '
                    f'distribution="{distribution}"{app}')

@COMMAND.add
class _show(COMMAND):
    'Show versions available from a release.'
    @staticmethod
    def init(parser: ArgumentParser) -> None:
        parser.add_argument('-d', '--distributions', action='store_true',
                            help='also show all available distributions for '
                            'each version from the release')
        parser.add_argument('release', nargs='?',
                            help=f'{REPO} release to show (e.g. 20240415), '
                            'default is latest release')

    @staticmethod
    def run(args: Namespace) -> None:
        release = args.release or get_latest_release_tag(args)
        files = get_release_files(args, release, 'cpython')
        if not files:
            sys.exit(f'Error: release "{release}" not found.')

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
                if args.distributions or app \
                        or distribution == args._distribution:
                    if distribution == args._distribution:
                        installable = True

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
                            help='return full path to python executable')
        parser.add_argument('version', help='version to return path for')

    @staticmethod
    def run(args: Namespace) -> Optional[str]:
        matcher = VersionMatcher([f.name for f in iter_versions(args)])
        version = matcher.match(args.version) or args.version
        path = args._versions / version
        if not path.is_dir():
            return f'Version "{version}" is not installed.'

        if args.python_path:
            subpath = path / 'bin' / 'python'
            if subpath.exists():
                print(subpath)
            else:
                subpath = path / 'python.exe'
                if subpath.exists():
                    print(subpath)
                else:
                    return f'Error: Can not find python executable in "{path}"'
        else:
            print(path)

if __name__ == '__main__':
    sys.exit(main())
