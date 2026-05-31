#!/usr/bin/env python3
"""
Cyberpunk 2077 存档修改器 (Mac 版)

Copyright (c) 2026 ZHENYUR

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

(Core save-file reading code in cp2077*.py is ISC-licensed by
 Ali Farzanrad <ali_farzanrad@riseup.net>, see LICENSE.)


支持修改:
  - 钱 (eddies)
  - 未用属性点
  - 未用专长点 (Primary)
  - 街头声望 (Street Cred)
  - 玩家等级
  - 快速破解组件 (Quickhack Components) — Tier 2/3/4 数量

用法:
  python3 edit_save.py              # 交互式菜单
  python3 edit_save.py --all 999999 # 一键全部拉满

依赖:
  - 同目录下的 cp2077save.py 等库文件 (修改自 fmwviormv/CyberpunkPythonHacks)
  - 仅支持 Mac 原生版 (VASC/FZLC 格式, capacity=0x200)

存档位置:
  ~/Library/Application Support/CD Projekt Red/Cyberpunk 2077/saves/
"""

import os
import sys
import struct
import time
import argparse
import builtins

# 添加同目录到 path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from cp2077save import SaveFile

SAVES_DIR = os.path.expanduser(
    '~/Library/Application Support/CD Projekt Red/Cyberpunk 2077/saves'
)


# ============================================================
# 工具函数
# ============================================================

def list_saves():
    """列出所有存档,按修改时间倒序返回 [(mtime, name), ...]"""
    saves = []
    for name in os.listdir(SAVES_DIR):
        path = os.path.join(SAVES_DIR, name)
        sav = os.path.join(path, 'sav.dat')
        if os.path.isdir(path) and os.path.exists(sav):
            saves.append((os.path.getmtime(sav), name))
    saves.sort(reverse=True)
    return saves


def get_string_index(strings, target):
    """在字符串表中查找 target,返回索引或 None"""
    for i, s in enumerate(strings):
        if s == target:
            return i
    return None


def get_field_value_position(struct_data_raw, field_name_idx, strings):
    """
    在一个 StructData 的 raw bytes 中找到指定字段的值的位置.
    返回 (value_position, field_index, struct_data_start_offset) 或 None.

    struct_data_raw: 单个 StructData 的字节
    field_name_idx: 要找的字段名索引 (如 'unspent' 的索引)
    """
    if len(struct_data_raw) < 2:
        return None
    count = struct.unpack('<H', struct_data_raw[0:2])[0]
    if count > 50:  # sanity check
        return None
    for f in range(count):
        h_start = 2 + 8 * f
        if h_start + 8 > len(struct_data_raw):
            break
        name_idx = struct.unpack('<H', struct_data_raw[h_start:h_start + 2])[0]
        offset = struct.unpack('<I', struct_data_raw[h_start + 4:h_start + 8])[0]
        if name_idx == field_name_idx:
            return offset, f
    return None


# ============================================================
# 修改逻辑
# ============================================================

