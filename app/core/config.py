'''运行配置：唯一来源是环境变量与 .env（前缀 WAHU_）。

生产环境（WAHU_ENV 落到 stage / prod 之类）在启动阶段会先校验一遍，任何一项没做到就直接
让进程起不来——这套系统真的会对外拨号并回写业务系统，宁可起不来也不能带着默认密钥裸奔。
'''

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENVS: tuple[str, ...] = ('dev', 'local', 'test', 'stage', 'staging', 'prod', 'production')
PROD_ENVS: tuple[str, ...] = ('stage', 'staging', 'prod', 'production')
STORAGES: tuple[str, ...] = ('sqlite', 'postgres')
TELEPHONY_PROVIDERS: tuple[str, ...] = ('simulated', 'rest')
CRM_MODES: tuple[str, ...] = ('fake', 'rest')
LLM_MODES: tuple[str, ...] = ('stub', 'live')
VOICE_PROVIDERS: tuple[str, ...] = ('simulated',)

DEFAULT_SECRET_KEY = 'dev-only-change-me'
DEFAULT_ADMIN_PASSWORD = 'admin12345'
DEFAULT_ADMIN_EMAIL = 'admin@example.com'


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix='WAHU_',
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore',
        case_sensitive=False,
    )

    # ---- 应用 ----
    env: str = 'dev'
    log_level: str = 'INFO'
    tenant_id: str = 'default'

    # ---- 存储 ----
    storage: str = 'sqlite'
    sqlite_path: str = 'data/wahu.sqlite3'
    database_url: str = 'postgresql+psycopg://wahu:wahu@localhost:5434/wahu'
    auto_migrate: bool = True

    # ---- 安全 ----
    secret_key: str = DEFAULT_SECRET_KEY
    token_ttl_hours: int = 12
    bootstrap_admin_email: str = DEFAULT_ADMIN_EMAIL
    bootstrap_admin_password: str = DEFAULT_ADMIN_PASSWORD
    bootstrap_admin_name: str = '系统管理员'

    # ---- 线路 ----
    telephony_provider: str = 'simulated'
    telephony_answer_rate: float = 0.6
    telephony_ring_seconds: float = 4.0
    telephony_no_answer_seconds: float = 20.0
    telephony_tick_ms: int = 300
    # 后台节拍器：推进通话状态机、冲刷 CRM 回写队列；测试里关掉手动 tick
    ticker_enabled: bool = True
    # ---- 真实线路（WAHU_TELEPHONY_PROVIDER=rest）----
    # 线路网关地址与令牌；令牌同时用于出站鉴权与回调校验
    telephony_base_url: str = ''
    telephony_token: str = ''
    # 双呼模式：先呼坐席这个号码，坐席接起后再呼客户（真实外呼线路基本都是这个模式）
    telephony_agent_phone: str = ''
    # 拨号后多久没收到任何线路回调就判失败（秒）
    telephony_timeout_seconds: int = 20
    # 线路厂商的状态码/状态名 → 本系统状态；例如 {"2":"answered","3":"hangup"}
    telephony_state_map: dict[str, str] = {}
    # ---- 录音 ----
    recording_enabled: bool = True
    recording_dir: str = 'var/recordings'

    # ---- 合规 ----
    compliance_dnd_start: str = '21:00'
    compliance_dnd_end: str = '09:00'
    compliance_daily_limit: int = 200
    compliance_per_number_daily_limit: int = 3
    compliance_mask_phone: bool = True

    # ---- 自研 CRM ----
    crm_mode: str = 'fake'
    crm_base_url: str = 'http://127.0.0.1:9100/api/v1'
    crm_api_token: str = 'dev-service-token'
    crm_actor_id: str = 'wahu-system'
    crm_page_size: int = 100
    crm_rate_limit_per_sec: int = 5
    crm_max_retries: int = 4
    crm_timeout_seconds: int = 15

    # ---- 大模型与语音（二期）----
    llm_mode: str = 'stub'
    llm_base_url: str = 'https://api.deepseek.com/v1'
    llm_api_key: str = 'replace-me'
    llm_model: str = 'deepseek-chat'
    llm_timeout_seconds: int = 60
    voice_provider: str = 'simulated'
    robot_concurrency: int = 3

    # ---- 前端 ----
    serve_web: bool = True
    web_dist_dir: str = 'web/dist'
    cors_origins: str = 'http://localhost:5176,http://127.0.0.1:5176'

    # ---- 分页 ----
    default_page_size: int = 50
    max_page_size: int = 200

    # ---- 生产逃生开关 ----
    # 只有显式打开才允许在生产使用模拟线路 / 模拟语音 / stub 大模型
    allow_simulated_in_prod: bool = False

    @model_validator(mode='after')
    def _check(self) -> Settings:
        _pick('env', self.env, ENVS)
        _pick('storage', self.storage, STORAGES)
        _pick('telephony_provider', self.telephony_provider, TELEPHONY_PROVIDERS)
        _pick('crm_mode', self.crm_mode, CRM_MODES)
        _pick('llm_mode', self.llm_mode, LLM_MODES)
        _pick('voice_provider', self.voice_provider, VOICE_PROVIDERS)
        if self.storage == 'sqlite' and not self.sqlite_path.strip():
            raise ValueError('WAHU_SQLITE_PATH 不能为空')
        if self.storage == 'postgres' and not self.database_url.strip():
            raise ValueError('WAHU_DATABASE_URL 不能为空')
        if not 0.0 <= self.telephony_answer_rate <= 1.0:
            raise ValueError('WAHU_TELEPHONY_ANSWER_RATE 必须落在 0~1')
        if self.telephony_tick_ms < 20:
            raise ValueError('WAHU_TELEPHONY_TICK_MS 不能小于 20')
        if self.telephony_timeout_seconds < 1:
            raise ValueError('WAHU_TELEPHONY_TIMEOUT_SECONDS 不能小于 1')
        if self.telephony_provider == 'rest' and not self.telephony_base_url.strip():
            raise ValueError('WAHU_TELEPHONY_PROVIDER=rest 时必须配置 WAHU_TELEPHONY_BASE_URL')
        parse_clock(self.compliance_dnd_start)
        parse_clock(self.compliance_dnd_end)
        self._guard_production()
        return self

    def _guard_production(self) -> None:
        if not self.is_production:
            return
        problems: list[str] = []
        if self.secret_key == DEFAULT_SECRET_KEY or len(self.secret_key) < 16:
            problems.append('WAHU_SECRET_KEY 必须换成至少 16 位随机串')
        if self.bootstrap_admin_password == DEFAULT_ADMIN_PASSWORD:
            problems.append('WAHU_BOOTSTRAP_ADMIN_PASSWORD 必须改掉默认口令')
        if '*' in self.cors_origin_list:
            problems.append('WAHU_CORS_ORIGINS 不能出现通配 *')
        if not self.compliance_mask_phone:
            problems.append('WAHU_COMPLIANCE_MASK_PHONE 必须为 true（号码必须脱敏）')
        if not self.allow_simulated_in_prod:
            if self.telephony_provider == 'simulated':
                problems.append('WAHU_TELEPHONY_PROVIDER 必须是真实线路，或设 WAHU_ALLOW_SIMULATED_IN_PROD=true')
            if self.voice_provider == 'simulated':
                problems.append('WAHU_VOICE_PROVIDER 必须是真实语音，或设 WAHU_ALLOW_SIMULATED_IN_PROD=true')
            if self.llm_mode == 'stub':
                problems.append('WAHU_LLM_MODE 必须是 live，或设 WAHU_ALLOW_SIMULATED_IN_PROD=true')
            if self.crm_mode == 'fake':
                problems.append('WAHU_CRM_MODE 必须是 rest，或设 WAHU_ALLOW_SIMULATED_IN_PROD=true')
        if problems:
            raise ValueError('生产环境配置未通过校验：\n- ' + '\n- '.join(problems))

    @property
    def is_production(self) -> bool:
        return self.env in PROD_ENVS

    @property
    def cors_origin_list(self) -> list[str]:
        return [part.strip() for part in self.cors_origins.split(',') if part.strip()]

    @property
    def sqlalchemy_url(self) -> str:
        '''sqlite 用标准库驱动；`:memory:` 表示进程内内存库（测试用）。'''
        if self.storage == 'postgres':
            return self.database_url
        path = self.sqlite_path.strip()
        if path in (':memory:', 'memory'):
            return 'sqlite+pysqlite:///:memory:'
        return 'sqlite+pysqlite:///' + Path(path).as_posix()

    @property
    def dnd_window(self) -> tuple[int, int]:
        '''免打扰时段（当日分钟数）；start > end 表示跨零点。'''
        return parse_clock(self.compliance_dnd_start), parse_clock(self.compliance_dnd_end)

    @property
    def recording_path(self) -> Path:
        return Path(self.recording_dir)

    @property
    def web_dist_path(self) -> Path:
        return Path(self.web_dist_dir)


def parse_clock(value: str) -> int:
    '''把 HH:MM 解析成当日分钟数。'''
    text = str(value or '').strip()
    parts = text.split(':')
    if len(parts) != 2 or not all(part.strip().isdigit() for part in parts):
        raise ValueError('时间格式必须是 HH:MM，收到：' + repr(value))
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError('时间超出范围：' + repr(value))
    return hour * 60 + minute


def _pick(name: str, value: str, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise ValueError('WAHU_' + name.upper() + ' 只能是 ' + ' / '.join(allowed) + '，收到：' + repr(value))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()