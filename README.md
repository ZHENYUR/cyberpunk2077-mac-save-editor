# Cyberpunk 2077 存档修改器 (Mac)

修改赛博朋克 2077 Mac 原生版（Steam）存档：钱、属性点、专长点、街头声望。

## 用法

```bash
cd "/Users/lawrence/Desktop/Useful Script/cyberpunk-save-editor"

# 交互式菜单（推荐）
python3 edit_save.py

# 命令行 - 一键全部拉满（最新存档）
python3 edit_save.py --all

# 命令行 - 只改钱
python3 edit_save.py --money 100000

# 指定存档
python3 edit_save.py --save ManualSave-2 --all

# 自定义值
python3 edit_save.py --money 500000 --attr 50 --perk 50 --cred 50
```

## 改完之后

1. 完全关闭游戏
2. 启动 Cyberpunk 2077
3. 加载你修改的存档（最新自动存档槽位会变，建议读手动存档）
4. **立刻在游戏里手动 save 一个新槽位**（防止 AutoSave 覆盖）

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
| 属性点 | 999 | 单属性最大 20 |
| 专长点 | 999 | 看不同分支 |
| 街头声望 | 50 | **50（必须 ≤ 50）** |

## 已知限制

- **只支持 Mac 原生版**（VASC/FZLC 格式，capacity = 0x200）。Windows 版用 CyberCAT-SimpleGUI。
- 字符串索引每个存档可能不同，脚本会动态查询，理论上每次保存都安全。
- 钱的定位用 TweakDB hash + 唯一性验证，避免改错位置。
- 属性点/专长点修改用"重命名 spent → unspent"的取巧方法（保留原值，但语义换了）。

## 文件结构

```
cyberpunk-save-editor/
├── edit_save.py       # 主脚本（交互 + CLI）
├── cp2077save.py      # 核心存档读写
├── cp2077node.py      # 节点解析
├── cp2077chunk.py     # FZLC/LZ4 解压（已修复 VALID_CAPACITY 支持 0x200）
├── cp2077type.py      # 类型系统
├── LICENSE            # 原作者 (fmwviormv) 的 LICENSE
└── README.md          # 本文件
```

## 致谢

存档读写核心来自 [fmwviormv/CyberpunkPythonHacks](https://github.com/fmwviormv/CyberpunkPythonHacks)。
我修改了 `cp2077chunk.py` 的 `VALID_CAPACITY` 来支持 Mac 版存档（capacity = 0x200）。
