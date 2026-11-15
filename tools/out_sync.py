# -*- coding: utf-8 -*-
"""Out 同步清理 / 归档 (云端版, 由 GitHub Actions 定时执行)

做三件事:
  A) 天翼侧比对: OneDrive2:out / TelegramVideos 里"天翼已有且同名同大小"的文件 -> 删 OneDrive 侧
  B) **GoogleDrive2 归档**: OneDrive2:out 里"天翼没有、GoogleDrive2/out 也没有"的文件
     -> 上传到 GoogleDrive2/out, 成功后删 OneDrive 侧 (取代原来"人工复制到天翼")
  C) 产出 GoogleDrive2(out + out2 归档区) 的编号清单(gd_stems.txt) 供 ty-transfer / worker 合并比对

天翼侧挂在本机 alist, 云端访问不到 -> 读本机导出的清单:
   onedrive2:dbqd/ty_out.tsv   (天翼个人/out2      名字<TAB>字节)
   onedrive2:dbqd/ty_tg.tsv    (天翼个人/TelegramVideos)
GoogleDrive2 用 rclone 直连(gdrive2:), 但**跑之前必须先用 gd_token.py 刷新凭证**。

安全: 默认演练(--dry); --apply 才真动; 单批上限 --max-ops; 删除进 OneDrive 回收站。
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
WORK = "/tmp/outsync"
OD_DIR = "onedrive2:dbqd"
REPORT = OD_DIR + "/out_sync_report.txt"
GD_MANIFEST = OD_DIR + "/gd_stems.txt"        # GoogleDrive2/out 的编号清单(供 ty-transfer 等合并)
GD_OUT = "gdrive2:out"
# gd-out2 流水线(gd-out2.yml)会把 GD 的东西"搬进" onedrive2:out2 并把原件归档到下面的 out2,
# 编号一旦离开 out 就没人认得 -> 编号清单/已归档判断必须把 out2 一起算 (2026-09-24 加)
GD_ARCH = "gdrive2:out2"
PAIRS = [
    {"key": "out", "label": "成品 out", "od": "onedrive2:out",
     "manifest": OD_DIR + "/ty_out.tsv"},
    {"key": "tg", "label": "TelegramVideos", "od": "onedrive2:TelegramVideos",
     "manifest": OD_DIR + "/ty_tg.tsv"},
]


def find_conf():
    for c in (os.environ.get("RCLONE_CONF_PATH", ""),
              os.path.expanduser("~/.config/rclone/rclone.conf"),
              os.path.join(os.environ.get("APPDATA", ""), "rclone", "rclone.conf"),
              os.path.expanduser("~/AppData/Roaming/rclone/rclone.conf")):
        if c and os.path.exists(c):
            return c
    return os.path.expanduser("~/.config/rclone/rclone.conf")


CONF = find_conf()


def rclone(args, timeout=3600):
    return subprocess.run(["rclone"] + args + ["--config", CONF],
                          capture_output=True, text=True, errors="replace",
                          timeout=timeout)


def human(b):
    return "%.0f MB" % (b / 1048576) if b < 1024 ** 3 else "%.2f GB" % (b / 1024 ** 3)


def stem(name):
    s = os.path.splitext(name)[0]
    s = re.sub(r"_D$", "", s)
    s = re.sub(r"^(已处理_|已下载_|D_)", "", s)
    s = re.sub(r"\.part\d+$", "", s)
    return s.strip().lower()


def load_manifest(remote):
    """拉天翼清单 -> ({名字: 大小}, 说明)"""
    fp = os.path.join(WORK, os.path.basename(remote))
    r = rclone(["copyto", remote, fp], timeout=600)
    if r.returncode != 0 or not os.path.exists(fp):
        return {}, "清单拉取失败: %s" % (r.stderr or "")[:80]
    out, stamp = {}, ""
    for line in io.open(fp, encoding="utf-8"):
        line = line.rstrip("\n")
        if line.startswith("#"):
            stamp = line.strip("# ").strip()
            continue
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            try:
                out[parts[0]] = int(parts[1])
            except ValueError:
                pass
    return out, stamp


def lsjson(remote):
    r = rclone(["lsjson", remote], timeout=3600)
    if r.returncode != 0:
        raise RuntimeError("lsjson %s 失败: %s" % (remote, (r.stderr or "")[:160]))
    items = json.loads(r.stdout or "[]")
    return {x["Name"]: int(x.get("Size") or 0) for x in items if not x.get("IsDir")}


def refresh_gd_token():
    """跑 rclone 前刷新 gdrive2 凭证(见 gd_token.py 说明)"""
    try:
        import gd_token
        rc = gd_token.main()
        if rc != 0:
            print("  !! gd_token 刷新返回 %s" % rc)
            return False
        return True
    except Exception as e:
        print("  !! gd_token 刷新异常: %s" % str(e)[:120])
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max-ops", type=int, default=200)
    a = ap.parse_args()
    os.makedirs(WORK, exist_ok=True)
    print("rclone 配置:", CONF)

    lines = ["# Out 同步/归档报告  %s  [%s]"
             % (time.strftime("%Y-%m-%d %H:%M:%S"),
                "执行模式" if a.apply else "演练模式(dry-run)")]
    ops = 0

    # GoogleDrive2 侧(先刷 token)
    gd_ok = refresh_gd_token()
    gd = {}
    if gd_ok:
        try:
            gd = lsjson(GD_OUT)
            n_out = len(gd)
            try:
                arch = lsjson(GD_ARCH)
            except Exception as e:
                arch = {}
                print("  !! 读归档区 %s 失败(只按 out 算): %s" % (GD_ARCH, str(e)[:100]))
                lines.append("\n!! 读归档区 %s 失败: %s" % (GD_ARCH, str(e)[:120]))
            dup = len(set(gd) & set(arch))
            for k, v in arch.items():
                gd.setdefault(k, v)
            print("[GoogleDrive2] out %d 个 + out2(归档) %d 个 = 去重后 %d 个文件"
                  % (n_out, len(arch), len(gd)))
            lines.append("\n[GoogleDrive2] out %d 个 + out2(归档) %d 个 = %d 个(重名 %d)"
                         % (n_out, len(arch), len(gd), dup))
        except Exception as e:
            print("  !! gdrive2 读取失败: %s" % str(e)[:180])
            lines.append("\n!! GoogleDrive2 读取失败: %s" % str(e)[:150])
            gd_ok = False
    else:
        lines.append("\n!! gd_token 刷新失败, 跳过 GoogleDrive2 相关动作")

    # 写 gd 编号清单(供 ty-transfer 合并比对)
    if gd_ok:
        stems = sorted({stem(n) for n in gd})
        tmp = os.path.join(WORK, "gd_stems.txt")
        io.open(tmp, "w", encoding="utf-8").write(
            "# GoogleDrive2/out 编号清单\n"
            "# 由 out_sync.py 自动生成, 供 ty-transfer / worker 合并比对\n"
            "# 更新时间: %s | 文件 %d 个 | 编号 %d 个\n"
            % (time.strftime("%Y-%m-%d %H:%M:%S"), len(gd), len(stems))
            + "\n".join(stems) + "\n")
        rc = rclone(["copyto", tmp, GD_MANIFEST], timeout=600)
        print("  gd 编号清单: %d 个 -> %s (%s)"
              % (len(stems), GD_MANIFEST, "OK" if rc.returncode == 0 else "失败"))
        lines.append("  gd 编号清单: %d 个 -> %s" % (len(stems), GD_MANIFEST))

    # A) 天翼侧比对(原有逻辑)
    for p in PAIRS:
        print()
        print("=" * 62)
        print("[%s] OneDrive 侧: %s" % (p["label"], p["od"]))
        ty, stamp = load_manifest(p["manifest"])
        if not ty:
            msg = "天翼清单为空/读不到 -> 跳过该组"
            print("  !! " + msg)
            lines.append("\n[%s] %s" % (p["label"], msg))
            continue
        print("  天翼清单: %d 个文件 [%s]" % (len(ty), stamp or "无时间戳"))
        try:
            od = lsjson(p["od"])
        except Exception as e:
            print("  !! %s" % str(e)[:150])
            lines.append("\n[%s] OneDrive 读取失败: %s" % (p["label"], str(e)[:120]))
            continue
        print("  OneDrive: %d 个文件" % len(od))

        same, conflict, todo = [], [], []
        for n, s in od.items():
            if n in ty:
                (same if ty[n] == s else conflict).append((n, s, ty[n]))
            else:
                todo.append((n, s))
        print("  对比: 天翼已归档 %d | 冲突 %d | 待归档 %d"
              % (len(same), len(conflict), len(todo)))
        lines.append("\n[%s] OneDrive %d | 天翼 %d | 天翼已归档 %d | 冲突 %d | 待归档 %d"
                     % (p["label"], len(od), len(ty), len(same), len(conflict), len(todo)))

        if same and a.apply and len(same) <= a.max_ops:
            ff = os.path.join(WORK, "_del_%s.txt" % p["key"])
            io.open(ff, "w", encoding="utf-8").write("\n".join(n for n, _, _ in same))
            r = rclone(["delete", p["od"], "--files-from", ff,
                        "--retries", "3", "--log-level", "WARNING"])
            after = lsjson(p["od"])
            gone = [n for n, _, _ in same if n not in after]
            ops += len(gone)
            print("  已删除(天翼已归档) %d 个" % len(gone))
            lines.append("  已删除 OneDrive 侧 %d 个(回收站可捞)" % len(gone))
        elif same:
            print("  (演练) 可删 %d 个, 示例: %s" % (len(same), ", ".join(n for n, _, _ in same[:4])))
            lines.append("  可删(天翼已归档) %d 个" % len(same))

        if conflict:
            print("  冲突(同名不同大小): %s"
                  % "; ".join("%s(%s vs %s)" % (n, human(s), human(t))
                              for n, s, t in conflict[:4]))
        # 待归档 -> 交给 B 段(只处理 out 组)
        if p["key"] == "out" and todo:
            print("  待归档(天翼没有): %d 个" % len(todo))
            lines.append("  待归档(天翼没有): %d 个" % len(todo))

    # B) 用 GoogleDrive2/out 归档 OneDrive2:out 里"两边都没有"的文件
    print()
    print("=" * 62)
    print("[GoogleDrive2 归档] %s -> %s" % ("onedrive2:out", GD_OUT))
    if not gd_ok:
        print("  !! 跳过(GoogleDrive2 不可用)")
    else:
        ty, _ = load_manifest(PAIRS[0]["manifest"])
        try:
            od = lsjson("onedrive2:out")
        except Exception as e:
            od = {}
            print("  !! 读 OneDrive2:out 失败: %s" % str(e)[:120])
        to_up, already, conflict2 = [], [], []
        for n, s in od.items():
            if n in gd:
                (already if gd[n] == s else conflict2).append(n)
            elif n in ty and ty[n] == s:
                pass                                  # 天翼已归档, A 段会删
            else:
                to_up.append((n, s))
        print("  OneDrive out %d | GoogleDrive2 out %d | 需上传 %d | 已在 GD %d | 冲突 %d"
              % (len(od), len(gd), len(to_up), len(already), len(conflict2)))
        lines.append("  OneDrive out %d | GD out %d | 需上传 %d | 已在 GD %d"
                     % (len(od), len(gd), len(to_up), len(already)))
        if to_up:
            print("  待上传示例: %s" % ", ".join("%s(%s)" % (n, human(s)) for n, s in to_up[:5]))
            lines.append("  待上传示例: " + ", ".join(n for n, _ in to_up[:5]))
            if a.apply and len(to_up) <= a.max_ops:
                ff = os.path.join(WORK, "_up.txt")
                io.open(ff, "w", encoding="utf-8").write("\n".join(n for n, _ in to_up))
                # rclone move = 复制成功才删源(进回收站由 --drive-use-trash 控制)
                r = rclone(["move", "onedrive2:out", GD_OUT, "--files-from", ff,
                            "--drive-use-trash=false", "--retries", "3",
                            "--stats", "0", "-v"], timeout=10800)
                after_gd = lsjson(GD_OUT)
                after_od = lsjson("onedrive2:out")
                moved = [n for n, _ in to_up if n in after_gd and n not in after_od]
                ops += len(moved)
                print("  已归档到 GoogleDrive2: %d 个 (退出码 %d)"
                      % (len(moved), r.returncode))
                lines.append("  已归档上传到 GoogleDrive2/out: %d 个" % len(moved))
                if r.returncode != 0:
                    print("  !! rclone 退出码 %d: %s" % (r.returncode, (r.stderr or "")[:200]))
                    lines.append("  !! rclone 报错: %s" % (r.stderr or "")[:150])
            elif to_up:
                print("  (演练) 不上传; 加 --apply 生效")
                lines.append("  (演练) 未上传")

    lines.append("\n合计操作 %d 次 | 模式: %s"
                 % (ops, "执行" if a.apply else "预览"))
    print()
    print("=" * 62)
    print("合计操作 %d 次" % ops)
    rp = os.path.join(WORK, "out_sync_report.txt")
    io.open(rp, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    rc = rclone(["copyto", rp, REPORT], timeout=600)
    print("报告上传 %s: %s" % (REPORT, "OK" if rc.returncode == 0 else "失败"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
