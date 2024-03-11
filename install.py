#!/usr/bin/env python3

import argparse
import ast
import collections
import filecmp
import hashlib
import json
import os
import os.path
import shutil
import sys

# directories that should be copied over to the main game files
# (also applies to OPTIONAL-MODS)
MOD_DIRS = ['Data', 'bin']

# blacklisted files, you can overwrite them but deleting them is no-no
BLACKLIST = [
    'bin/bink2w64.dll',
    'bin/bink2w64_original.dll',
]

def die(*args):
    print('ERROR:', *args, file=sys.stderr)
    sys.exit(1)

class Paths:
    platforms = {}

    @classmethod
    def register_platform(cls, name):
        def inner(platformcls):
            cls.platforms[name] = platformcls
        return inner

    @classmethod
    def for_current_platform(cls):
        try:
            return cls.platforms[sys.platform]()
        except KeyError:
            print('WARNING: platform not supported, you must supply paths manually.', file=sys.stderr)
            return cls()

    def __init__(self):
        self.steam = None
        self.libraries = []
        self.game = None
        self.gamedata = None
        self.gamebin = None

        self.appdata = None

    def discover(self):
        if not self.game:
            self.game = self.discover_game()
        self.gamedata = os.path.join(self.game, 'Data')
        if not os.path.isdir(self.gamedata):
            die('game data directory does not exist')
        self.gamebin = os.path.join(self.game, 'bin')
        if not os.path.isdir(self.gamebin):
            die('game bin directory does not exist')
        print('found game at', self.game)

        if not self.appdata:
            try:
                self.appdata = self.discover_appdata()
            except Exception as e:
                print(e, file=sys.stderr)
                die('could not find appdata')
        if not os.path.isdir(self.appdata):
            die('path is not a directory:', repr(self.appdata))
        print('found appdata at', self.appdata)

    def discover_game(self):
        if not self.libraries:
            self.libraries = self.discover_libraries()
        for library in self.libraries:
            print('searching library', library)
            gamepath = os.path.join(library, 'steamapps', 'common', 'Baldurs Gate 3')
            if os.path.isdir(gamepath):
                return gamepath
        die('could not find Baldur\'s Gate 3')

    def discover_libraries(self):
        if not self.steam:
            try:
                self.steam = self.discover_steam()
            except Exception as e:
                print(e, file=sys.stderr)
                die('could not find steam')
        if not os.path.isdir(self.steam):
            die('path is not a directory:', repr(self.steam))
        print('found steam at', self.steam)

        self.libraryconfig = os.path.join(self.steam, 'config', 'libraryfolders.vdf')
        if not os.path.isfile(self.libraryconfig):
            die('could not find steam library configuration')

        libraries = []
        try:
            with open(self.libraryconfig, 'r') as f:
                librarydata = parse_vdf(f.read())
            for k, v in librarydata['libraryfolders'].items():
                try:
                    if os.path.isdir(v['path']):
                        libraries.append(v['path'])
                except Exception:
                    pass
        except ParseError as e:
            print('vdf parse error:', e)
            die('could not parse steam library configuration')
        except Exception as e:
            die('could not read steam library configuration')

        return libraries

    def discover_steam(self):
        # return wherever steams default data is
        # this + config/libraryfolders.vdf must exist
        raise NotImplementedError('discover_steam')

    def discover_appdata(self):
        # return wherever the game stores its own appdata
        # for example, the file graphicSettings.lsx
        raise NotImplementedError('discover_appdata')