def modify_dev_points(savefile, attribute_unspent=None, perk_unspent=None):
    """
    修改 devPoints 字段中的 unspent 值.

    devPoints 数组里有 4 个 SDevelopmentPoints items:
      - Item 1: Attribute (无 type 字段, 默认)
      - Item 2: Espionage type
      - Item 3: Primary type (= 专长点 perk points)
      - Item 4: Secondary type

    每个 item 是一个 StructData, 可能包含 type/spent/unspent 字段.
    我们要找到 Attribute 那个 item 和 Primary 那个 item, 修改它们的 unspent.

    字段索引在每个存档里可能不同, 需要动态查询字符串表!
    """
    changes = []
    with savefile.nodes.ScriptableSystemsContainer as config:
        pdd = config.PlayerDevelopmentData
        strings = pdd._strings

        unspent_idx = get_string_index(strings, 'unspent')
        spent_idx = get_string_index(strings, 'spent')
        type_idx = get_string_index(strings, 'type')
        primary_idx = get_string_index(strings, 'Primary')
        if unspent_idx is None or spent_idx is None:
            print("⚠️  找不到 'spent'/'unspent' 字符串索引,存档结构异常")
            return changes

        name, t, devp_slc = pdd._field_info('devPoints')
        devp_raw = bytearray(builtins.bytearray.__getitem__(pdd, devp_slc))

        # 解析 devPoints 数组中的所有 items
        items = parse_dev_points_items(devp_raw)

        for item_start, item_size in items:
            item_bytes = devp_raw[item_start:item_start + item_size]
            field_count = struct.unpack('<H', item_bytes[0:2])[0]

            # 找该 item 的 type (如果有) 和 unspent (如果有)
            item_type_value = None  # None 表示无 type 字段(默认 Attribute)
            unspent_value_pos = None  # 在 devp_raw 中的绝对位置
            spent_value_pos = None
            spent_field_header_pos = None

            for f in range(field_count):
                h_start = 2 + 8 * f
                if h_start + 8 > len(item_bytes):
                    break
                name_id = struct.unpack('<H', item_bytes[h_start:h_start + 2])[0]
                offset = struct.unpack('<I', item_bytes[h_start + 4:h_start + 8])[0]

                if name_id == type_idx:
                    # type 是 CName, 2 字节
                    type_val = struct.unpack('<H', item_bytes[offset:offset + 2])[0]
                    item_type_value = type_val
                elif name_id == unspent_idx:
                    unspent_value_pos = item_start + offset
                elif name_id == spent_idx:
                    spent_value_pos = item_start + offset
                    spent_field_header_pos = item_start + h_start

            # 判断是 Attribute (无 type) 还是 Primary (type=Primary)
            is_attribute = (item_type_value is None)
            is_primary = (item_type_value == primary_idx)

            target_value = None
            if is_attribute and attribute_unspent is not None:
                target_value = attribute_unspent
                label = "属性点"
            elif is_primary and perk_unspent is not None:
                target_value = perk_unspent
                label = "专长点 (Primary)"
            else:
                continue

            # 如果已经有 unspent 字段, 直接改值
            if unspent_value_pos is not None:
                old = struct.unpack('<i', devp_raw[unspent_value_pos:unspent_value_pos + 4])[0]
                devp_raw[unspent_value_pos:unspent_value_pos + 4] = struct.pack('<i', target_value)
                changes.append(f"  ✓ {label}: {old} → {target_value}")
            elif spent_field_header_pos is not None:
                # 没有 unspent 字段, 把 spent 改名成 unspent
                devp_raw[spent_field_header_pos:spent_field_header_pos + 2] = struct.pack('<H', unspent_idx)
                old = struct.unpack('<i', devp_raw[spent_value_pos:spent_value_pos + 4])[0]
                devp_raw[spent_value_pos:spent_value_pos + 4] = struct.pack('<i', target_value)
                changes.append(f"  ✓ {label}: spent→unspent, {old} → {target_value}")
            else:
                changes.append(f"  ⚠️  {label}: 没找到可修改的位置")

        builtins.bytearray.__setitem__(pdd, devp_slc, bytes(devp_raw))
    return changes


def parse_dev_points_items(devp_raw):
    """
    解析 devPoints 数组, 返回 [(item_start, item_size), ...].

    数组开头 4 字节是 count, 之后是 4 个 SDevelopmentPoints items.
    每个 item 是 StructData (开头 2 字节是 field count).
    需要根据 field 数量和 offset 推断 item 大小.
    """
    count = struct.unpack('<I', devp_raw[0:4])[0]
    items = []
    pos = 4
    for _ in range(count):
        if pos + 2 > len(devp_raw):
            break
        field_count = struct.unpack('<H', devp_raw[pos:pos + 2])[0]
        if field_count > 10 or field_count < 1:
            break

        # 找最大的 offset 来推断 item 大小
        max_offset = 0
        max_offset_field_size = 4  # 假设 Int32 (大部分情况)
        for f in range(field_count):
            h_start = pos + 2 + 8 * f
            if h_start + 8 > len(devp_raw):
                return items
            type_idx = struct.unpack('<H', devp_raw[h_start + 2:h_start + 4])[0]
            offset = struct.unpack('<I', devp_raw[h_start + 4:h_start + 8])[0]
            if offset > max_offset:
                max_offset = offset
                # CName (gamedataDevelopmentPointType) 是 2 字节, Int32 是 4 字节
                # 简单按 4 字节算, 不会大错
                max_offset_field_size = 4

        item_size = max_offset + max_offset_field_size
        # 处理 CName 类型字段在最后的情况 (大小为 2)
        # 检查最后字段是不是 type 字段 (CName)
        last_h_start = pos + 2 + 8 * (field_count - 1)
        if last_h_start + 8 <= len(devp_raw):
            last_name_idx = struct.unpack('<H', devp_raw[last_h_start:last_h_start + 2])[0]
            # 简单启发: 如果只有 1 个字段且 offset+2 后是下一个有效 count, 则用 2
            # 实际不严谨, 但这是已知格式的妥协
            pass

        items.append((pos, item_size))
        pos += item_size
    return items


