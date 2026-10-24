"""Turn the read-only baseline manifest into a human-reviewable diff table.

Every row is classified as exactly one of:

  已正式打包        the running artifact comes from an installed apk package
  运行时手工安装    present on the phone but owned by no package
  实验或诊断        bring-up capture / probe logic, not needed for normal boot
  不确定待查        origin cannot be established from the captured evidence

The output is deliberately explicit about what could not be read (root-only
paths) instead of filling gaps from older reports.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PACKAGED = '已正式打包'
MANUAL = '运行时手工安装'
DIAGNOSTIC = '实验或诊断'
UNKNOWN = '不确定待查'

# What the packaged baseline now provides, keyed by runtime path/name.
# (target description, current classification of the running artifact)
RECOVERED = {
    '/etc/systemd/system/pja110-boot-success.service':
        ('/usr/lib/systemd/system/pja110-boot-success.service（device-oneplus-xigua 1-r7）',
         MANUAL),
    '/usr/local/libexec/pja110-mark-a-success':
        ('/usr/libexec/pja110-mark-a-success（device-oneplus-xigua 1-r7）', MANUAL),
    '/usr/local/libexec/pja110-qbootctl':
        ('/usr/bin/qbootctl（Alpine qbootctl 0.2.2-r1）', MANUAL),
    '/usr/local/lib/pja110/qcom_battmgr.ko':
        ('/lib/modules/6.14.0-oneplus-xigua/kernel/drivers/power/supply/qcom_battmgr.ko'
         '（linux-oneplus-xigua 6.14-r2）', MANUAL),
    '/usr/local/lib/pja110/qcom-spmi-adc5-gen3.ko':
        ('/lib/modules/6.14.0-oneplus-xigua/kernel/drivers/iio/adc/qcom-spmi-adc5-gen3.ko'
         '（linux-oneplus-xigua 6.14-r2）', MANUAL),
    '/usr/local/libexec/pja110-charger-capture': ('停用；诊断内容不入包', DIAGNOSTIC),
    '/usr/local/libexec/pja110-wifi-probe': ('停用；诊断内容不入包', DIAGNOSTIC),
    '/usr/local/libexec/pja110-wifi-clean-boot': ('停用；诊断内容不入包', DIAGNOSTIC),
    '/usr/local/libexec/pja110-wifi-aston-rfkill-test': ('停用；诊断内容不入包', DIAGNOSTIC),
    'pja110-battmgr-readonly.service': ('由 qcom_battmgr 自动加载取代', DIAGNOSTIC),
    'pja110-adc-test.service': ('由 qcom-spmi-adc5-gen3 自动加载取代', DIAGNOSTIC),
    'pja110-charger-capture.service': ('诊断采集，无功能依赖', DIAGNOSTIC),
    'pja110-wifi-probe.service': ('诊断采集，无功能依赖', DIAGNOSTIC),
    'pja110-wifi-clean-boot.service': ('诊断采集，无功能依赖', DIAGNOSTIC),
    'pja110-wifi-aston-rfkill.service': ('诊断采集，无功能依赖', DIAGNOSTIC),
}


def owner_of(ownership, path):
    for line in ownership:
        if line.startswith('OWN ') and line.split(' :: ')[0][4:] == path:
            return line.split(' :: ', 1)[1]
    return ''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--manifest', default='out/baseline-20261017/baseline-manifest.json')
    ap.add_argument('--out', default='out/baseline-20261017/diff-table.md')
    args = ap.parse_args()

    m = json.loads((ROOT / args.manifest).read_text())
    lines = []
    add = lines.append

    add('# PJA110 原生基线差异表')
    add('')
    add(f"采集时间：{m.get('generated_at')}；主机：{m['device']['host']}；"
        f"内核：`{m['identity'].get('uname', '')}`")
    add('')
    add(f"机器可读清单：`{args.manifest}`。本表只依据本轮只读采集，"
        "不从历史报告补写无法读取的内容。")
    add('')
    add('## 1. 已安装本地包（运行时）')
    add('')
    add('| 包 | 归属 | 分类 |')
    add('| --- | --- | --- |')
    for pkg in m['packages']['installed']:
        if any(pkg.startswith(p) for p in ('device-oneplus-xigua', 'linux-oneplus-xigua',
                                           'firmware-oneplus-xigua', 'phoc-')):
            add(f'| `{pkg}` | apk 数据库 | {PACKAGED} |')
    add('')

    add('## 2. pja110-* 服务')
    add('')
    add('| Unit | enabled | 启用来源 | 分类 | 说明 |')
    add('| --- | --- | --- | --- | --- |')
    for name, unit in sorted(m['units'].items()):
        key = name
        target, cls = RECOVERED.get(key, (None, None))
        if target is None:
            if unit.get('enabled') == 'static':
                cls, target = PACKAGED, '包内置（静态）'
            else:
                cls, target = MANUAL, '无 apk 归属，手工放入 /etc/systemd/system'
        add(f"| `{name}` | {unit.get('enabled') or '?'} | {target} | {cls} | "
            f"`{unit.get('fragment') or '?'}` |")
    add('')

    add('## 3. 脚本、模块与二进制')
    add('')
    add('| 路径 | SHA256/大小 | apk 归属 | 分类 | 处理 |')
    add('| --- | --- | --- | --- | --- |')
    for f in m['runtime']['local_files']:
        path = f['path']
        if path.endswith('.ko'):
            continue  # listed with modinfo details in the module loop below
        target, cls = RECOVERED.get(path, ('无', MANUAL))
        add(f"| `{path}` | `{f['sha256'][:16]}…` / {f['bytes']} B | 无 | {cls} | {target} |")
    for path, info in sorted(m['runtime']['local_modules'].items()):
        target, cls = RECOVERED.get(path, ('无', MANUAL))
        mi = info.get('modinfo', {})
        add(f"| `{path}` | `{(info.get('sha256') or '')[:16]}…` | 无 | {cls} | "
            f"version={mi.get('version', '?')}；{target} |")
    add('')

    add('## 4. 内核模块加载顺序（节选）')
    add('')
    order = [x['name'] for x in m['modules']['load_order']]
    add('加载顺序：' + ' → '.join(f'`{n}`' for n in order[:14]) + ' …')
    add('')
    add('| 模块 | 版本 | 参数 |')
    add('| --- | --- | --- |')
    for name, params in sorted(m['modules']['parameters'].items()):
        clean = {k: v for k, v in params.items() if k not in ('version', 'srcversion')}
        add(f"| `{name}` | {params.get('version') or '-'} | "
            f"{', '.join(f'{k}={v}' for k, v in clean.items()) or '-'} |")
    add('')

    add('## 5. 各包与装载路径')
    add('')
    add('| 位置 | 结论 |')
    add('| --- | --- |')
    add('| 单电池 battmgr | 6.14-r1 无补丁；6.14-r2 以 `qcom-battmgr-single-battery.patch` 打入 |')
    add('| ADC Gen3 | 6.14-r1 无；6.14-r2 以 pin 到上游提交的源码 + 兼容补丁在树内编译 |')
    add('| 启动标记 | 手工 `/usr/local`；1-r6 起为设备包内 unit + 脚本，qbootctl 用发行版 |')
    add('| 设备树 | 包内 `verified-vendor.dtb` 仅参考；A 槽 vendor_boot 由离线生成器复用已装镜像 |')
    add('')

    add('## 6. 运行 DT 与包内 `verified-vendor.dtb` 的语义对比')
    add('')
    dt = m['device_tree']
    add(f"- 运行节点数 {dt['running_nodes']}；参考 DTB 节点数 {dt['reference_nodes']}。")
    add(f"- 根 compatible：运行 `{dt['running_root_compatible']}`；"
        f"参考 `{dt['reference_root_compatible']}`。")
    add(f"- 根 model：运行 `{dt['running_root_model']}`；"
        f"参考 `{dt['reference_root_model']}`。")
    add(f"- 参考 DTB 的全部 {dt['reference_nodes']} 个节点都在运行树中出现；"
        f"运行树多出 {len(dt['nodes_only_running'])} 个节点。")
    add('')
    add('| 差异 | 运行值 | 参考值 | 分类 | 说明 |')
    add('| --- | --- | --- | --- | --- |')
    for path, props in dt['property_changes'].items():
        for key, values in props.items():
            run = str(values['running'])[:70].replace('|', '\\|')
            ref = str(values['reference'])[:70].replace('|', '\\|')
            if path == '/' and key == 'model':
                cls, note = MANUAL, '厂商 DTBO 覆盖 model；compatible 与身份未变'
            elif path == '/chosen':
                cls, note = MANUAL, '引导器写入 cmdline / initrd 边界'
            elif path.startswith('/memory'):
                cls, note = MANUAL, '引导器按实际 16 GB 内存改写'
            else:
                cls, note = UNKNOWN, '引导器或 DTBO 追加'
            add(f'| `{path}` `{key}` | `{run}` | `{ref}` | {cls} | {note} |')
    add('')
    add(f"仅在运行树出现的节点共 {len(dt['nodes_only_running'])} 个，按来源分为：")
    add('')
    add('| 来源 | 节点 | 分类 |')
    add('| --- | --- | --- |')
    groups = {
        '厂商 DTBO / 引导器（thermal、hypervisor、clocks、pmic-glink 端口）': MANUAL,
        '本机重建标记（xigua-rebuild-r1、xigua-avb-control）': DIAGNOSTIC,
        'WCN7850 电源域补充节点': MANUAL,
        '其他待查': UNKNOWN,
    }
    buckets = {k: [] for k in groups}
    for node in dt['nodes_only_running']:
        low = node.lower()
        if 'xigua-rebuild' in low or 'avb-control' in low:
            buckets['本机重建标记（xigua-rebuild-r1、xigua-avb-control）'].append(node)
        elif 'wcn7850' in low:
            buckets['WCN7850 电源域补充节点'].append(node)
        elif any(k in low for k in ('thermal', 'hypervisor', 'clocks', 'cpu-map',
                                    'pmic-glink', 'ddr-regions', 'firmware')):
            buckets['厂商 DTBO / 引导器（thermal、hypervisor、clocks、pmic-glink 端口）'].append(node)
        else:
            buckets['其他待查'].append(node)
    for group, cls in groups.items():
        nodes = buckets[group]
        if not nodes:
            continue
        shown = '、'.join(f'`{n}`' for n in nodes[:6])
        more = f' 等 {len(nodes)} 个' if len(nodes) > 6 else ''
        add(f'| {group} | {shown}{more} | {cls} |')
    add('')

    add('## 7. 无法读取的缺项（需要 root）')
    add('')
    add('| 项目 | 原因 | 状态 |')
    add('| --- | --- | --- |')
    for gap in m['gaps']:
        add(f"| {gap['item']}（`{gap['path']}`） | {gap['reason']} | {gap['status']} |")
    add('')
    add('这些缺项在获得一次交互式 sudo 会话后补齐；在此之前不以历史哈希代替本轮读回。')
    add('')

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    # Explicit UTF-8: the table is Chinese text and must not follow the host locale.
    out.write_bytes(('\n'.join(lines) + '\n').encode('utf-8'))
    print(f'wrote {out}')


if __name__ == '__main__':
    main()
