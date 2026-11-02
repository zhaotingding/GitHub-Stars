from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from .reports import digest_text, html_document


def send_digest(paths, store, config, week, now, retry=False, factory=None):
    settings = config["email"]
    if not settings["enabled"]:
        return "未启用邮件；周报已保存在应用内"
    digest = store.one("SELECT * FROM digests WHERE week=?", (week,))
    if not digest:
        raise ValueError("请先生成周报")
    if digest["mail_state"] == "sent":
        return "此周邮件已发送，无需重复发送"
    if digest["mail_state"] in {"unknown", "sending"} and not retry:
        raise ValueError("上次发送结果未知，请先检查收件箱；需要时点击明确重发")
    password = paths.secret("smtp")
    if settings["username"] and not password:
        raise ValueError("请先保存 SMTP 密码／授权码")
    text = digest_text(store, week)
    message = EmailMessage()
    message["Subject"] = f"GitHub Stars++ | {week} · 本周值得知道的开源项目"
    message["From"] = settings["sender"]
    message["To"] = settings["recipient"]
    message["Message-ID"] = f"<github-stars-{week}@{settings['sender'].split('@')[-1]}>"
    message.set_content(text)
    message.add_alternative(html_document(text), subtype="html")
    store.execute("UPDATE digests SET mail_state='sending',mail_attempt=?,mail_detail='' WHERE week=?", (now.isoformat(), week))
    sending = False
    smtp = None
    try:
        context = ssl.create_default_context()
        if factory:
            smtp = factory()
        elif settings["security"] == "ssl":
            smtp = smtplib.SMTP_SSL(settings["host"], settings["port"], timeout=30, context=context)
        else:
            smtp = smtplib.SMTP(settings["host"], settings["port"], timeout=30)
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
        if settings["username"]:
            smtp.login(settings["username"], password)
        sending = True  # DATA 发送开始后，网络异常可能意味着服务器已收件。
        smtp.send_message(message)
        store.execute("UPDATE digests SET mail_state='sent',mail_detail='SMTP 已接受；不等于已进入收件箱' WHERE week=?", (week,))
        store.event(now, "INFO", f"周报 {week} 已提交 SMTP")
        return "SMTP 已接受邮件；请检查收件箱／垃圾邮件"
    except Exception as exc:
        state = "unknown" if sending else "failed"
        detail = f"{type(exc).__name__}：{'提交结果未知，检查收件箱后决定是否重发' if sending else '连接或认证失败，尚未发送'}"
        store.execute("UPDATE digests SET mail_state=?,mail_detail=? WHERE week=?", (state, detail, week))
        raise RuntimeError(detail) from None
    finally:
        if smtp:
            try:
                smtp.close()  # QUIT 失败不能把已确认发送改写为失败。
            except OSError:
                pass
