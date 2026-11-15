# -*- coding: utf-8 -*-
"""自检: 只打印「名字 / 键名 / 计数」, 不打印任何路径真值与 token。

用来确认本仓库这套流程的配置是齐的(OneDrive2 版):
  1) RCLONE_CONF 里有哪些远端(名字只给 sha1[:8]) + 是否含旧/新远端
  2) PATHS_JSON 的 key 清单 + 每个 key 的「形状」(远端名脱敏, 目录名保留)
  3) 关键 key 是否都指向 OneDrive2(只看前缀判定, 不回显值)
  4) rclone 连不连得上(只回 ok/失败)
"""
import hashlib
import io
import json
import os
import subprocess
import sys

import pathcfg

HERE = os.path.dirname(os.path.abspath(__file__))
NEED = ["GD_DST", "GD_SRC", "DBJM_SRC", "TY_SRC", "GM_OD", "GR_A_SRC", "GR_B_DST",
        "GR_TG_SRC", "GR_REPORT", "GB_REPORT", "ID_OD_DIRS", "ID_QUEUE", "ID_REPORT",
        "ID_STEM_MANIFESTS", "TT_REMOTE", "TT_COMPARE_REMOTES", "TT_OD_MANIFEST",
        "TT_GD_MANIFEST", "OT_DAILY", "OT_REPORT", "OT_SRC", "OT_ARCH", "TT_OD_DEST",
        "YDY_OD_DEST", "GR_B_SRC", "GB_SRC_ROOT", "GB_DST_ROOT", "GB_DIRS",
        "FS_QUOTA", "FS_DESC", "FS_GROUPS", "FS_ADVICE", "_WORDS"]


def h8(s):
    return hashlib.sha1((s or "").encode()).hexdigest()[:8]


def conf_remotes():
    p = os.environ.get("RCLONE_CONF_PATH") or os.path.expanduser("~/.config/rclone/rclone.conf")
    out = []
    try:
        for l in io.open(p, encoding="utf-8").read().splitlines():
            s = l.strip()
            if s.startswith("[") and s.endswith("]"):
                out.append(s[1:-1])
    except Exception as e:
        print("  !! 读 rclone.conf 失败: %s" % e)
    return out


def shape(v):
    if not isinstance(v, str):
        return repr(v)[:60]
    out = []
    for one in v.split(","):
        s = one.strip()
        if not s:
            continue
        if ":" in s and not s.startswith("/"):
            r, p = s.split(":", 1)
            out.append("<r:%s>:%s" % (h8(r), p))
        elif s.startswith("/"):
            seg = s.strip("/").split("/")
            out.append("<m:%s>/%s" % (h8("/" + seg[0]), "/".join(seg[1:])))
        else:
            out.append(s)
    return ",".join(out)


def main():
    print("==== 1) rclone 远端(名字脱敏) ====")
    rs = conf_remotes()
    for r in rs:
        print("   <r:%s>  %s" % (h8(r), "** = 目标远端 OneDrive2" if r == "onedrive2" else
                                 ("** = 源侧远端" if r in ("gdrive2", "gdrive6") else "")))
    print("   段数=%d  含 onedrive2=%s" % (len(rs), "onedrive2" in rs))

    print("\n==== 2) PATHS_JSON 键 ====")
    d = dict(pathcfg._load())
    print("   key 数=%d" % len(d))
    print("   缺的 key: %s" % ([k for k in NEED if k not in d] or "无"))

    print("\n==== 3) 关键路径的形状(远端名脱敏, 目录名保留) ====")
    for k in sorted(d):
        if k.startswith("FS_") or k == "_WORDS":
            continue
        print("   %-22s %s" % (k, shape(d[k])[:110]))

    print("\n==== 4) 指向 OneDrive2 的 key 个数 ====")
    n_od2 = sum(1 for k, v in d.items()
                if isinstance(v, str) and v.replace(",", " ").startswith("onedrive2")
                or (isinstance(v, str) and ",onedrive2" in v))
    print("   前缀命中 onedrive2 的 key: %d 个" % n_od2)
    print("   FS_QUOTA 行数: %s" % len(json.loads(d.get("FS_QUOTA", "[]"))))

    print("\n==== 5) rclone 可达性(只回 ok/失败) ====")
    for rm in ("onedrive2:", "gdrive2:"):
        try:
            r = subprocess.run(["rclone", "lsd", rm, "--max-depth", "1",
                                "--timeout", "30s", "--contimeout", "15s"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
            out = r.stdout.decode("utf-8", "replace").strip().splitlines()
            print("   %-12s %s  顶层目录 %d 个" % (rm, "ok" if r.returncode == 0 else "失败", len(out)))
        except Exception as e:
            print("   %-12s 失败 %s" % (rm, str(e)[:60]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
