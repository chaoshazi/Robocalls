'''阿里云 RPC 签名：编码规则、待签串、确定性与回归锁定。

说明：这里断言的是「本实现的算法不跑偏」（编码规则 + 固定入参下的签名值），
接真实账号时用 scripts/aliyun_voice_gateway.py --live 打通一次即可确认端到端一致。
'''

from __future__ import annotations

import unittest

from app.integrations.aliyun.signature import (
    SIGNATURE_METHOD,
    SIGNATURE_VERSION,
    build_request,
    canonical_query,
    common_params,
    percent_encode,
    redact,
    sign,
    string_to_sign,
    timestamp_now,
)

SECRET = 'testsecret'


class EncodingTest(unittest.TestCase):
    def test_rfc3986_rules(self) -> None:
        self.assertEqual(percent_encode('a b'), 'a%20b')  # 空格是 %20，不是 +
        self.assertEqual(percent_encode('a+b'), 'a%2Bb')
        self.assertEqual(percent_encode('*'), '%2A')  # 星号必须编码
        self.assertEqual(percent_encode('~'), '~')  # 波浪号不编码
        self.assertEqual(percent_encode('/'), '%2F')
        self.assertEqual(percent_encode('a=1&b'), 'a%3D1%26b')
        self.assertEqual(percent_encode('AZaz09-_.'), 'AZaz09-_.')
        self.assertEqual(percent_encode('中文'), '%E4%B8%AD%E6%96%87')

    def test_canonical_query_sorts_by_encoded_key(self) -> None:
        query = canonical_query({'b': '2', 'a': '1', 'c d': 'x y'})
        self.assertEqual(query, 'a=1&b=2&c%20d=x%20y')

    def test_string_to_sign_shape(self) -> None:
        params = {'Action': 'X', 'Version': '1'}
        raw = string_to_sign('POST', '/', params)
        parts = raw.split('&')
        self.assertEqual(parts[0], 'POST')
        self.assertEqual(parts[1], '%2F')
        # 第三段是「规范化查询串」再整体编码一次
        self.assertEqual(parts[2], percent_encode(canonical_query(params)))
        self.assertEqual(len(parts), 3)

    def test_sign_is_deterministic(self) -> None:
        params = common_params(
            action='SingleCallByTone',
            version='2017-05-25',
            access_key_id='testid',
            business={'CalledNumber': '13800000001'},
            nonce='abc123',
            timestamp='2026-10-09T10:00:00Z',
        )
        first = sign(params, SECRET)
        second = sign(dict(params), SECRET)
        self.assertEqual(first, second)
        self.assertNotEqual(first, sign(params, 'other-secret'))
        self.assertTrue(first.endswith('='))


class RegressionTest(unittest.TestCase):
    '''固定入参下的签名值：算法或编码规则一改就会红。'''

    def test_known_signature(self) -> None:
        url, params = build_request(
            action='SingleCallByTone',
            version='2017-05-25',
            access_key_id='testid',
            access_key_secret=SECRET,
            business={
                'CalledShowNumber': '05710000',
                'CalledNumber': '13800000001',
                'TtsCode': 'TTS_1',
            },
            endpoint='https://dyvmsapi.aliyuncs.com',
            nonce='abc123',
            timestamp='2026-10-09T10:00:00Z',
        )
        self.assertEqual(url, 'https://dyvmsapi.aliyuncs.com/')
        self.assertEqual(params['Signature'], 'avjq/4/+vVxsTfoqvy3dCWjh5Tw=')


class ParamsTest(unittest.TestCase):
    def test_common_params(self) -> None:
        params = common_params(
            action='SmartCall',
            version='2017-05-25',
            access_key_id='id-1',
            region_id='cn-hangzhou',
            business={'CalledNumber': '13800000001', 'Empty': ''},
            nonce='n1',
            timestamp='2026-10-09T10:00:00Z',
        )
        self.assertEqual(params['Format'], 'JSON')
        self.assertEqual(params['SignatureMethod'], SIGNATURE_METHOD)
        self.assertEqual(params['SignatureVersion'], SIGNATURE_VERSION)
        self.assertEqual(params['Action'], 'SmartCall')
        self.assertEqual(params['RegionId'], 'cn-hangzhou')
        self.assertEqual(params['CalledNumber'], '13800000001')
        self.assertNotIn('Empty', params)  # 空值不入参
        self.assertNotIn('Signature', params)  # Signature 由 build_request 加

    def test_build_request_adds_signature_and_keeps_business(self) -> None:
        url, params = build_request(
            action='A',
            version='V',
            access_key_id='id',
            access_key_secret=SECRET,
            business={'CalledNumber': '138'},
            endpoint='https://example.com/',
            nonce='n',
            timestamp='2026-10-09T10:00:00Z',
        )
        self.assertEqual(url, 'https://example.com/')
        self.assertIn('Signature', params)
        self.assertEqual(params['CalledNumber'], '138')
        self.assertTrue(params['SignatureNonce'])

    def test_redact_hides_secrets(self) -> None:
        masked = redact({'AccessKeyId': 'id', 'Signature': 'sig', 'Action': 'A'})
        self.assertEqual(masked['AccessKeyId'], '***')
        self.assertEqual(masked['Signature'], '***')
        self.assertEqual(masked['Action'], 'A')

    def test_timestamp_format(self) -> None:
        stamp = timestamp_now()
        self.assertRegex(stamp, r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')


if __name__ == '__main__':
    unittest.main()