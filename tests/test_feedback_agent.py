import json
import unittest

from backend.feedback_agent import normalize_agent_result, redact_external_text, safe_page_context


class FeedbackAgentTest(unittest.TestCase):
    def test_redact_external_text_hides_common_identifiers_but_keeps_measurements(self):
        source = '登记号 0002343629，手机 13812345678，LVEF 62%，ED 6，ES 16。'

        result = redact_external_text(source)

        self.assertNotIn('0002343629', result)
        self.assertNotIn('13812345678', result)
        self.assertIn('LVEF 62%', result)
        self.assertIn('ED 6', result)

    def test_safe_page_context_only_keeps_non_patient_workstation_fields(self):
        result = safe_page_context({
            'module': 'cvi',
            'module_label': 'CMR 工作站',
            'dataset': 'CMR_ALL',
            'case_catalog_id': 42,
            'patient_name': '不应保留',
            'dicom_path': '/sensitive/path',
        })

        self.assertEqual(result, {
            'module': 'cvi',
            'module_label': 'CMR 工作站',
            'dataset': 'CMR_ALL',
            'case_catalog_id': 42,
        })

    def test_normalize_agent_result_builds_stable_ticket_contract(self):
        payload = {
            'reply': '已整理。',
            'intent': 'bug',
            'ready_for_ticket': True,
            'ticket': {
                'category': 'bug',
                'title': '传播跨到了下一层',
                'summary': '4CH 时域传播错误地影响其他 slice。',
                'page': 'Function 4CH',
                'operation': '在已标注层点击传播。',
                'expected_behavior': '只传播当前 slice 的 phase。',
                'actual_behavior': '其他 slice 同时出现轮廓。',
                'impact': '需要医生手工清理。',
                'severity': 'high',
                'acceptance_criteria': '其他 slice 不新增轮廓。',
                'change_scope': 'large_change',
            },
        }

        result = normalize_agent_result(json.dumps(payload, ensure_ascii=False))

        self.assertTrue(result['ready_for_ticket'])
        self.assertEqual(result['ticket']['severity'], 'high')
        self.assertEqual(result['ticket']['change_scope'], 'large_change')

    def test_normalize_agent_result_does_not_create_ticket_without_details(self):
        result = normalize_agent_result(json.dumps({
            'reply': '请问发生在哪个页面？',
            'intent': 'bug',
            'ready_for_ticket': False,
            'ticket': {'title': '信息不足'},
        }, ensure_ascii=False))

        self.assertFalse(result['ready_for_ticket'])
        self.assertIsNone(result['ticket'])


if __name__ == '__main__':
    unittest.main()