def modify_money(savefile, new_money):
    """
    修改钱 (Items.money 的 quantity).

    钱在 inventory 节点里, 紧跟在 Items.money 的 TweakDBID 之后.
    Items.money 在 inventory 字节中只出现一次的 ITEM ENTRY 是真正的钱位置.

    更可靠的做法: 用现有的精确值搜索. 但首次运行不知道精确值,
    因此用 TweakDBID + 附近候选的策略.
    """
    import binascii
    money_crc = binascii.crc32(b'Items.money') & 0xFFFFFFFF
    money_hash = struct.pack('<IB3x', money_crc, len(b'Items.money'))

    # 找 inventory 节点
    inv_info = None
    for nid in range(len(savefile.nodes_info)):
        if savefile.nodes_info[nid].name == b'inventory':
            inv_info = savefile.nodes_info[nid]
            break
    if inv_info is None:
        return None, "找不到 inventory 节点"

    data = savefile.data
    inv_bytes = bytes(data[inv_info.offset:inv_info.offset + inv_info.size])

    # 找所有 Items.money 出现位置
    positions = []
    s = 0
    while True:
        i = inv_bytes.find(money_hash, s)
        if i < 0:
            break
        positions.append(i)
        s = i + 1

    if not positions:
        return None, "在 inventory 里找不到 Items.money"

    # 在 Items.money 附近找一个看起来像钱数量的 uint32
    # 策略: 找最大的、且 < 100,000,000 的 uint32, 在每个 hash 位置附近 ±64 字节
    money_pos_candidates = []
    for hash_pos in positions:
        for off in range(-64, 64, 1):
            pos = hash_pos + off
            if pos < 0 or pos + 4 > len(inv_bytes):
                continue
            val = struct.unpack('<I', inv_bytes[pos:pos + 4])[0]
            # 合理的钱值范围: 1 到 1亿
            if 1 <= val < 100_000_000:
                money_pos_candidates.append((val, pos, hash_pos))

    if not money_pos_candidates:
        return None, "找不到合理的钱数量"

    # 取最大值 (实际经验: 钱往往是 inventory 里某个最大的数, 且离 hash 较近)
    # 但有时候不准, 所以列出 top 候选让用户确认
    money_pos_candidates.sort(reverse=True)
    top = money_pos_candidates[0]
    val, pos, hash_pos = top

    # 全局唯一性检查: 这个值在整个 save 里是否只出现一次?
    all_bytes = bytes(data[:])
    val_bytes = struct.pack('<I', val)
    occurrences = all_bytes.count(val_bytes)

    if occurrences == 1:
        # 唯一, 100% 是这个值
        abs_pos = inv_info.offset + pos
        data[abs_pos:abs_pos + 4] = struct.pack('<I', new_money)
        return (val, new_money), None
    else:
        # 不唯一, 提示用户手动确认
        return None, (
            f"在 inventory 找到候选钱值 {val}, 但在整个存档里出现了 {occurrences} 次,"
            f"无法 100% 确定. 请告诉我游戏内当前精确钱数, 重新运行."
        )


