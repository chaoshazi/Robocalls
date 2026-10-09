'''灌一批演示数据，方便直接打开界面就能看到完整流程。

用法（在仓库根目录跑）：
    python -X utf8 scripts/seed_demo.py
    python -X utf8 scripts/seed_demo.py --reset    # 先清空所有表再灌（危险，仅本地）

灌完的形态：
- 名单批次一：CRM 线索（WAHU_CRM_MODE=fake 时用内置假数据，ID 与 D:\crm 演示数据一致）；
- 名单批次二：本地上传的演示名单（4 个号码），**故意一条都不呼**，留给你在工作台点「拨号」；
- 任务一跑完 2 通（成交 / 无意向），并走完 CRM 回写，用来演示通话记录与报表；
- 一条黑名单、一个话术脚本与一个机器人任务（默认不启动）。
'''

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.container import Container  # noqa: E402
from app.core.config import get_settings  # noqa: E402

CRM_BATCH_NAME = '演示：CRM 线索'
IMPORT_BATCH_NAME = '演示：本地上传名单'
HISTORY_BATCH_NAME = '演示：历史通话（已跑完）'

# 演示号码，刻意避开 CRM 线索里已经用掉的 13800000001/2，免得被库内去重挡掉
DEMO_ROWS = (
    ('13910000001', '示例：海联能源', '周凯'),
    ('13910000002', '示例：万景医疗', '刘畅'),
    ('13910000003', '示例：正弘物流', '马超'),
    ('13910000004', '示例：青岩环保', '孙婷'),
)

SCRIPT_CONTENT = {
    'opening': '您好，我是{company}的小王，请问是{name}吗？',
    'nodes': [
        {
            'id': 'n1',
            'say': '想跟您确认一下，贵司近期有采购计划吗？',
            'keywords': {'有': 'n2', '没有': None},
            'default': 'n2',
            'intent': 'B',
        },
        {
            'id': 'n2',
            'say': '方便的话我加您微信，把资料发您看看？',
            'keywords': {'方便': 'n3', '不方便': None},
            'default': 'n3',
        },
        {'id': 'n3', 'say': '好的，那我稍后把资料整理好发您。', 'keywords': {}, 'default': None},
    ],
    'closing': '好的，打扰了，祝您生活愉快。',
}

OUTCOMES = (
    ('deal', 'A', '客户确认要方案，周五前给报价。', '周五前发报价单'),
    ('not_interested', 'D', '客户说今年预算已用完。', None),
)

# 历史通话：让通话记录与报表有内容可看（号码刻意避开上面用过的）
HISTORY_ROWS = (
    ('13930000001', '示例：恒润重工', '陈斌'),
    ('13930000002', '示例：领航教育', '林芳'),
    ('13930000003', '示例：中泽建材', '赵磊'),
    ('13930000004', '示例：启元软件', '许静'),
    ('13930000005', '示例：德茂食品', '黄勇'),
    ('13930000006', '示例：天成物流', '吴倩'),
    ('13930000007', '示例：锐风传媒', '郑鑫'),
    ('13930000008', '示例：安泰化工', '何俊'),
)

HISTORY_OUTCOMES = (
    ('deal', 'A', '客户确认采购，走合同流程。', '本周内出合同'),
    ('interested', 'B', '客户要方案对比，下周再聊。', '下周电话回访'),
    ('call_back', 'B', '客户在开会，约明早十点回电。', '明早十点回电'),
    ('not_interested', 'D', '客户说已有固定供应商。', None),
    ('connected', 'none', '简单沟通，暂无明确意向。', None),
    ('deal', 'A', '复购意向明确，要样品。', '寄送样品'),
    ('refused', 'D', '客户明确表示不要再联系。', None),
    ('connected', 'none', '前台转接，负责人不在。', '改天再试'),
)


def backdate_answered(container, call_id: str, seconds: int) -> None:
    '''把「接通时刻」挪到当前时间之前，让演示数据有真实的通话时长。'''
    from datetime import timedelta

    from app.adapters.tables import calls as calls_table
    from app.core.clock import now, to_iso

    container.store.update(
        calls_table, call_id, {'answered_at': to_iso(now() - timedelta(seconds=seconds))}
    )


