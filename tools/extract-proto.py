#!/usr/bin/env python3
"""
Pull the protobuf schema straight out of the vendor app's exe.

`Insta360 Link Controller.exe` is a C++ protobuf build, so every .proto it was compiled
from is embedded verbatim as a serialized FileDescriptorProto. That gives real field and
enum names — no guessing, no disassembler, no protobuf module needed.

    ./extract-proto.py                             all three schemas
    ./extract-proto.py --exe /path/to/other.exe    after an app update

The names this prints are authoritative. `insta360.md` quotes them; when they disagree,
the exe wins.
"""

import argparse
import mmap
import re
import sys

DEFAULT_EXE = '/mnt/winos/Program Files/Insta360 Link Controller/Insta360 Link Controller.exe'

TYPES = {1: 'double', 2: 'float', 3: 'int64', 4: 'uint64', 5: 'int32', 6: 'fixed64',
         7: 'fixed32', 8: 'bool', 9: 'string', 10: 'group', 11: 'message', 12: 'bytes',
         13: 'uint32', 14: 'enum', 15: 'sfixed32', 16: 'sfixed64', 17: 'sint32', 18: 'sint64'}
LABELS = {1: 'optional', 2: 'required', 3: 'repeated'}


def varint(b, i):
    r = s = 0
    while True:
        c = b[i]; i += 1
        r |= (c & 0x7f) << s
        if not c & 0x80:
            return r, i
        s += 7
        if s > 70:
            raise ValueError('varint too long')


def fields(b):
    i = 0
    while i < len(b):
        key, i = varint(b, i)
        num, wire = key >> 3, key & 7
        if num == 0:
            raise ValueError('field 0')
        if wire == 0:
            v, i = varint(b, i)
        elif wire == 2:
            ln, i = varint(b, i)
            v, i = b[i:i+ln], i + ln
            if len(v) != ln:
                raise ValueError('truncated')
        elif wire == 5:
            v, i = b[i:i+4], i + 4
        elif wire == 1:
            v, i = b[i:i+8], i + 8
        else:
            raise ValueError(f'wire type {wire}')
        yield num, wire, v


def consume(m, off, limit=0x40000):
    """Greedily take the longest prefix at off that parses as protobuf."""
    b, i = m[off:off+limit], 0
    while i < len(b):
        try:
            key, j = varint(b, i)
            num, wire = key >> 3, key & 7
            if num == 0 or num > 60 or wire not in (0, 1, 2, 5):
                break
            if wire == 0:
                _, j = varint(b, j)
            elif wire == 2:
                ln, j = varint(b, j)
                if ln > limit:
                    break
                j += ln
            elif wire == 5:
                j += 4
            else:
                j += 8
            if j > len(b):
                break
            i = j
        except (ValueError, IndexError):
            break
    return b[:i]


def parse_enum(buf):
    name, vals = None, []
    for n, _, v in fields(buf):
        if n == 1:
            name = v.decode('utf8', 'replace')
        elif n == 2:
            vn, num = None, 0
            for n2, _, v2 in fields(v):
                if n2 == 1:
                    vn = v2.decode('utf8', 'replace')
                elif n2 == 2:
                    num = v2
            vals.append((vn, num))
    return name, vals


def parse_msg(buf):
    name, flds, enums, nested = None, [], [], []
    for n, _, v in fields(buf):
        if n == 1:
            name = v.decode('utf8', 'replace')
        elif n == 2:
            fn, fnum, ftype, flabel, tname = None, 0, 0, 0, ''
            for n2, _, v2 in fields(v):
                if n2 == 1:
                    fn = v2.decode('utf8', 'replace')
                elif n2 == 3:
                    fnum = v2
                elif n2 == 4:
                    flabel = v2
                elif n2 == 5:
                    ftype = v2
                elif n2 == 6:
                    tname = v2.decode('utf8', 'replace')
            flds.append((fnum, fn, LABELS.get(flabel, '?'), tname or TYPES.get(ftype, str(ftype))))
        elif n == 3:
            nested.append(parse_msg(v))
        elif n == 4:
            enums.append(parse_enum(v))
    return name, flds, enums, nested


def parse_file(buf):
    fname, pkg, msgs, enums = None, None, [], []
    for n, _, v in fields(buf):
        if n == 1:
            fname = v.decode('utf8', 'replace')
        elif n == 2:
            pkg = v.decode('utf8', 'replace')
        elif n == 4:
            msgs.append(parse_msg(v))
        elif n == 5:
            enums.append(parse_enum(v))
    return fname, pkg, msgs, enums


def print_msg(msg, indent=''):
    name, flds, enums, nested = msg
    print(f'{indent}message {name} {{')
    for num, fn, lab, t in flds:
        print(f'{indent}  {num:>3} {lab:<8} {t:<28} {fn}')
    for en, vals in enums:
        print(f'{indent}  enum {en}: ' + ', '.join(f'{n}={v}' for n, v in vals))
    for nm in nested:
        print_msg(nm, indent + '  ')
    print(f'{indent}}}')


def descriptor_starts(m):
    """A FileDescriptorProto opens with 0a <len> <name>.proto — find each one."""
    for mt in re.finditer(rb'[\x20-\x7e]{4,60}\.proto', m):
        name_len = mt.end() - mt.start()
        off = mt.start() - 2
        if off < 0 or m[off] != 0x0a or m[off + 1] != name_len:
            continue
        yield off, m[mt.start():mt.end()].decode()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--exe', default=DEFAULT_EXE)
    args = ap.parse_args()

    with open(args.exe, 'rb') as f:
        m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        seen = set()
        for off, name in descriptor_starts(m):
            if name in seen:
                continue
            raw = consume(m, off)
            try:
                fname, pkg, msgs, enums = parse_file(raw)
            except (ValueError, IndexError) as e:
                print(f'# {name} at {off:#x}: unparsable ({e})', file=sys.stderr)
                continue
            if not msgs and not enums:
                continue
            seen.add(name)
            print(f'\n########## {fname}  (offset {off:#x}, {len(raw)} bytes)')
            for msg in msgs:
                print_msg(msg)
            for en, vals in enums:
                print(f'enum {en} {{')
                for n, v in sorted(vals, key=lambda x: x[1]):
                    print(f'  {v:>4} {n}')
                print('}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
