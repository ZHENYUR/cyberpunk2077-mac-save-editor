# Cyberpunk 2077 存档修改器 (Mac)

修改赛博朋克 2077 Mac 原生版（Steam）存档。支持：
钱、属性点、专长点、街头声望、玩家等级、快速破解组件、升级组件、弹药。

## 用法

```bash
cd "/Users/lawrence/Desktop/Useful Script/cyberpunk-save-editor"

# 交互式菜单（推荐）
python3 edit_save.py

# 一键全部拉满（最新存档）
python3 edit_save.py --all

# 单项
python3 edit_save.py --money 100000
python3 edit_save.py --quickhack 999    # 快速破解组件
python3 edit_save.py --upgrade 999      # 义体/武器升级组件
python3 edit_save.py --ammo 9999        # 弹药

# 指定存档 + 自定义值
python3 edit_save.py --save ManualSave-2 --money 500000 --attr 50 --perk 50 --cred 50
```

## 交互菜单

```
[1] 钱 (eddies)        改成 999 万
[2] 属性点 (unspent)   改成 999
[3] 专长点 (Primary)   改成 999
[4] 街头声望           改成 50 (满级)
[5] 玩家等级           改成 60 (满级)
[6] 快速破解组件       Tier 2/3/4/5 改成 999
[7] 升级组件 (义体/武器) 白/绿/蓝/紫/橙 改成 999
[8] 弹药               全部改成 9999
[9] 一键全部拉满
```

## 改完之后

1. 完全关闭游戏（Cmd+Q，不是回主菜单）
2. 启动 Cyberpunk 2077
3. 加载你修改的存档（建议读手动存档，AutoSave 会被覆盖）
4. **立刻在游戏里手动 save 一个新槽位**

## 安全说明

- 每次保存会自动把原 `sav.dat` 备份为 `backup_N.dat`
- 想回滚就在终端跑：
  ```bash
  cd ~/Library/Application\ Support/CD\ Projekt\ Red/Cyberpunk\ 2077/saves/<存档名>
  mv sav.dat sav.dat.bad && mv backup_1.dat sav.dat
  ```

## 数值上限建议

| 项 | 推荐值 | 游戏上限 |
|---|---|---|
| 钱 | 9,999,999 | 没有显示上限 |
| 属性点 / 专长点 | 999 | 单属性最大 20 |
| 街头声望 | 50 | **50（必须 ≤ 50）** |
| 玩家等级 | 60 | **60** |
| 快速破解组件 | 999 | 各 tier |
| 升级组件 | 999 | 各品质 |
| 弹药 | 9999 | 各类型 |

## 技术原理（踩坑记录）

修改分两类，机制完全不同：

**1. 属性点 / 专长点 / 声望 / 等级** — 走 `cp2077save` 的节点 API
（`PlayerDevelopmentData` 等），原地改值，安全。

**2. 钱 / 组件 / 弹药** — inventory 节点里的可堆叠物品
- CP2077 inventory 是**嵌套子节点树**。每个物品 = 父预告头
  `NextItemEntry`(TdbId+Header) + 子节点 `ItemData`(NodeId+TdbId+Header
  +Flags+CreationTime+Quantity)。父子两份 TdbId 头加载时必须逐字节相等。
- **真正的 quantity 在「第二个 hash(子节点 TdbId) + 21 字节」**
  = 子节点 body offset 24。只改这 4 字节，绝不碰 NodeId/TdbId/Header。
- TweakDBID = **标准 CRC32** (zlib) + 1 字节名长 + 3 字节 0。
  （注意：物品/弹药都是标准 CRC32，不是 CRC32C。弹药用 `Ammo.` 前缀。）
- 背包里**不存在**的物品无法凭空添加（需新增子节点，会改变节点大小，
  破坏偏移目录）。所以 Tier 5 组件等需先在游戏里获得至少 1 个。

**LZ4 修复**：`cp2077chunk.py` 原本的 LZ4 data setter 是「假压缩」
（literal copy，不压缩），导致改存档后文件涨 ~5%，游戏拒绝加载。
已改用真正的 `lz4.block.compress(mode='high_compression')`。

**车辆解锁不支持**：车库在 `PersistencySystem2`（7.4MB RED4 序列化 blob）
里，解锁 = 往变长数组加 record，需完整 RED4 反序列化（只有 Windows 版
CyberCAT 能做）。游戏内做 Gigs / fixer 购买才是正路。

## 依赖

```bash
pip3 install lz4 --break-system-packages   # 真 LZ4 压缩需要
```

## 文件结构

```
cyberpunk-save-editor/
├── edit_save.py       # 主脚本（交互 + CLI）
├── cp2077save.py      # 核心存档读写
├── cp2077node.py      # 节点解析
├── cp2077chunk.py     # FZLC/LZ4（修复 VALID_CAPACITY=0x200 + 真 LZ4 压缩）
├── cp2077type.py      # 类型系统
├── LICENSE            # 原作者 (fmwviormv) 的 LICENSE
└── README.md          # 本文件
```

## 致谢

存档读写核心来自 [fmwviormv/CyberpunkPythonHacks](https://github.com/fmwviormv/CyberpunkPythonHacks)（ISC 协议）。
本项目的修改：
- `cp2077chunk.py`：`VALID_CAPACITY` 加 `0x200` 支持 Mac 版存档；LZ4 setter 改用真压缩。
- `edit_save.py`：全部修改功能（MIT 协议）。

物品/车辆存档结构的研究参考了
[WolvenKit/CyberCAT](https://github.com/WolvenKit/CyberCAT) 与
[CyberCAT-SimpleGUI](https://github.com/Deweh/CyberCAT-SimpleGUI) 的源码。
