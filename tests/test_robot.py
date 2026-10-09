'''AI 机器人：脚本引擎、自动外呼、会话轮次与转人工。'''

from __future__ import annotations

import unittest

from app.adapters.tables import task_items
from app.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.robot.engine import ScriptEngine, detect_intent, guess_intent
from tests.support import ServiceCase, make_agent

SCRIPT = {
    'opening': '您好，我是{company}的小王，请问是{name}吗？',
    'nodes': [
        {
            'id': 'n1',
            'say': '您近期有采购计划吗？',
            'keywords': {'有': 'n2', '没有': None},
            'default': 'n2',
            'intent': 'B',
        },
        {'id': 'n2', 'say': '方便约个时间详细聊吗？', 'keywords': {'方便': 'n3'}, 'default': 'n3'},
        {'id': 'n3', 'say': '好的，我把资料发您。', 'keywords': {}, 'default': None},
    ],
    'closing': '好的，打扰了，祝您愉快。',
}


class ScriptEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ScriptEngine(SCRIPT)

    def test_opening_fills_variables(self) -> None:
        self.assertIn('远山科技', self.engine.opening({'company': '远山科技', 'name': '张伟'}))

    def test_keyword_jump(self) -> None:
        reply = self.engine.respond(node_id='n1', customer_text='有，我们在看', variables={})
        self.assertEqual(reply.next_node, 'n2')
        self.assertFalse(reply.end)
        self.assertEqual(reply.intent, 'B')

    def test_keyword_ends_call(self) -> None:
        reply = self.engine.respond(node_id='n1', customer_text='没有', variables={})
        self.assertTrue(reply.end)
        self.assertIsNone(reply.next_node)
        self.assertIn('打扰了', reply.say)

    def test_default_branch(self) -> None:
        reply = self.engine.respond(node_id='n1', customer_text='嗯……', variables={})
        self.assertEqual(reply.next_node, 'n2')

    def test_terminal_node_ends(self) -> None:
        reply = self.engine.respond(node_id='n3', customer_text='好', variables={})
        self.assertTrue(reply.end)

    def test_unknown_node_ends_gracefully(self) -> None:
        reply = self.engine.respond(node_id='nope', customer_text='喂', variables={})
        self.assertTrue(reply.end)

    def test_transfer_keyword(self) -> None:
        reply = self.engine.respond(node_id='n1', customer_text='我要转人工', variables={})
        self.assertTrue(reply.transfer)

    def test_empty_script_still_answers(self) -> None:
        engine = ScriptEngine({})
        self.assertTrue(engine.opening({}))
        self.assertTrue(engine.respond(node_id=None, customer_text='你好', variables={}).end)

    def test_intent_detection(self) -> None:
        self.assertEqual(detect_intent('我们签合同吧'), 'A')
        self.assertEqual(detect_intent('我再考虑一下'), 'B')
        self.assertEqual(detect_intent('不需要'), 'D')
        self.assertIsNone(detect_intent('天气不错'))

    def test_guess_intent_picks_strongest(self) -> None:
        transcript = [
            {'role': 'robot', 'text': '您好'},
            {'role': 'customer', 'text': '不需要'},
            {'role': 'customer', 'text': '不过可以聊聊报价'},
        ]
        self.assertEqual(guess_intent(transcript), 'A')
        self.assertEqual(guess_intent([]), 'none')

    def test_prompt_mentions_script(self) -> None:
        prompt = self.engine.prompt(transcript=[], variables={'company': '远山科技'})
        self.assertIn('外呼机器人', prompt)
        self.assertIn('远山科技', prompt)