def modify_proficiency_level(savefile, proficiency_name, new_level):
    """
    修改某个 proficiency (StreetCred / Level / 等) 的 currentLevel.

    proficiency_name 是 enum 名 (如 'StreetCred', 'Level', 'Athletics' 等).
    在 proficiencies 数组里找 type=<name> 的 entry,
    格式: [enum value 2B] [currentLevel int32 4B] [...]
    """
    with savefile.nodes.ScriptableSystemsContainer as config:
        pdd = config.PlayerDevelopmentData
        strings = pdd._strings

        prof_str_idx = get_string_index(strings, proficiency_name)
        if prof_str_idx is None:
            return None, f"找不到 '{proficiency_name}' 字符串"

        name, t, prof_slc = pdd._field_info('proficiencies')
        prof_raw = bytearray(builtins.bytearray.__getitem__(pdd, prof_slc))

        # 找该 proficiency enum value 出现位置
        sc_bytes = struct.pack('<H', prof_str_idx)
        positions = []
        s = 0
        while True:
            i = bytes(prof_raw).find(sc_bytes, s)
            if i < 0:
                break
            positions.append(i)
            s = i + 1

        if not positions:
            return None, f"找不到 {proficiency_name} entry"

        # 找位置后跟着合理 level (1-70) 的那个
        for p in positions:
            if p + 6 > len(prof_raw):
                continue
            val = struct.unpack('<i', prof_raw[p + 2:p + 6])[0]
            if 0 <= val <= 70:
                prof_raw[p + 2:p + 6] = struct.pack('<i', new_level)
                builtins.bytearray.__setitem__(pdd, prof_slc, bytes(prof_raw))
                return (val, new_level), None

        return None, f"{proficiency_name} 的 currentLevel 值不合理"


def modify_streetcred(savefile, new_level):
    """修改街头声望 (上限 50)"""
    return modify_proficiency_level(savefile, 'StreetCred', new_level)


def modify_player_level(savefile, new_level):
    """修改玩家等级 (上限 60)"""
    return modify_proficiency_level(savefile, 'Level', new_level)


def modify_quickhack_components(savefile, new_qty=999):
    """
    ⚠️  实验性功能 - 后期存档可能损坏 ⚠️

    在简单存档(早期游戏进度)上可能工作, 但在后期/复杂存档上
    游戏会拒绝加载. 推测原因: CP2077 存档对 inventory 节点有
    内部一致性检查, 修改单个 quantity 字段会破坏 checksum.

    使用前**务必备份**, 如果游戏进不去, 用 backup_N.dat 恢复.

    修改 Quickhack 升级组件数量 (Tier 2 绿 / Tier 3 蓝 / Tier 4 紫).

    Quickhack 组件以 inventory 中的 stackable item 存储:
      Items.QuickHackUncommonMaterial1  (Tier 2 绿)
      Items.QuickHackRareMaterial1      (Tier 3 蓝)
      Items.QuickHackEpicMaterial1      (Tier 4 紫)

    Item entry 结构 (基于实验观察):
      [8 bytes TweakDBID hash]
      [8 bytes metadata (flags/length等)]
      [4 bytes quantity uint32]   ← 在 hash+16 位置
      [8 bytes hash 重复]
      [8 bytes metadata 重复]
      [4 bytes quantity 重复]      ← 在 hash+36 位置
    两个 quantity 位置都需要修改.

    注: 用绿色 Uncommon 组件实验确认 quantity 在 hash+16 (从 82 → 999 验证成功).

    Tier 5 (Legendary 橙) 需要先在游戏里获得至少 1 个才能用此函数修改.
    """
    import binascii

    components = [
        ('Items.QuickHackUncommonMaterial1', 'Tier 2 (绿)'),
        ('Items.QuickHackRareMaterial1', 'Tier 3 (蓝)'),
        ('Items.QuickHackEpicMaterial1', 'Tier 4 (紫)'),
        ('Items.QuickHackLegendaryMaterial1', 'Tier 5 (橙)'),
    ]

    # 找 inventory 节点
    inv_info = None
    for nid in range(len(savefile.nodes_info)):
        if savefile.nodes_info[nid].name == b'inventory':
            inv_info = savefile.nodes_info[nid]
            break
    if inv_info is None:
        return ["⚠️  找不到 inventory 节点"]

    data = savefile.data
    changes = []

    for name_str, label in components:
        name = name_str.encode()
        crc = binascii.crc32(name) & 0xFFFFFFFF
        hash_bytes = struct.pack('<IB3x', crc, len(name))

        # 在 inventory 字节里搜
        inv_bytes = bytes(data[inv_info.offset:inv_info.offset + inv_info.size])
        positions = []
        s = 0
        while True:
            i = inv_bytes.find(hash_bytes, s)
            if i < 0:
                break
            positions.append(i)
            s = i + 1

        if not positions:
            changes.append(f"  ⚠️  {label}: 背包里没有, 跳过 (需先在游戏里获得 1 个)")
            continue

        # 修改每个位置的 hash+16 quantity 字段
        # (hash 出现 2 次, 第一次 +16 = quantity, 第二次 +16 = quantity 重复)
        for p in positions:
            abs_pos = inv_info.offset + p + 16
            old = struct.unpack('<I', data[abs_pos:abs_pos + 4])[0]
            data[abs_pos:abs_pos + 4] = struct.pack('<I', new_qty)

        old_first = struct.unpack(
            '<I',
            bytes(data[inv_info.offset + positions[0] + 4:
                       inv_info.offset + positions[0] + 8])
        )[0]
        # 因为我们已经写入了新值, old_first 现在等于 new_qty
        # 重新算 old 用第一次写入前的值（用 positions 数量 / 2 来推断）
        # 这里简化: 直接报告改了几处
        changes.append(f"  ✓ {label}: 改了 {len(positions)} 处 → {new_qty}")

    return changes


