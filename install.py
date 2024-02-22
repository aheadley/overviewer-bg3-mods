#!/usr/bin/env python3

import argparse
import ast
import json
import os
import os.path
import shutil
import sys

METAFILE = 'overviewer-bg3-mods.meta'
INSTALL = 'install'
MOVE = 'move'
MKDIR = 'mkdir'

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
        return os.path.join(appdata, 'Larian Studios', 'Baldur\'s Gate 3')

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

class MetaInstaller:
    def __init__(self, path, dry_run):
        self.root = path
        self.dry_run = dry_run
        self.metapath = os.path.join(self.root, METAFILE)
        self.meta = None
        self.removed = []
        self.added = []

        print('In', self.root)

    def uninstall(self):
        if self.meta is not None:
            raise RuntimeError('metafile must be closed to uninstall')
        if not os.path.isfile(self.metapath):
            return False
        with open(self.metapath, 'rb+') as meta:
            lines = []
            offset = 0
            for line in meta:
                lines.append((offset, json.loads(line)))
                offset += len(line)

            lines.reverse()
            for truncate_at, line in lines:
                if line[0] == INSTALL:
                    self.uninstall_file(line[1])
                elif line[0] == MOVE:
                    self.uninstall_move(line[1], line[2])
                elif line[0] == MKDIR:
                    self.uninstall_mkdir(line[1])
                else:
                    raise RuntimeError('unknown meta command {!r}'.format(line[0]))
                if not self.dry_run:
                    meta.truncate(truncate_at)
                    meta.flush()
        if lines:
            assert lines[-1][0] == 0
        if not self.dry_run:
            os.remove(self.metapath)
        return True

    def add_removed(self, path):
        if self.dry_run:
            self.removed.append(os.path.normpath(path))

    def add_added(self, path):
        if self.dry_run:
            self.added.append(os.path.normpath(path))

    def uninstall_file(self, dst):
        fulldest = os.path.join(self.root, dst)
        if self.isdir(dst):
            die('should be file, not directory:', fulldest)
        if self.isfile(dst):
            print('\t', 'remove', dst)
            if not self.dry_run:
                os.remove(fulldest)
            self.add_removed(dst)

    def uninstall_move(self, src, dst):
        fullsrc = os.path.join(self.root, src)
        fulldest = os.path.join(self.root, dst)
        if self.isdir(dst):
            die('should be file, not directory:', fulldest)
        if self.isfile(dst):
            # dst is the backup, src is where it should go now
            if self.isdir(src):
                die('should be file, not directory:', fullsrc)
            print('\t', 'move', dst, src)
            if not self.dry_run:
                shutil.copy2(fulldest, fullsrc)
                os.remove(fulldest)
            self.add_removed(dst)

    def uninstall_mkdir(self, dst):
        fulldest = os.path.join(self.root, dst)
        if self.isfile(dst):
            die('should be directory, not file:', fulldest)
        if self.isdir(dst):
            # only remove if empty
            for leaf in os.listdir(fulldest):
                if self.exists(os.path.join(dst, leaf)):
                    break
            else:
                # no file within exists
                print('\t', 'rmdir', dst)
                if not self.dry_run:
                    os.rmdir(fulldest)
                self.add_removed(dst)
        

    def __enter__(self):
        if self.meta is None:
            if not self.dry_run:
                self.meta = open(self.metapath, 'x')
        return self

    def __exit__(self, typ, value, traceback):
        if self.meta is not None:
            self.meta.close()
        self.meta = None

    def ensure_meta(self):
        if self.meta is None and not self.dry_run:
            raise RuntimeError('metafile must be open to install')

    def emit_meta(self, *args):
        print('\t', *args)
        if not self.dry_run:
            self.meta.write(json.dumps(list(args)) + '\n')
            self.meta.flush()

    def exists(self, path):
        key = os.path.normpath(path)
        if key in self.added:
            return True
        if key in self.removed:
            return False
        return os.path.exists(os.path.join(self.root, path))

    def isdir(self, path):
        key = os.path.normpath(path)
        if key in self.added:
            return True
        if key in self.removed:
            return False
        return os.path.isdir(os.path.join(self.root, path))

    def isfile(self, path):
        key = os.path.normpath(path)
        if key in self.added:
            return True
        if key in self.removed:
            return False
        return os.path.isfile(os.path.join(self.root, path))

    def move_file(self, src, dst):
        self.ensure_meta()
        self.emit_meta(MOVE, src, dst)
        fullsrc = os.path.join(self.root, src)
        fulldest = os.path.join(self.root, dst)
        if not self.isfile(src):
            die('cannot move file:', fullsrc)
        if self.exists(dst):
            die('file already exists:', fulldest)
        if not self.dry_run:
            shutil.move(fullsrc, fulldest)
        self.add_added(dst)

    def makedir(self, dst):
        self.ensure_meta()
        fulldest = os.path.join(self.root, dst)
        if self.isdir(dst):
            return
        if self.exists(dst):
            die('path expected to be directory:', fulldest)
        self.emit_meta(MKDIR, dst)
        if not self.dry_run:
            os.mkdir(fulldest)
        self.add_added(dst)

    def makedirs(self, dst):
        head, tail = os.path.split(dst)
        if not tail:
            head, tail = os.path.split(head)
        if head and tail:
            self.makedirs(head)
        self.makedir(dst)

    def install_file(self, src, dst):
        self.ensure_meta()
        head, tail = os.path.split(dst)
        if head:
            self.makedirs(head)
        fulldest = os.path.join(self.root, dst)
        if self.exists(dst):
            self.move_file(dst, dst + '.bak')
        self.emit_meta(INSTALL, dst)
        if not self.dry_run:
            shutil.copy2(src, fulldest)
        self.add_added(dst)

    def install_tree(self, src, dst):
        for subdir, dirs, files in os.walk(src):
            for file in files:
                subsrc = os.path.join(subdir, file)
                leaf = os.path.relpath(subsrc, src)
                subdst = os.path.join(dst, leaf)
                self.install_file(subsrc, subdst)

def do_install(paths, dry_run, uninstall, optional_mods):
    if uninstall:
        gameins = MetaInstaller(paths.game, dry_run)
        uninstall_did_something = gameins.uninstall()
        print()
        appins = MetaInstaller(paths.appdata, dry_run)
        uninstall_did_something = appins.uninstall() or uninstall_did_something
        return uninstall_did_something

    gameins = MetaInstaller(paths.game, dry_run)
    uninstall_did_something = gameins.uninstall()
    print()
    with gameins:
        gameins.install_tree('Data', 'Data')
        if optional_mods:
            gameins.install_tree('OPTIONAL-MODS/bin', 'bin')

    print()

    appins = MetaInstaller(paths.appdata, dry_run)
    uninstall_did_something = appins.uninstall() or uninstall_did_something
    print()
    with appins:
        appins.install_tree('Baldur\'s Gate 3', '')

    return uninstall_did_something

def main(paths, dry_run, uninstall, optional_mods):
    paths.discover()
    print()
    uninstall_did_something = do_install(paths, True, uninstall, optional_mods)
    if uninstall and not uninstall_did_something:
        print('Nothing to do.')
        sys.exit(0)

    if not dry_run:
        print()
        print('Perform actions listed above (Y/n)? ', end='')
        s = input()
        if s not in ['', 'Y', 'y']:
            print('exiting...')
            sys.exit(0)
        print()
        do_install(paths, False, uninstall, optional_mods)
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

    os.chdir(os.path.abspath(os.path.split(sys.argv[0])[0]))
    main(paths, args.dry_run, args.uninstall, args.optional)
