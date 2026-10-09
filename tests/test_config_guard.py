'''生产环境配置守卫：宁可起不来，也不能带着默认密钥与模拟能力进生产。'''

from __future__ import annotations

import unittest

from app.core.config import Settings
from tests.support import make_settings


class ConfigGuardTest(unittest.TestCase):
    def test_dev_allows_defaults(self) -> None:
        settings = make_settings(env='dev')
        self.assertFalse(settings.is_production)
        self.assertEqual(settings.telephony_provider, 'simulated')

    def test_rejects_unknown_env(self) -> None:
        with self.assertRaises(ValueError):
            make_settings(env='prd')

    def test_rejects_unknown_provider(self) -> None:
        with self.assertRaises(ValueError):
            make_settings(telephony_provider='asterisk')

    def test_prod_rejects_default_secret(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            Settings(
                env='prod',
                secret_key='dev-only-change-me',
                bootstrap_admin_password='strong-password-here',
                sqlite_path=':memory:',
                telephony_provider='rest',
                telephony_base_url='http://gw.local',
                crm_mode='rest',
                llm_mode='live',
                voice_provider='simulated',
                allow_simulated_in_prod=True,
                compliance_mask_phone=True,
            )
        self.assertIn('WAHU_SECRET_KEY', str(ctx.exception))

    def test_prod_rejects_simulated_stack(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            Settings(
                env='prod',
                secret_key='a' * 32,
                bootstrap_admin_password='strong-password-here',
                sqlite_path=':memory:',
                telephony_provider='simulated',
                crm_mode='fake',
                llm_mode='stub',
                voice_provider='simulated',
                compliance_mask_phone=True,
            )
        message = str(ctx.exception)
        self.assertIn('WAHU_TELEPHONY_PROVIDER', message)
        self.assertIn('WAHU_LLM_MODE', message)
        self.assertIn('WAHU_CRM_MODE', message)

    def test_prod_rejects_masking_off_and_wildcard_cors(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            Settings(
                env='prod',
                secret_key='a' * 32,
                bootstrap_admin_password='strong-password-here',
                sqlite_path=':memory:',
                compliance_mask_phone=False,
                cors_origins='*',
                allow_simulated_in_prod=True,
            )
        message = str(ctx.exception)
        self.assertIn('WAHU_COMPLIANCE_MASK_PHONE', message)
        self.assertIn('WAHU_CORS_ORIGINS', message)

    def test_prod_escape_hatch_opens_simulated(self) -> None:
        settings = Settings(
            env='prod',
            secret_key='a' * 32,
            bootstrap_admin_password='strong-password-here',
            sqlite_path=':memory:',
            telephony_provider='simulated',
            crm_mode='fake',
            llm_mode='stub',
            voice_provider='simulated',
            compliance_mask_phone=True,
            cors_origins='https://wahu.example.com',
            allow_simulated_in_prod=True,
        )
        self.assertTrue(settings.is_production)

    def test_clock_window_parsing(self) -> None:
        settings = make_settings(compliance_dnd_start='21:00', compliance_dnd_end='09:00')
        self.assertEqual(settings.dnd_window, (1260, 540))
        with self.assertRaises(ValueError):
            make_settings(compliance_dnd_start='25:00')

    def test_sqlalchemy_url_for_memory(self) -> None:
        self.assertEqual(make_settings().sqlalchemy_url, 'sqlite+pysqlite:///:memory:')


if __name__ == '__main__':
    unittest.main()