@Paths.register_platform('win32')
class WindowsPaths(Paths):
    def discover_steam(self):
        import winreg
        key = winreg.OpenKeyEx(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam')
        value, typ = winreg.QueryValueEx(key, 'SteamExe')
        if typ != winreg.REG_SZ:
            raise TypeError('expected string for SteamExe key')
        if not os.path.isfile(value):
            raise TypeError('expected SteamExe to point to a file')
        return os.path.split(value)[0]

    def discover_appdata(self):
        appdata = os.environ['LOCALAPPDATA']
        trial = os.path.join(appdata, 'Larian Studios', 'Baldur\'s Gate 3')
        if not os.path.isdir(trial):
            raise RuntimeError('cannot find steam')
        return trial

@Paths.register_platform('linux')
class LinuxPaths(Paths):
    def discover_steam(self):
        trial = os.path.join(os.path.expanduser('~'), '.local', 'share', 'Steam')
        if not os.path.isdir(trial):
            raise RuntimeError('cannot find steam')
        return trial

    def discover_appdata(self):
        if not self.libraries:
            self.libraries = self.discover_libraries()

        wine_prefix = [
            'compatdata', '1086940', 'pfx', 'drive_c',
            'users', 'steamuser', 'AppData', 'Local',
            'Larian Studios', 'Baldur\'s Gate 3',
        ]
        for library in self.libraries:
            trial = os.path.join(library, 'steamapps', *wine_prefix)
            if os.path.isdir(trial):
                return trial
        raise RuntimeError('cannot find appdata folder')

class ParseError(Exception):
    def __init__(self, tracker, message):
        line = tracker.line
        col = tracker.col
        super().__init__('line {} col {}: {}'.format(line, col, message))
        self.line = line
        self.col = col
        self.message = message

class LineColTracker:
    def __init__(self, stream):
        self.stream = iter(stream)
        self.line = 1
        self.col = -1

    @classmethod
    def track(cls, stream):
        if isinstance(stream, cls):
            return stream
        return cls(stream)

    def __iter__(self):
        return self

    def __next__(self):
        c = next(self.stream)
        if c == '\n':
            self.line += 1
            self.col = 0
        else:
            self.col += 1
        return c

def parse_vdf(stream, subvdf=False):
    WAIT_KEY, KEY, WAIT_VALUE, VALUE = range(4)
    stream = LineColTracker.track(stream)

    data = {}
    state = WAIT_KEY
    k = None
    v = None

    for c in stream:
        if state == WAIT_KEY:
            if c.isspace():
                continue
            elif c == '"':
                k = c
                state = KEY
                continue
            elif c == '}' and subvdf:
                return data
            else:
                raise ParseError(stream, 'expected space or \'"\', not {!r}'.format(c))
        elif state == KEY:
            k += c
            if c == '"' and k[-1] != '\\':
                state = WAIT_VALUE
                try:
                    k = ast.literal_eval(k)
                except Exception:
                    raise ParseError(stream, 'bad string: {!r}'.format(k))
            continue
        elif state == WAIT_VALUE:
            if c.isspace():
                continue
            elif c == '"':
                v = c
                state = VALUE
                continue
            elif c == '{':
                v = parse_vdf(stream, True)
                state = WAIT_KEY
                data[k] = v
                k = None
                v = None
                continue
            else:
                raise ParseError(stream, 'expected space or \'"\', not {!r}'.format(c))
        elif state == VALUE:
            v += c
            if c == '"' and v[-1] != '\\':
                state = WAIT_KEY
                try:
                    v = ast.literal_eval(v)
                except Exception:
                    raise ParseError(stream, 'bad string: {!r}'.format(v))
                data[k] = v
                k = None
                v = None
            continue
        else:
            raise RuntimeError('bad parse state')

    if subvdf:
        raise ParseError(stream, 'end of file inside braces')
    if state != WAIT_KEY:
        raise ParseError(stream, 'end of file inside key/value pair')

    return data

class LastUpdatedOrderedDict(collections.OrderedDict):
    """OrderedDict but updating a value moves it to the end."""
    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.move_to_end(key)

class InstallSimulator:
    """Gather file ops into a list of changes without performing them.

    Known bugs: paths are assumed to only ever be a file or a
    directory. Removing a directory and replacing it with a file named
    the same thing, or vice versa, will generate a change set that fails.
    """
    M_DIR = 'dir'
    M_FILE = 'file'

    def __init__(self, path):
        self.root = os.path.abspath(path)
        self.changes = LastUpdatedOrderedDict()

    def reset(self):
        """Clear the list of changes."""
        self.changes.clear()

    def normpath(self, path):
        """Turn a path into a normalized key."""
        # turn absolute paths into relative paths, but
        # relative paths stay relative to the root
        relpath = os.path.relpath(os.path.join(self.root, path), self.root)
        return os.path.normpath(relpath)

    def exists(self, path):
        """Check if a path exists, accounting for changes."""
        key = self.normpath(path)
        if key in self.changes:
            if self.changes[key] is None:
                return False
            return True
        return os.path.exists(os.path.join(self.root, key))

    def isdir(self, path):
        """Check if a path is a directory, accounting for changes."""
        key = self.normpath(path)
        if key in self.changes:
            if self.changes[key] is None:
                return False
            elif self.changes[key][0] == self.M_DIR:
                return True
            return False
        return os.path.isdir(os.path.join(self.root, key))

    def isfile(self, path):
        """Check if a path is a file, accounting for changes."""
        key = self.normpath(path)
        if key in self.changes:
            if self.changes[key] is None:
                return False
            elif self.changes[key][0] == self.M_FILE:
                return True
            return False
        return os.path.isfile(os.path.join(self.root, key))

    def listdir(self, path):
        """List the contents of a directory, accounting for changes."""
        key = self.normpath(path)
        key_and_sep = key + os.path.sep
        fullpath = os.path.join(self.root, key)
        leaves = []

        # first grab all the files on disk, but make sure they still exist
        # after changes
        if os.path.isdir(fullpath):
            for leaf in os.listdir(fullpath):
                if self.exists(os.path.join(key, leaf)):
                    leaves.append(key)

        # now grab any files added by changes
        for k, v in self.changes.items():
            if v is None:
                continue
            if k.startswith(key_and_sep):
                kleaf = k[len(key_and_sep):]
                if not os.path.sep in kleaf and kleaf not in leaves:
                    leaves.append(kleaf)

        return leaves

    def same_file(self, src, dst, real_only=False):
        """Return true if src and dest are the same file.

        If real_only=True, ignore simulated changes and look only at
        the real disk."""
        a = src
        b = os.path.join(self.root, dst)
        if not real_only:
            key = self.normpath(dst)
            if key in self.changes:
                if self.changes[key] is None:
                    return False
                elif self.changes[key][0] == self.M_FILE:
                    b = self.changes[key][1]
                else:
                    return False
        if not os.path.exists(b):
            return False
        return filecmp.cmp(a, b, shallow=False)

    def open(self, path, mode='rb'):
        """Open a file, accounting for changes."""
        key = self.normpath(path)
        fullpath = os.path.join(self.root, key)
        if key in self.changes:
            if self.changes[key] is None:
                raise RuntimeError('path does not exist: {}'.format(fullpath))
            elif self.changes[key][0] == self.M_FILE:
                return open(self.changes[key][1], mode)
            else:
                raise RuntimeError('path is not a file: {}'.format(fullpath))
        return open(os.path.join(self.root, path), mode)

    def makedir(self, dst):
        """Simulate directory creation."""
        fulldest = os.path.join(self.root, dst)
        key = self.normpath(dst)
        if self.isdir(dst):
            return
        if self.exists(dst):
            raise RuntimeError('path expected to be a directory: {}'.format(fulldest))
        self.changes[key] = [self.M_DIR]
        if os.path.isdir(fulldest):
            del self.changes[key]

    def makedirs(self, dst):
        """Simulate recursive directory creation."""
        head, tail = os.path.split(dst)
        if not tail:
            head, tail = os.path.split(head)
        if head and tail:
            self.makedirs(head)
        self.makedir(dst)

    def rmdir(self, dst):
        """Simulate removing a directory. Fails if not empty."""
        fulldest = os.path.join(self.root, dst)
        key = self.normpath(dst)
        if not self.exists(dst):
            return
        if not self.isdir(dst):
            raise RuntimeError('path expected to be a directory: {}'.format(fulldest))
        if self.listdir(dst):
            raise RuntimeError('directory not empty: {}'.format(fulldest))
        self.changes[key] = None
        if not os.path.exists(fulldest):
            del self.changes[key]

    def install_file(self, src, dst):
        """Simulate installing src to dest."""
        head, tail = os.path.split(dst)
        if head:
            self.makedirs(head)
        fulldest = os.path.join(self.root, dst)
        key = self.normpath(dst)
        if self.isdir(dst):
            raise RuntimeError('path is expected to be a file: {}'.format(fulldest))
        if self.same_file(src, dst):
            return
        self.changes[key] = [self.M_FILE, os.path.abspath(src)]
        if self.same_file(src, dst, real_only=True):
            del self.changes[key]

    def remove_file(self, dst):
        """Simulate removing a file."""
        fulldest = os.path.join(self.root, dst)
        key = self.normpath(dst)
        if not self.exists(dst):
            return
        if not self.isfile(dst):
            raise RuntimeError('path expected to be a file: {}'.format(fulldest))
        self.changes[key] = None
        if not os.path.exists(fulldest):
            del self.changes[key]

    def install_tree(self, src, dst):
        """Simulate installing a bunch of files, recursively."""
        for subdir, dirs, files in os.walk(src):
            for filename in files:
                subsrc = os.path.join(subdir, filename)
                leaf = os.path.relpath(subsrc, src)
                subdst = os.path.join(dst, leaf)
                self.install_file(subsrc, subdst)

class Installer:
    """Keeps track of what files this tool remembers installing."""
    M_VERSION = 0
    M_HASH_DIR = 'dir' # the special hash for dirs

    def __init__(self, root, metafile='overviewer-bg3-mods.meta'):
        self.root = os.path.abspath(root)
        self.sim = InstallSimulator(self.root)
        self.metapath = os.path.join(self.root, metafile)
        self.meta = {}

        # read the metadata, with some failure modes
        if os.path.isfile(self.metapath):
            with open(self.metapath, 'r') as f:
                try:
                    self.meta = json.load(f)
                    assert 'version' in self.meta
                    assert isinstance(self.meta.get('files'), dict)
                except Exception:
                    print('Could not load metafile!', file=sys.stderr)
                    print('It could be corrupted, or you used an older version of', file=sys.stderr)
                    print('this tool. If so, uninstall using the older tool first.', file=sys.stderr)
                    die('Bad metafile.')
        else:
            self.meta = self.default_meta()

        if self.meta['version'] != self.M_VERSION:
            print('Bad metafile version!', file=sys.stderr)
            print('You may have used a newer version of this tool on this game.', file=sys.stderr)
            print('If so, you should go back to using it.', file=sys.stderr)
            die('Bad metafile.')

        # find all the files we both installed and which have the
        # same hash we installed them with
        # we'll treat these as "unmodified" and safe to uninstall
        self.unmodified = {}
        for k, v in self.meta['files'].items():
            if v == self.M_HASH_DIR:
                continue
            path = os.path.join(self.root, k)
            if os.path.isfile(path):
                with open(path, 'rb') as f:
                    if v == self.hash(f):
                        self.unmodified[k] = v

    def default_meta(self):
        """The default, empty metadata."""
        return {
            'version': self.M_VERSION,
            'files': {},
        }

    def hash(self, fobj):
        """Hash a file object."""
        bufsize = 65536
        hasher = hashlib.sha1()
        hashname = 'sha1'
        while True:
            data = fobj.read(bufsize)
            if not data:
                break
            hasher.update(data)
        return hashname + ':' + hasher.hexdigest()

    def uninstall(self):
        """Plan to uninstall all known, unmodified files, and empty dirs."""

        # normalize blacklist so we can check it fast
        blacklist_keys = {self.sim.normpath(k) for k in BLACKLIST}

        # go in reverse length order, to remove leaves before dirs
        keys = list(self.meta['files'].keys())
        keys.sort(key=len, reverse=True)
        for k in keys:
            if k in blacklist_keys:
                continue
            v = self.meta['files'][k]
            if v == self.M_HASH_DIR:
                # remove if exists and empty
                if self.sim.isdir(k) and not self.sim.listdir(k):
                    self.sim.rmdir(k)
            elif self.sim.isfile(k) and k in self.unmodified:
                # exists and not modified, so remove it
                self.sim.remove_file(k)

    def install_tree(self, src, dst):
        """Plan to install a tree."""
        self.sim.install_tree(src, dst)

    def sim_label(self, k, v):
        """Generate a label for this operation in the summary."""
        if v is None:
            if os.path.isdir(os.path.join(self.root, k)):
                return '  [!] rmdir    '
            else:
                return '  [!] delete   '
        elif v[0] == self.sim.M_FILE:
            if os.path.isfile(os.path.join(self.root, k)) and k not in self.unmodified:
                # it exists and it's either unknown or modified
                return ' [!!] overwrite'
            else:
                return '      install  '
        elif v[0] == self.sim.M_DIR:
            return '      mkdir    '
        else:
            raise RuntimeError('unhandled change')

    def summarize(self):
        """Summarize planned changes."""
        if self.sim.changes:
            print('In {}'.format(self.root))
            for k, v in self.sim.changes.items():
                print(self.sim_label(k, v), k)
            return True
        return False

    def commit(self):
        """Execute planned changes, printing step by step."""
        with open(self.metapath, 'a+') as metafile:
            metafile.seek(0)
            try:
                data = json.load(metafile)
            except Exception:
                data = self.default_meta()
            if data != self.meta:
                die('metafile has changed, rerun tool')
            metafile.seek(0)
            metafile.truncate(0)
            json.dump(self.meta, metafile, indent=2)
            metafile.flush()
            metafile.seek(0)

            print('In {}'.format(self.root))

            for k, v in self.sim.changes.items():
                print(self.sim_label(k, v), k)
                fullk = os.path.join(self.root, k)
                if v is None:
                    if os.path.isdir(fullk):
                        os.rmdir(fullk)
                    elif os.path.isfile(fullk):
                        os.remove(fullk)
                    if k in self.meta['files']:
                        del self.meta['files'][k]
                elif v[0] == self.sim.M_FILE:
                    shutil.copy2(v[1], fullk)
                    with open(fullk, 'rb') as f:
                        self.meta['files'][k] = self.hash(f)
                elif v[0] == self.sim.M_DIR:
                    os.mkdir(fullk)
                    self.meta['files'][k] = self.M_HASH_DIR

                metafile.truncate(0)
                json.dump(self.meta, metafile, indent=2)
                metafile.flush()
                metafile.seek(0)

        self.sim.reset()

        if not self.meta['files']:
            os.remove(self.metapath)

def main(paths, dry_run, uninstall, optional_mods):
    paths.discover()
    print()

    gameins = Installer(paths.game)
    appins = Installer(paths.appdata)

    gameins.uninstall()
    appins.uninstall()

    if not uninstall:
        for d in MOD_DIRS:
            if os.path.isdir(d):
                gameins.install_tree(d, d)
        if optional_mods:
            for d in MOD_DIRS:
                optional_dir = os.path.join('OPTIONAL-MODS', d)
                if os.path.isdir(optional_dir):
                    gameins.install_tree(optional_dir, d)

        appins.install_tree('Baldur\'s Gate 3', '')

    if len(gameins.sim.changes) + len(appins.sim.changes) == 0:
        print('Nothing to do.')
        sys.exit(0)

    gameins.summarize()
    print()
    appins.summarize()

    if not dry_run:
        print()
        print('Perform actions listed above (Y/n)? ', end='')
        s = input()
        if s not in ['', 'Y', 'y']:
            print('exiting...')
            sys.exit(0)
        print()
        gameins.commit()
        print()
        appins.commit()
        print()
        print('Done.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog=sys.argv[0],
        description='install and manage mod files for BG3',
    )

    parser.add_argument('-g', '--game',
                        help='path to the game folder')
    parser.add_argument('-a', '--appdata',
                        help='path to the game\'s appdata folder')
    parser.add_argument('-s', '--steam',
                        help='path to Steam\'s main install folder')
    parser.add_argument('-n', '--dry-run', action='store_true',
                        help='print the actions to take, then exit')
    parser.add_argument('-d', '--uninstall', action='store_true',
                        help='uninstall any installed files only')
    parser.add_argument('-o', '--optional', action='store_true',
                        help='also install optional mods')

    args = parser.parse_args()
    paths = Paths.for_current_platform()
    if args.game:
        paths.game = os.path.abspath(args.game)
    if args.appdata:
        paths.appdata = os.path.abspath(args.appdata)
    if args.steam:
        paths.steam = os.path.abspath(args.steam)

    os.chdir(os.path.abspath(os.path.split(sys.argv[0])[0]))
    main(paths, args.dry_run, args.uninstall, args.optional)
