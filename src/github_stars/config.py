from __future__ import annotations

import copy
import math
import os
import re
import uuid
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from zoneinfo import ZoneInfo

import keyring
import yaml


def merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)  # 不原地改变共享默认设置。
    for key, value in override.items():
        if key not in result:
            raise ValueError(f"未知设置：{key}")
        result[key] = merge(result[key], value) if isinstance(result[key], dict) and isinstance(value, dict) else value
    return result


def validate(config: dict) -> None:
    defaults = yaml.safe_load(files("github_stars").joinpath("defaults.yaml").read_text(encoding="utf-8"))

    def types(value, template, path=""):
        if type(value) is not type(template):
            raise ValueError(f"设置类型错误：{path}")
        if isinstance(template, dict):
            for key in template:
                types(value[key], template[key], f"{path}.{key}")
        empty_allowed = path in {'.research.interests', '.research.exclude_terms'}
        if isinstance(template, list) and ((not value and not empty_allowed)
                                          or not all(isinstance(x, str) and x.strip() for x in value)):
            raise ValueError(f"列表需要非空文字：{path}")

    types(config, defaults)  # YAML true/false 与整数必须区分。
    ZoneInfo(config["schedule"]["timezone"])
    bounds = {("schedule", "daily_hour"): (0, 23), ("schedule", "weekly_hour"): (0, 23),
              ("schedule", "weekly_day"): (0, 6), ("digest", "max_projects"): (1, 7),
              ("digest", "hot_slots"): (0, 7), ("digest", "min_score"): (0, 100),
              ("digest", "cooldown_days"): (7, 730), ("discovery", "min_stars"): (0, 1000000),
              ("discovery", "new_min_stars"): (0, 1000000), ("discovery", "active_days"): (1, 730),
              ("discovery", "per_query"): (1, 50), ("discovery", "readme_limit"): (1, 30),
              ("ai", "max_calls_per_week"): (1, 20), ("ai", "max_output_tokens"): (1000, 16000),
              ("ai", "readme_chars"): (2000, 100000), ("ai", "timeout_seconds"): (30, 1800),
              ("tutorial", "max_calls_per_week"): (1, 20), ("tutorial", "max_output_tokens"): (4000, 128000),
              ("tutorial", "readme_chars"): (2000, 100000), ("tutorial", "timeout_seconds"): (60, 1800),
              ("research", "max_calls"): (1, 6), ("research", "max_tools"): (0, 8),
              ("research", "max_images"): (0, 2), ("research", "max_calls_per_week"): (1, 100),
              ("research", "max_output_tokens"): (1000, 8000), ("research", "max_input_chars"): (4000, 50000),
              ("research", "timeout_seconds"): (15, 900), ("research", "history_days"): (1, 90),
              ("email", "port"): (1, 65535)}
    for (section, key), (low, high) in bounds.items():
        if not low <= config[section][key] <= high:
            raise ValueError(f"{section}.{key} 需要在 {low}–{high} 之间")
    if config["digest"]["hot_slots"] > config["digest"]["max_projects"]:
        raise ValueError("热点名额不能超过每周项目上限")
    queries = config["discovery"]["research_queries"] + config["discovery"]["hot_queries"]
    if len(queries) > 8 or any(len(q) > 150 for q in queries):
        raise ValueError("最多 8 条检索语句，每条最多 150 字符")
    if config["email"]["security"] not in {"ssl", "starttls"}:
        raise ValueError("邮件连接必须使用 ssl 或 starttls")
    if config["email"]["enabled"]:
        for key in ("host", "sender", "recipient"):
            value = config["email"][key]
            if not value or "\n" in value or "\r" in value:
                raise ValueError(f"请填写有效的邮件 {key}")
        for key in ("sender", "recipient"):
            if not re.fullmatch(r"[^\s<>@,;]+@[^\s<>@,;]+\.[^\s<>@,;]+", config["email"][key]):
                raise ValueError(f"{key} 需要填写一个邮件地址")
    if config["ai"]["enabled"] and not config["ai"]["model"].strip():
        raise ValueError("启用 AI 前请填写账户可用的 OpenAI 模型 ID")
    if config["appearance"]["theme"] not in {"dark", "light"}:
        raise ValueError("主题必须为 dark 或 light")
    if config["ai"]["credential_source"] not in {"local", "msgx", "autogpu"}:
        raise ValueError("请选择有效的凭据来源")
    for section in ("ai", "tutorial"):
        if config[section]["service_tier"] not in {"default", "flex"}:
            raise ValueError("服务等级必须为 default 或 flex；不会自动切换到更贵等级")
        if not config[section]["prompt"].strip() or len(config[section]["prompt"]) > 20000:
            raise ValueError(f"{section} 提示词需要 1–20000 字符")
    settings = config['research']
    if settings['service_tier'] not in {'default', 'flex'} or settings['image_credential_source'] not in {'local', 'msgx', 'autogpu'}:
        raise ValueError('研究服务等级或图片凭据来源无效')
    for field in ('max_cost_cny', 'input_cny_per_million', 'output_cny_per_million',
                  'image_input_cny_per_million', 'image_output_cny_per_million'):
        if not math.isfinite(settings[field]) or not 0 <= settings[field] <= 100000:
            raise ValueError('研究费率和预算需要有限非负数')
    if not .01 <= settings['max_cost_cny'] <= 100:
        raise ValueError('研究预算需要0.01～100元（本地估算）')
    for field in ('interests', 'exclude_terms'):
        if len(settings[field]) > 12 or any(not 2 <= len(x) <= 50 for x in settings[field]):
            raise ValueError('研究关注点/少关注词各最多12项，每项2～50字')


