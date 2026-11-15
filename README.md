# cloudtransfer-od2 —— OneDrive 角色流程（OneDrive2 版）

> 这套流程 = **现有那套的克隆**：程序一个字没改，只把「OneDrive 角色的目录」指回
> **真实的 OneDrive2**（现有那套在 2026-11-13 之后把这些目录放到了 GoogleDrive2 的
> `onedrive/` 目录下）。
>
> 同一时刻**只开一边**：本仓库开 → 老仓库那几条要 disable；
> OneDrive2 再出问题 → 本仓库 disable，老仓库 re-enable。

## 流程清单（文件名即流程名，全部带 `-od2` 后缀）

| 流程 | 作用 | 周期 |
|---|---|---|
| in-pipeline-od2 | 上游判重 + 清上游 → 出待下载队列 | 3h |
| gen-manifest-od2 | 导出编号清单（各处判重的依据） | 3h |
| in2-ydout-od2 | `in2` 里带 `_D` 的分卷 → `ydout`（送达删源） | 6h |
| ydout-in3-od2 | `ydout` → `in3`，源归档 `out3` | 手动 |
| od2-tg-gd2-od2 | TG 新片 → GoogleDrive2（送达删源） | 6h |
| gd-out2-od2 | `gdrive2:out` 切分 → OneDrive2 `out2`，源归档 `gdrive2:out2` | 3h |
| od2-dbjm-od2 | `out2` → 豆包 `/dbjm` | 6h |
| out2-ty-sync-od2 | `out2` → 天翼，完成后归档 `gdrive2:out3` | 3h |
| gd-backup-od2 | GoogleDrive2 三目录 → GoogleDrive6 备份 | 12h |
| ty-transfer-od2 | 139 家庭云 `/in` 切分 → `ydout` | 12h |
| ydy2-transfer-od2 | 139 个人云 `/in` 切分 → `ydout` | 12h |
| out-sync-od2 | OneDrive2 成品与天翼比对（删 OneDrive 侧已有）—— **备用**：原 `out-sync` 的远端本来就是硬编码 `onedrive2`，没被迁移过，所以它留在原仓库继续跑，本仓库这份默认停用 | 12h |
| flow-status-od2 | 总览卡片 → Telegram（每 6h） | 6h |
| tg-control-od2 | Telegram 指令入口（/flow、/sub…） | 常驻 340min |
| od2-check | 自检：rclone 远端 / PATHS_JSON 键 / OneDrive2 可达性（只打印名字与计数） | 手动 |

## 路径真值

`PATHS_JSON` 由 `od2_export.py` 从老仓库的同一份 Secret **反向换算** 而来
（`gdrive2:onedrive/X` → `onedrive2:X`，`/GoogleDrive2/onedrive/X` → `/OneDrive2/X`，
容量卡片把 OneDrive2 那一行加回来）。值不出 CI，日志里只有 key 名与脱敏形状。

## 切换（同一时刻只开一边）

```bash
# 去 OneDrive2
gh workflow disable gd-out2.yml -R tammader/cloudtransfer-gd-out-pub   # 老套件逐条 disable
gh workflow enable  gd-out2-od2.yml -R tamd369/cloudtransfer-od2       # 本套件逐条 enable

# OneDrive2 再挂 → 回退
gh workflow disable gd-out2-od2.yml -R tamd369/cloudtransfer-od2
gh workflow enable  gd-out2.yml -R tammader/cloudtransfer-gd-out-pub
```

> 切换前先搬一次数据（`rclone copy` 两个方向之一），本仓库不负责搬数据。

## LADA（Colab）

`LADA_Colab3.ipynb`（OneDrive2 直连版）读写的是 OneDrive2 根目录下的
`in / lada_videos / lada_results / into / out` —— 本套件把这些目录摆回原位后，
notebook 不需要改动；只需保证 Colab Secrets 里的 `OD2_RT` 有效。
