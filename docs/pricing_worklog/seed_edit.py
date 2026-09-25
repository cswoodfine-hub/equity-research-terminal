"""Edit one row of a seed in place, or insert a row after it, keeping every other line as is.
  from seed_edit import edit_row, insert_after"""
import csv, io, pathlib

def _parse(path):
    raw = pathlib.Path(path).read_bytes().decode("utf-8")
    lines = raw.splitlines(keepends=True)
    header = None
    for l in lines:
        if not l.startswith("#") and l.strip():
            header = next(csv.reader([l])); break
    return lines, header

def _fmt(header, d, ending):
    buf = io.StringIO(); csv.writer(buf, lineterminator="").writerow([d.get(h, "") for h in header])
    return buf.getvalue() + ending

def edit_row(path, match, change):
    """match(fields)->bool; change(fields)->None mutates. Returns rows changed."""
    lines, header = _parse(path); out = []; n = 0; seen_header = False
    for l in lines:
        if l.startswith("#") or not l.strip(): out.append(l); continue
        cells = next(csv.reader([l]))
        if not seen_header: seen_header = True; out.append(l); continue
        d = dict(zip(header, cells))
        if match(d):
            change(d); out.append(_fmt(header, d, l[len(l.rstrip("\r\n")):])); n += 1
        else: out.append(l)
    pathlib.Path(path).write_bytes("".join(out).encode("utf-8")); return n

def insert_after(path, match, new):
    lines, header = _parse(path); out = []; n = 0; seen_header = False
    for l in lines:
        out.append(l)
        if l.startswith("#") or not l.strip(): continue
        if not seen_header: seen_header = True; continue
        d = dict(zip(header, next(csv.reader([l]))))
        if match(d) and n == 0:
            out.append(_fmt(header, new, l[len(l.rstrip("\r\n")):] or "\n")); n += 1
    pathlib.Path(path).write_bytes("".join(out).encode("utf-8")); return n
