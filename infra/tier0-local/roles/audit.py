"""Harness auditor (root + DAC_READ_SEARCH only, no network). Modes: perms <path> | scan <marker> <path>... | list <path>"""
import json, os, stat, sys
mode = sys.argv[1]
if mode == "perms":
    rows = []
    for root, dirs, files in os.walk(sys.argv[2]):
        for n in dirs + files:
            st = os.lstat(os.path.join(root, n)); rows.append({"path": os.path.relpath(os.path.join(root, n), sys.argv[2]), "mode": oct(stat.S_IMODE(st.st_mode)), "uid": st.st_uid, "dir": stat.S_ISDIR(st.st_mode)})
    st = os.lstat(sys.argv[2]); rows.append({"path": ".", "mode": oct(stat.S_IMODE(st.st_mode)), "uid": st.st_uid, "dir": True})
    print(json.dumps(rows))
elif mode == "scan":
    marker = sys.argv[2].encode(); hits = []
    for base in sys.argv[3:]:
        for root, _d, files in os.walk(base):
            for n in files:
                p = os.path.join(root, n)
                try:
                    if marker in open(p, "rb").read(): hits.append(p)
                except OSError: pass
    print(json.dumps(hits))
elif mode == "list":
    print(json.dumps(sorted(os.path.relpath(os.path.join(r, n), sys.argv[2]) for r, d, f in os.walk(sys.argv[2]) for n in d + f)))