def main() -> int:
    parser = argparse.ArgumentParser(description='灌入外呼系统演示数据')
    parser.add_argument('--reset', action='store_true', help='先清空所有表再灌（慎用）')
    args = parser.parse_args()

    settings = get_settings()
    container = Container(settings)
    if args.reset:
        print('清空所有表 ...')
        container.store.drop_all()
    container.startup()

    admin = container.identity.actor_for_token(
        container.identity.login(
            settings.bootstrap_admin_email, settings.bootstrap_admin_password
        )['token']
    )
    print('管理员：' + admin.display + ' / ' + admin.user_id)

    existing = {row['name'] for row in container.batches.list_batches(admin, page_size=200)['data']}
    if IMPORT_BATCH_NAME in existing and not args.reset:
        print('演示数据已经在库里了（' + IMPORT_BATCH_NAME + '）。想重来一遍就加 --reset（会清空所有表）。')
        return 0

    # ---- 批次一：CRM 线索 ----
    pulled = container.batches.create_from_crm(
        admin, {'crm_object': 'leads', 'name': CRM_BATCH_NAME, 'limit': 50}
    )
    print('批次一（CRM）：入库 ' + str(pulled['report']['imported']) + ' 条')

    # ---- 批次二：本地上传，故意不呼，留给用户自己点 ----
    rows = ['手机号,客户名称,联系人'] + [','.join(row) for row in DEMO_ROWS]
    uploaded = container.batches.import_file(
        admin,
        filename='演示名单.csv',
        content=('\n'.join(rows) + '\n').encode('utf-8'),
        name=IMPORT_BATCH_NAME,
        note='演示用：留给工作台手动点拨号',
    )
    print('批次二（导入）：入库 ' + str(uploaded['report']['imported']) + ' 条')

    # 演示数据要的是「每通都接通、时长像真的、结果由我们指定」；
    # 这里把模拟线路调成立刻接通，接通后再把时刻回填成真实的通话时长。
    if hasattr(container.provider, 'answer_rate'):
        container.provider.answer_rate = 1.0
        container.provider.ring_seconds = 0.0

    # ---- 任务一：跑 2 通，演示通话记录与回写 ----
    first = container.tasks.create_task(
        admin,
        {
            'name': '演示任务：CRM 线索（跑 2 通）',
            'batch_id': pulled['batch']['id'],
            'status': 'active',
            'priority': 'high',
            'max_attempts': 3,
        },
    )
    done = 0
    while done < len(OUTCOMES):
        item = container.tasks.next_item(admin)
        if item is None or item['task_id'] != first['id']:
            break
        code, intent, note, followup = OUTCOMES[done]
        call = container.calls.dial(admin, task_item_id=item['id'])
        container.tick_once()
        backdate_answered(container, call['id'], 60 + done * 37)
        container.calls.hangup(admin, call['id'])
        container.calls.complete(
            admin,
            call['id'],
            {
                'result_code': code,
                'intent_level': intent,
                'note': note,
                'followup_subject': followup,
                'followup_priority': 'high' if followup else None,
            },
        )
        print('  通话 ' + call['id'] + ' → ' + code + '（' + str(item.get('company') or '') + '）')
        done += 1
    container.writeback.drain(limit=50)
    print('CRM 回写：' + str(container.writeback.list(admin)['summary']))

    # ---- 任务二：留着不呼，工作台里就有「拨号」按钮 ----
    second = container.tasks.create_task(
        admin,
        {
            'name': '演示任务：本地上传名单（留给你自己打）',
            'batch_id': uploaded['batch']['id'],
            'status': 'active',
            'priority': 'normal',
            'max_attempts': 3,
        },
    )
    print('任务二：' + second['id'] + '，待呼 ' + str(second['progress']['pending']) + ' 条（去「坐席工作台」点拨号）')

    # ---- 批次三：历史通话，把通话记录与报表填满 ----
    history_rows = ['手机号,客户名称,联系人'] + [','.join(row) for row in HISTORY_ROWS]
    history = container.batches.import_file(
        admin,
        filename='演示历史名单.csv',
        content=('\n'.join(history_rows) + '\n').encode('utf-8'),
        name=HISTORY_BATCH_NAME,
        note='演示用：已跑完的历史通话',
    )
    history_task = container.tasks.create_task(
        admin,
        {
            'name': '演示任务：历史通话（已跑完）',
            'batch_id': history['batch']['id'],
            'status': 'active',
            'priority': 'normal',
            'max_attempts': 3,
        },
    )
    done_history = 0
    while done_history < len(HISTORY_OUTCOMES):
        item = container.tasks.next_item(admin, task_id=history_task['id'])
        if item is None:
            break
        code, intent, note, followup = HISTORY_OUTCOMES[done_history]
        call = container.calls.dial(admin, task_item_id=item['id'])
        container.tick_once()
        backdate_answered(container, call['id'], 78 + done_history * 41)
        container.calls.hangup(admin, call['id'])
        container.calls.complete(
            admin,
            call['id'],
            {
                'result_code': code,
                'intent_level': intent,
                'note': note,
                'followup_subject': followup,
                'followup_priority': 'normal' if followup else None,
            },
        )
        done_history += 1
    container.writeback.drain(limit=100)
    print('历史通话：' + str(done_history) + ' 通（含回写）')

    container.compliance.create_blacklist(
        admin, {'scope': 'phone', 'phone': '13700000000', 'reason': '演示：客户明确要求不再联系'}
    )
    print('黑名单：已加入 13700000000')

    script = container.robot.create_script(
        admin, {'name': '首访话术（演示）', 'status': 'active', 'content': SCRIPT_CONTENT}
    )
    robot = container.robot.create_robot_task(
        admin,
        {
            'name': '机器人首轮（演示）',
            'script_id': script['id'],
            'batch_id': uploaded['batch']['id'],
            'concurrency': int(settings.robot_concurrency),
            'autostart': False,
        },
    )
    print('机器人任务：' + robot['id'] + '（未启动，去「AI 机器人」点启动）')

    print('概览：' + str(container.reports.overview(admin)))
    print('')
    print('完成。现在去「坐席工作台」，任务二那 4 条可以直接点「拨号」；也可以用手动拨号盘打任意号码。')
    print('后端：python -X utf8 -m uvicorn app.main:app --port 9300 ；前端：cd web && npm run dev')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())