@dataclass
class Paths:
    root: Path

    def __post_init__(self):
        self.root = self.root.resolve()  # CLI、GUI、计划任务共用明确的资料位置。
        self.data.mkdir(parents=True, exist_ok=True)

    @property
    def data(self):
        return self.root / "data"

    @property
    def settings(self):
        return self.root / "config.local.yaml"

    def load(self):
        base = yaml.safe_load(files("github_stars").joinpath("defaults.yaml").read_text(encoding="utf-8"))
        if self.settings.exists():
            override = yaml.safe_load(self.settings.read_text(encoding="utf-8"))
            if not isinstance(override, dict):
                raise ValueError("config.local.yaml 必须是 YAML 映射；请修复文件，程序不会静默覆盖")
            base = merge(base, override)
        validate(base)
        return base

    def save(self, config):
        validate(config)
        temporary = self.settings.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        temporary.replace(self.settings)  # 完整写入后原子替换，避免半份配置。

    def ensure_theme(self):
        config = self.load()
        override = yaml.safe_load(self.settings.read_text(encoding="utf-8")) if self.settings.exists() else {}
        if "theme" not in override.get("appearance", {}):
            override["appearance"] = {**override.get("appearance", {}), "theme": config["appearance"]["theme"]}
            temporary = self.settings.with_suffix(".theme.tmp")
            temporary.write_text(yaml.safe_dump(override, allow_unicode=True, sort_keys=False), encoding="utf-8")
            temporary.replace(self.settings)  # 只补主题，不改写旧 API 配置或个人偏好。
        return config

    def secret(self, kind, source=None):
        names = {"openai": "OPENAI_API_KEY", "github": "GITHUB_TOKEN", "smtp": "GITHUB_STARS_SMTP_PASSWORD"}
        source = source or (self.load()["ai"]["credential_source"] if kind == "openai" else "local")
        if kind == "openai" and source != "local":
            return existing_openai_secret(source)
        return os.getenv(names[kind]) or keyring.get_password(f"GitHub Stars++:{self.root}", kind) or ""

    def set_secret(self, kind, value):
        keyring.set_password(f"GitHub Stars++:{self.root}", kind, value)  # Windows 系统凭据库，不写 YAML。


def existing_openai_secret(source):
    import ctypes
    from ctypes import wintypes
    if os.name != "nt":
        raise ValueError("复用 Windows 凭据仅支持当前 Windows 登录用户")
    targets = {"msgx": ("msgx/api/d9617135d6fdd0a2cde722d637a1dfcc3da37515708b3ea5d66ae607c8ac785e", "msgx"),
               "autogpu": ("autodl-watcher/llm/https://api.openai.com/v1", "autodl-watcher")}
    target, username = targets[source]

    class Credential(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    api = ctypes.WinDLL("Advapi32", use_last_error=True)
    pointer = ctypes.POINTER(Credential)()
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
    api.CredReadW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    if not api.CredReadW(target, 1, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == 1168:
            return ""
        raise ValueError("无法读取所选系统凭据，请核对当前 Windows 用户")
    try:
        item = pointer.contents
        if item.UserName != username:
            raise ValueError("凭据用户名与所选应用不匹配，请选择正确来源")
        return ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize).decode("utf-8")
    finally:
        ctypes.memset(pointer.contents.CredentialBlob, 0, pointer.contents.CredentialBlobSize)
        api.CredFree(pointer)  # 仅请求进程持有明文，不复制或迁移旧凭据。
