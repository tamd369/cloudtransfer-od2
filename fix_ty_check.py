# -*- coding: utf-8 -*-
"""在 runner 里读 PATHS_JSON 现值 -> 把 天翼家庭/out2 全替换成 天翼家庭/out7 -> 加密回写。
只改这一个子串出现的键；其它键原样保留；值不出日志(只打键名与替换计数)。
用法: python fix_ty_check.py [--apply]
"""
import base64, io, json, os, sys, urllib.error, urllib.request

REPO = os.environ.get("REPO", "tamd369/cloudtransfer-od2")
API = "https://api.github.com"
TOK = (os.environ.get("GH_PAT") or os.environ.get("GH_TOKEN") or "").strip()
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
APPLY = "--apply" in sys.argv

OLD = "天翼家庭/out2"
NEW = "天翼家庭/out7"


def gh(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Authorization": "token " + TOK, "User-Agent": "fix-ty",
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
    print("Secret %-12s -> %s (%d 字节)" % (name, st, len(value)))
    return st in (201, 204)


raw = os.environ.get("PATHS_JSON", "")
if not raw.strip():
    print("!! 环境里没有 PATHS_JSON（workflow 需注入该 Secret）"); sys.exit(1)

d = json.loads(raw)
print("PATHS_JSON 现有 %d 个键" % len(d))
changed = []
for k, v in list(d.items()):
    if isinstance(v, str) and OLD in v:
        nv = v.replace(OLD, NEW)
        print("  改键 %-24s (含 '%s' x%d)" % (k, OLD, v.count(OLD)))
        d[k] = nv
        changed.append(k)

if not changed:
    print("没有键含 '%s'，无需修改" % OLD)
    sys.exit(0)

print("将修改 %d 个键: %s" % (len(changed), ", ".join(changed)))
out = json.dumps(d, ensure_ascii=False)
if not APPLY:
    print("(dry) 加 --apply 才写回 Secret")
    sys.exit(0)
ok = set_secret("PATHS_JSON", out)
sys.exit(0 if ok else 2)