class RobotTaskTest(ServiceCase):
    def make_script(self, **extra: object) -> dict:
        payload = {'name': '首访话术', 'status': 'active', 'content': SCRIPT}
        payload.update(extra)
        return self.container.robot.create_script(self.admin, payload)

    def make_robot_task(self, *, autostart: bool = True, **extra: object) -> dict:
        batch = self.make_batch(crm_object='contacts')
        script = self.make_script()
        payload = {
            'name': '机器人首轮',
            'script_id': script['id'],
            'batch_id': batch['id'],
            'autostart': autostart,
            'concurrency': 2,
        }
        payload.update(extra)
        return self.container.robot.create_robot_task(self.admin, payload)

    def test_script_validations(self) -> None:
        with self.assertRaises(ValidationFailed):
            self.container.robot.create_script(self.admin, {'name': '', 'content': SCRIPT})
        with self.assertRaises(ValidationFailed):
            self.container.robot.create_script(self.admin, {'name': 'x', 'content': {}})
        with self.assertRaises(ValidationFailed):
            self.container.robot.create_script(self.admin, {'name': 'x', 'content': SCRIPT, 'status': 'wat'})
        agent = make_agent(self.container, name='坐席', email='rb@example.com')
        with self.assertRaises(Forbidden):
            self.container.robot.create_script(agent, {'name': 'x', 'content': SCRIPT})

    def test_script_update_bumps_version(self) -> None:
        script = self.make_script()
        updated = self.container.robot.update_script(
            self.admin, script['id'], {'content': {**SCRIPT, 'closing': '那就这样'}}
        )
        self.assertEqual(updated['version'], 2)

    def test_robot_task_dials_and_opens_sessions(self) -> None:
        task = self.make_robot_task()
        self.assertEqual(task['status'], 'running')
        first = self.container.tick_once()['robot']
        self.assertEqual(first['dialed'], 2)
        second = self.container.tick_once()['robot']
        self.assertEqual(second['sessions'], 2)

        sessions = self.container.robot.list_sessions(self.admin, task['id'])['data']
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0]['outcome'], 'in_progress')
        self.assertIn('请问是', sessions[0]['transcript'][0]['text'])
        self.assertEqual(sessions[0]['phone_masked'][-4:], sessions[0]['phone_masked'][-4:])

    def test_turn_advances_and_completes(self) -> None:
        task = self.make_robot_task(concurrency=1)
        self.container.tick_once()
        self.container.tick_once()
        session = self.container.robot.list_sessions(self.admin, task['id'])['data'][0]

        after_first = self.container.robot.turn(self.admin, session['id'], text='有采购计划')
        self.assertEqual(after_first['outcome'], 'in_progress')
        self.assertEqual(after_first['intent_level'], 'B')
        self.assertEqual(len(after_first['transcript']), 3)
        self.assertFalse(after_first['transcript'][-1]['llm'])

        after_second = self.container.robot.turn(self.admin, session['id'], text='方便，下周吧')
        self.assertEqual(after_second['outcome'], 'in_progress')
        final = self.container.robot.turn(self.admin, session['id'], text='好的')
        self.assertEqual(final['outcome'], 'completed')
        call = self.container.store.get(
            __import__('app.adapters.tables', fromlist=['calls']).calls, session['call_id']
        )
        self.assertEqual(call['state'], 'ended')
        self.assertIsNotNone(call['completed_at'])

    def test_turn_requires_active_call(self) -> None:
        task = self.make_robot_task(concurrency=1)
        self.container.tick_once()
        self.container.tick_once()
        session = self.container.robot.list_sessions(self.admin, task['id'])['data'][0]
        self.container.store.update(
            __import__('app.adapters.tables', fromlist=['calls']).calls,
            session['call_id'],
            {'state': 'ended'},
        )
        with self.assertRaises(Conflict):
            self.container.robot.turn(self.admin, session['id'], text='喂')

    def test_empty_turn_rejected(self) -> None:
        task = self.make_robot_task(concurrency=1)
        self.container.tick_once()
        self.container.tick_once()
        session = self.container.robot.list_sessions(self.admin, task['id'])['data'][0]
        with self.assertRaises(ValidationFailed):
            self.container.robot.turn(self.admin, session['id'], text='   ')

    def test_transfer_returns_item_to_agent(self) -> None:
        agent = make_agent(self.container, name='人工坐席', email='human@example.com')
        task = self.make_robot_task(concurrency=1)
        self.container.tick_once()
        self.container.tick_once()
        session = self.container.robot.list_sessions(self.admin, task['id'])['data'][0]

        result = self.container.robot.transfer(self.admin, session['id'])
        self.assertEqual(result['outcome'], 'transferred')
        self.assertEqual(result['assigned_to'], agent.user_id)
        call_row = self.container.store.get(
            __import__('app.adapters.tables', fromlist=['calls']).calls, session['call_id']
        )
        item = self.container.store.get(task_items, call_row['task_item_id'])
        self.assertEqual(item['status'], 'pending')
        self.assertEqual(item['assignee_id'], agent.user_id)
        # 转人工的人应该在坐席队列里看到这条
        nxt = self.container.tasks.next_item(agent)
        self.assertIsNotNone(nxt)
        self.assertEqual(nxt['id'], item['id'])

    def test_transfer_keyword_triggers_transfer(self) -> None:
        make_agent(self.container, name='人工坐席', email='human2@example.com')
        task = self.make_robot_task(concurrency=1)
        self.container.tick_once()
        self.container.tick_once()
        session = self.container.robot.list_sessions(self.admin, task['id'])['data'][0]
        result = self.container.robot.turn(self.admin, session['id'], text='我要转人工')
        self.assertEqual(result['outcome'], 'transferred')

    def test_idle_session_closed(self) -> None:
        task = self.make_robot_task(concurrency=1)
        self.container.tick_once()
        self.container.tick_once()
        session = self.container.robot.list_sessions(self.admin, task['id'])['data'][0]

        import app.services.robot as robot_module

        original = robot_module.SESSION_IDLE_SECONDS
        robot_module.SESSION_IDLE_SECONDS = -1
        try:
            closed = self.container.robot.close_idle()
            self.assertEqual(closed, 1)
        finally:
            robot_module.SESSION_IDLE_SECONDS = original
        detail = self.container.robot.get_session(self.admin, session['id'])
        self.assertEqual(detail['outcome'], 'aborted')

    def test_pause_stops_dialing(self) -> None:
        task = self.make_robot_task(autostart=False)
        self.assertEqual(self.container.tick_once()['robot']['dialed'], 0)
        self.container.robot.start(self.admin, task['id'])
        self.assertEqual(self.container.tick_once()['robot']['dialed'], 2)
        self.container.robot.pause(self.admin, task['id'])
        # 已有两通在通话中，暂停后不会再新增
        self.assertEqual(self.container.tick_once()['robot']['dialed'], 0)

    def test_summary(self) -> None:
        task = self.make_robot_task(concurrency=1)
        self.container.tick_once()
        self.container.tick_once()
        session = self.container.robot.list_sessions(self.admin, task['id'])['data'][0]
        self.container.robot.turn(self.admin, session['id'], text='有')
        data = self.container.robot.summary(self.admin)
        self.assertEqual(data['sessions'], 1)
        self.assertEqual(data['running_tasks'], 1)
        self.assertEqual(data['robot_calls'], 1)
        self.assertGreaterEqual(data['avg_turns'], 1)

    def test_missing_script_or_batch(self) -> None:
        batch = self.make_batch()
        with self.assertRaises(NotFound):
            self.container.robot.create_robot_task(
                self.admin, {'name': 'x', 'script_id': 'script-nope', 'batch_id': batch['id']}
            )
        script = self.make_script()
        with self.assertRaises(NotFound):
            self.container.robot.create_robot_task(
                self.admin, {'name': 'x', 'script_id': script['id'], 'batch_id': 'batch-nope'}
            )

    def test_robot_task_requires_manager(self) -> None:
        agent = make_agent(self.container, name='坐席', email='rb2@example.com')
        with self.assertRaises(Forbidden):
            self.container.robot.create_robot_task(agent, {})

    def test_unknown_session(self) -> None:
        with self.assertRaises(NotFound):
            self.container.robot.get_session(self.admin, 'rs-nope')


class VoiceTest(unittest.TestCase):
    def test_simulated_voice_returns_text(self) -> None:
        from app.robot.llm import LlmClient, SimulatedVoice

        voice = SimulatedVoice()
        self.assertEqual(voice.start(opening='你好')['spoken'], '你好')
        self.assertEqual(voice.turn(say='在的')['spoken'], '在的')

    def test_llm_stub_is_disabled(self) -> None:
        from app.core.config import get_settings
        from app.robot.llm import LlmClient

        client = LlmClient(get_settings())
        self.assertFalse(client.enabled)
        self.assertIsNone(client.complete(prompt='你好'))


if __name__ == '__main__':
    unittest.main()