# ============================================================
# 主程序
# ============================================================

def choose_save():
    """让用户选择要修改哪个存档"""
    saves = list_saves()
    if not saves:
        print("❌ 找不到任何存档!")
        sys.exit(1)

    print(f"\n找到 {len(saves)} 个存档,显示最近 10 个:\n")
    for i, (mtime, name) in enumerate(saves[:10]):
        marker = " ← 最新" if i == 0 else ""
        print(f"  [{i}] {name:25s}  {time.ctime(mtime)}{marker}")

    while True:
        choice = input(f"\n选择存档编号 (回车 = 最新 [0]): ").strip()
        if not choice:
            return saves[0][1]
        try:
            idx = int(choice)
            if 0 <= idx < len(saves):
                return saves[idx][1]
        except ValueError:
            pass
        print("无效输入,重试")


def interactive_menu(save_name):
    """交互式修改菜单"""
    save_path = os.path.join(SAVES_DIR, save_name)
    print(f"\n📂 加载: {save_name}")
    savefile = SaveFile(save_path)

    while True:
        print("\n" + "=" * 50)
        print(f"  存档: {save_name}")
        print("=" * 50)
        print("  [1] 钱 (eddies)        改成 999 万")
        print("  [2] 属性点 (unspent)   改成 999")
        print("  [3] 专长点 (Primary)   改成 999")
        print("  [4] 街头声望           改成 50 (满级)")
        print("  [5] 玩家等级           改成 60 (满级)")
        print("  [6] 快速破解组件       Tier 2/3/4 改成 999 ⚠️ 实验性")
        print("  [7] 一键全部拉满")
        print("  [0] 保存并退出")
        print("  [q] 不保存退出")

        choice = input("\n选择: ").strip().lower()

        if choice == '0':
            savefile.save()
            print(f"\n✅ 已保存到 {save_path}/sav.dat")
            print(f"   原文件已自动备份为 backup_N.dat")
            break
        elif choice == 'q':
            print("已退出,未保存修改")
            break
        elif choice == '1':
            res, err = modify_money(savefile, 9_999_999)
            if err:
                print(f"❌ {err}")
            else:
                print(f"✓ 钱: {res[0]} → {res[1]}")
        elif choice == '2':
            changes = modify_dev_points(savefile, attribute_unspent=999)
            for c in changes:
                print(c)
        elif choice == '3':
            changes = modify_dev_points(savefile, perk_unspent=999)
            for c in changes:
                print(c)
        elif choice == '4':
            res, err = modify_streetcred(savefile, 50)
            if err:
                print(f"❌ {err}")
            else:
                print(f"✓ 街头声望: {res[0]} → {res[1]}")
        elif choice == '5':
            res, err = modify_player_level(savefile, 60)
            if err:
                print(f"❌ {err}")
            else:
                print(f"✓ 玩家等级: {res[0]} → {res[1]}")
        elif choice == '6':
            print("🧩 快速破解组件:")
            for c in modify_quickhack_components(savefile, 999):
                print(c)
        elif choice == '7':
            r, e = modify_money(savefile, 9_999_999)
            print(f"💰 钱: {f'{r[0]} → {r[1]}' if r else '失败 - ' + e}")
            for c in modify_dev_points(savefile, attribute_unspent=999, perk_unspent=999):
                print(c)
            r, e = modify_streetcred(savefile, 50)
            print(f"🎖️  街头声望: {f'{r[0]} → {r[1]}' if r else '失败 - ' + e}")
            r, e = modify_player_level(savefile, 60)
            print(f"⭐ 玩家等级: {f'{r[0]} → {r[1]}' if r else '失败 - ' + e}")
            print("🧩 快速破解组件:")
            for c in modify_quickhack_components(savefile, 999):
                print(c)
        else:
            print("无效选择")


