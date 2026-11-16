# -*- coding: utf-8 -*-
"""在 runner 里: 读 PATHS_JSON 现值 -> 把"落地目标=天翼个人/out2"相关的键改成 ydy2/out2
-> 加密写回为【新】Secret PATHS_JSON_YDY2 (旧 PATHS_JSON 不动)。
只打印键名与替换计数, 值不出日志.
用法: python make_ydy2_paths.py [--apply]
"""
import base64, json, os, sys, urllib.error, urllib.request

REPO = os.environ.get("REPO", "tamd369/cloudtransfer-od2")
API = "https://api.github.com"
TOK = (os.environ.get("GH_PAT") or os.environ.get("GH_TOKEN") or "").strip()
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
APPLY = "--apply" in sys.argv

# 只替换这些（天翼个人/out2 -> ydy2/out2 出现在"落地/判重"含义处）；
# 用整串替换，注意 alist: 前缀的变体也覆盖到。
OLD = "天翼个人/out2"
NEW = "ydy2/out2"

# 只改这些键（避免误改到比如 ID_* 里不该动的）
TARGET_KEYS = {"OT_TY", "OT_TY_CHECK", "GM_TY_OUT", "GM_STEM_DIRS",
               "TT_COMPARE_REMOTES_LOCAL", "TY_DST"}


def gh(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Authorization": "token " + TOK, "User-Agent": "mk-ydy2",
                                          "Accept": "application/vnd.github+json",
                                          "Content-Type": "application/json"})
    try:
        with OP.open(req, timeout=90) as x:
            t = x.read().decode()
            return x.status, (json.loads(t) if t.strip() else {})
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def set_secret(name, value):
    st, d = gh("GET", "/repos/%s/actions/secrets/public-key" % REPO)
    if st != 200:
        print("!! public-key 失败 %s %s" % (st, str(d)[:150])); return False
    from nacl import encoding, public as npub
    pk = npub.PublicKey(d["key"].encode(), encoding.Base64Encoder())
    enc = base64.b64encode(npub.SealedBox(pk).encrypt(value.encode())).decode()
    st, _ = gh("PUT", "/repos/%s/actions/secrets/%s" % (REPO, name),
               {"encrypted_value": enc, "key_id": d["key_id"]})
    print("Secret %-18s -> %s (%d 字节)" % (name, st, len(value)))
    return st in (201, 204)


raw = os.environ.get("PATHS_JSON", "")
if not raw.strip():
    print("!! 环境里没有 PATHS_JSON"); sys.exit(1)

d = json.loads(raw)
print("PATHS_JSON 现有 %d 个键" % len(d))
changed = []
for k in list(d.keys()):
    v = d.get(k)
    if not isinstance(v, str):
        continue
    if k in TARGET_KEYS and OLD in v:
        d[k] = v.replace(OLD, NEW)
        print("  改键 %-26s (含 '%s' x%d)" % (k, OLD, v.count(OLD)))
        changed.append(k)

# 额外检查: 有没有 TARGET_KEYS 里没匹配到的（防止键名漂移）
for k in TARGET_KEYS:
    if k in d and changed and k not in changed and isinstance(d.get(k), str) and OLD not in d[k]:
        print("  (注意: %s 已不含 '%s', 跳过)" % (k, OLD))

print("将改 %d 个键: %s" % (len(changed), ", ".join(changed)))
if len(changed) < 5:
    print("!! 改动键数偏少(<5), 疑似键名/结构不符, 拒绝写入")
    sys.exit(3)

out = json.dumps(d, ensure_ascii=False)
if not APPLY:
    print("(dry) 加 --apply 才写 PATHS_JSON_YDY2")
    sys.exit(0)
ok = set_secret("PATHS_JSON_YDY2", out)
sys.exit(0 if ok else 2)
