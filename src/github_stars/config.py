from __future__ import annotations

import copy
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
        if isinstance(template, list) and (not value or not all(isinstance(x, str) and x.strip() for x in value)):
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
              ("ai", "readme_chars"): (2000, 40000), ("email", "port"): (1, 65535)}
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

    def secret(self, kind):
        names = {"openai": "OPENAI_API_KEY", "github": "GITHUB_TOKEN", "smtp": "GITHUB_STARS_SMTP_PASSWORD"}
        return os.getenv(names[kind]) or keyring.get_password(f"GitHub Stars++:{self.root}", kind) or ""

    def set_secret(self, kind, value):
        keyring.set_password(f"GitHub Stars++:{self.root}", kind, value)  # Windows 系统凭据库，不写 YAML。