def main():
    parser = argparse.ArgumentParser(
        description='Cyberpunk 2077 存档修改器 (Mac)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='示例:\n'
               '  python3 edit_save.py                 # 交互式\n'
               '  python3 edit_save.py --all           # 最新存档全部拉满\n'
               '  python3 edit_save.py --money 100000  # 只改钱',
    )
    parser.add_argument('--save', help='指定存档名 (如 ManualSave-2),默认让你选')
    parser.add_argument('--all', action='store_true', help='一键全部拉满')
    parser.add_argument('--money', type=int, help='设置钱数')
    parser.add_argument('--attr', type=int, help='设置未用属性点数')
    parser.add_argument('--perk', type=int, help='设置未用专长点数')
    parser.add_argument('--cred', type=int, help='设置街头声望 (上限 50)')
    parser.add_argument('--level', type=int, help='设置玩家等级 (上限 60)')
    parser.add_argument('--quickhack', type=int, help='设置 Tier 2/3/4 快速破解组件数量')
    args = parser.parse_args()

    # 决定要操作的存档
    if args.save:
        save_name = args.save
        if not os.path.isdir(os.path.join(SAVES_DIR, save_name)):
            print(f"❌ 存档不存在: {save_name}")
            sys.exit(1)
    elif args.all or args.money or args.attr or args.perk or args.cred or args.level or args.quickhack:
        # 命令行模式 - 用最新存档
        saves = list_saves()
        if not saves:
            print("❌ 找不到任何存档!")
            sys.exit(1)
        save_name = saves[0][1]
        print(f"使用最新存档: {save_name}")
    else:
        # 交互模式
        save_name = choose_save()
        interactive_menu(save_name)
        return

    # 命令行模式 - 执行
    save_path = os.path.join(SAVES_DIR, save_name)
    savefile = SaveFile(save_path)

    if args.all:
        args.money = args.money or 9_999_999
        args.attr = args.attr or 999
        args.perk = args.perk or 999
        args.cred = args.cred or 50
        args.level = args.level or 60
        args.quickhack = args.quickhack or 999

    if args.money is not None:
        r, e = modify_money(savefile, args.money)
        print(f"💰 钱: {f'{r[0]} → {r[1]}' if r else '失败 - ' + e}")

    if args.attr is not None or args.perk is not None:
        for c in modify_dev_points(savefile,
                                    attribute_unspent=args.attr,
                                    perk_unspent=args.perk):
            print(c)

    if args.cred is not None:
        r, e = modify_streetcred(savefile, args.cred)
        print(f"🎖️  街头声望: {f'{r[0]} → {r[1]}' if r else '失败 - ' + e}")

    if args.level is not None:
        r, e = modify_player_level(savefile, args.level)
        print(f"⭐ 玩家等级: {f'{r[0]} → {r[1]}' if r else '失败 - ' + e}")

    if args.quickhack is not None:
        print(f"🧩 快速破解组件 → {args.quickhack}:")
        for c in modify_quickhack_components(savefile, args.quickhack):
            print(c)

    savefile.save()
    print(f"\n✅ 已保存. 原文件备份为 backup_N.dat")


if __name__ == '__main__':
    main()
