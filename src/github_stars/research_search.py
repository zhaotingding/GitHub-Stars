"""有界本地证据快照、相关表达检索、跨日观测与显式 PNG 附件准备。"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import struct
import zlib
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

FAMILIES = (
    ('机器人感知', ('机器人', '机械臂', 'robot', 'robotics', '具身', 'embodied')),
    ('多模态', ('多模态', 'multimodal', 'vlm', '视觉语言')),
    ('视觉检测', ('计算机视觉', 'computer vision', '视觉', 'vision', 'detection', '检测', 'yolo')),
    ('深度伪造', ('深度伪造', 'deepfake', 'forgery', 'face manipulation')),
    ('部署与显存', ('显存', 'oom', 'vram', 'out of memory', '部署', 'inference', '推理')),
    ('自监督', ('自监督', 'self-supervised', 'representation learning')),
    ('强化学习', ('强化学习', 'reinforcement learning', 'rl')),
    ('智能体', ('agent', '智能体', 'mcp', 'tool calling')),
)
STOP = re.compile('最近|项目|仓库|哪些|什么|如何|怎么|有没有|帮我|请问|比较|推荐|适合|研究|的|了|和|与|是|在')


def contains_term(text, term):
    # 英文缩写不能命中其它单词（例如 rl 不能命中 world）。
    if not term:
        return False
    term = term.lower()
    left = r'(?<![a-z0-9])' if re.match('[a-z0-9]', term[0]) else ''
    right = r'(?![a-z0-9])' if re.match('[a-z0-9]', term[-1]) else ''
    return bool(re.search(left + re.escape(term) + right, text.lower()))


def terms_for(question):
    words = re.findall(r'[a-z][a-z0-9_+.-]{1,35}|[\u4e00-\u9fff]{2,30}', STOP.sub(' ', question.lower()))
    related = [word for _, family in FAMILIES if any(contains_term(question, word) for word in family) for word in family]
    return list(dict.fromkeys(words + related))[:24]


def grams(value):
    result = set(re.findall(r'[a-z][a-z0-9_+.-]{1,35}', value.lower()))
    for word in re.findall(r'[\u4e00-\u9fff]+', STOP.sub(' ', value.lower())):
        result.update(word[i:i+2] for i in range(len(word)-1))
    return result


def safe_url(value):
    if not isinstance(value, str) or len(value) > 2048 or re.search(r'[\s\\\x00-\x1f\x7f]', value):
        return ''
    try:
        parsed = urlsplit(value)
        parts = parsed.path.strip('/').split('/')
        valid_path = (len(parts) >= 2 and re.fullmatch(r'[A-Za-z0-9-]+', parts[0])
                      and re.fullmatch(r'[A-Za-z0-9_.-]+', parts[1]) and parts[1] not in {'.', '..'}
                      and parts[0].lower() not in {'settings', 'topics', 'collections', 'orgs', 'users', 'search', 'marketplace', 'login'})
        return value if (parsed.scheme == 'https' and parsed.netloc.lower() == 'github.com' and valid_path) else ''
    except ValueError:
        return ''


def snapshot(store, now, repo_ids=None, days=30):
    if repo_ids is not None and (not isinstance(repo_ids, list) or not 1 <= len(repo_ids) <= 30
                               or any(type(x) is not int or x <= 0 for x in repo_ids) or len(set(repo_ids)) != len(repo_ids)):
        raise ValueError('范围需要1～30个已保存项目编号')
    if type(days) is not int or not 1 <= days <= 365:
        raise ValueError('历史范围需要1～365天')
    where, args = (" AND id IN (" + ','.join('?' for _ in repo_ids) + ')', tuple(repo_ids)) if repo_ids else ('', ())
    # 在 SQL 层只取需要的有界字段，不把庞大的 metadata/README 先装入 Python。
    metadata = "CASE WHEN json_valid(metadata) THEN metadata ELSE '{}' END"
    fields = ','.join(f"substr(json_extract({metadata},'$.{key}'),1,{size}) {key}"
                      for key, size in [('description', 1800), ('topics', 900), ('language', 100), ('license', 300), ('stargazers_count', 30)])
    rows = store.rows("SELECT id,substr(name,1,200) name," + fields + ",length(metadata)>8000 metadata_truncated,"
                      "seen_at,substr(readme_sha,1,200) readme_sha,substr(readme_url,1,2049) readme_url,readme_at,study_state,"
                      "substr(readme,1,16000) readme,length(readme) original_length FROM repos"
                      " WHERE feedback<>'dismissed'" + where + " ORDER BY (study_state='focus') DESC,score DESC,id LIMIT 101", args)
    truncated = len(rows) > 100
    rows = rows[:100]
    if repo_ids and set(repo_ids) != {row['id'] for row in rows}:
        raise ValueError('所选项目不存在、已忽略或超出本次范围')
    records, remaining = [], 240000
    names = {row['id']: row['name'] for row in rows}
    for row in rows:
        if not remaining:
            truncated = True
            break
        summary = json.dumps({key: row[key] for key in ('description', 'topics', 'language', 'license', 'stargazers_count')}, ensure_ascii=False)[:3500]
        body = (summary + '\n' + row['readme'])[:remaining]
        record_truncated = bool(row['metadata_truncated'] or len(body) < len(summary + '\n' + row['readme']) or row['original_length'] > 16000)
        truncated |= record_truncated
        remaining -= len(body)
        records.append(dict(label=f"R{row['id']}", repo_id=row['id'], name=row['name'], kind='repository',
                            url=safe_url(row['readme_url']) or safe_url('https://github.com/' + row['name']),
                            sha=row['readme_sha'], captured=row['readme_at'] or row['seen_at'], body=body,
                            truncated=record_truncated))
    history, observations = [], []
    if names:
        slots = ','.join('?' for _ in names)
        cutoff = (now - timedelta(days=days)).isoformat()
        history = store.rows(f'SELECT id,repo_id,substr(sha,1,200) sha,substr(text,1,16000) body,length(text) original_length,'
                             f'substr(url,1,2049) url,captured FROM research_documents h '
                             f'WHERE repo_id IN ({slots}) AND julianday(captured)>=julianday(?) AND julianday(captured)<=julianday(?) '
                             'AND NOT EXISTS(SELECT 1 FROM repos r WHERE r.id=h.repo_id AND (r.readme_sha=h.sha OR r.readme=h.text)) '
                             'ORDER BY julianday(captured) DESC,id DESC LIMIT 101', (*names, cutoff, now.isoformat()))
        truncated |= len(history) > 100
        current = {(row['id'], row['readme_sha']) for row in rows}
        for row in history[:100]:
            if not remaining:
                truncated = True
                break
            if (row['repo_id'], row['sha']) in current:
                continue
            text = row['body'][:remaining]
            remaining -= len(text)
            record_truncated = len(text) < len(row['body']) or row['original_length'] > 16000
            truncated |= record_truncated
            records.append(dict(label=f"H{row['id']}", repo_id=row['repo_id'], name=names[row['repo_id']],
                                kind='readme_version', sha=row['sha'], captured=row['captured'],
                                url=safe_url(row['url']), body=text, truncated=record_truncated))
        observations = store.rows(f'SELECT repo_id,day,stars FROM snapshots WHERE repo_id IN ({slots}) '
                                   'AND day>=? AND day<=? ORDER BY day DESC,repo_id LIMIT 601',
                                   (*names, (now-timedelta(days=days)).date().isoformat(), now.date().isoformat()))
        truncated |= len(observations) > 600
    return dict(records=records, observations=sorted(observations[:600], key=lambda row: (row['day'], row['repo_id'])), truncated=bool(truncated),
                captured=now.isoformat(), days=days, images=[])


def retrieve(scope, question, terms=None, preferences=None, weights=None, limit=12):
    terms = terms if terms is not None else terms_for(question)
    prefs, weights = preferences or {}, weights or {}
    query = grams(question + ' ' + ' '.join(terms))
    scored = []
    for record in scope['records']:
        body = record['name'].lower() + ' ' + record['body'].lower()
        hits = [term for term in terms if contains_term(body, term)]
        overlap = query & grams(body)
        similarity = len(overlap) / max(1, len(query))
        if not hits and (len(overlap) < 2 or similarity < .2):
            continue
        score = 2 * len(hits) + similarity
        score += min(.4, .1 * sum(contains_term(body, word) for word in prefs.get('interests', [])))
        score -= min(.4, .1 * sum(contains_term(body, word) for word in prefs.get('exclude_terms', [])))
        score += max(-.2, min(.2, sum(weights.get(term, 0) for term in hits) * .02))
        anchor = next((record['body'].lower().find(term.lower()) for term in hits if term.lower() in record['body'].lower()), 0)
        excerpt = record['body'][max(0, anchor-100):max(0, anchor-100)+2400]
        scored.append((score, {key: value for key, value in record.items() if key != 'body'} |
                       {'text': excerpt, 'truncated': record.get('truncated', False) or len(excerpt) < len(record['body'])}))
    scored.sort(key=lambda item: (-item[0], item[1]['label']))
    return dict(sources=[source for _, source in scored[:limit]], matched=len(scored),
                truncated=scope['truncated'] or len(scored) > limit or any(source['truncated'] for _, source in scored[:limit]))


def organize(scope, sources):
    names = {source['repo_id']: source['name'] for source in sources if 'repo_id' in source}
    timeline, last = [], {}
    for row in sorted(scope['observations'], key=lambda row: (row['day'], row['repo_id'])):
        if row['repo_id'] not in names:
            continue
        before = last.get(row['repo_id'])
        timeline.append({**row, 'name': names[row['repo_id']], 'change_since_previous':
                         row['stars']-before if before is not None else None})
        last[row['repo_id']] = row['stars']
    groups = defaultdict(list)
    for source in sources:
        text = re.sub(r'\s+', ' ', source['text'].lower()).strip()
        if len(text) >= 80:
            groups[hashlib.sha256(text.encode()).hexdigest()].append(source['label'])
    topics = [{'title': title, 'sources': [s['label'] for s in sources if any(contains_term(s['text'], word) for word in family)]}
              for title, family in FAMILIES]
    return dict(timeline=timeline, topics=[item for item in topics if item['sources']],
                duplicates=[labels for labels in groups.values() if len(labels) > 1],
                note='Star为本地观测，首条无增量基线；README采集时间不是作者提交时间，重复节选不构成独立验证。')


def png_attachment(path):
    """只接受用户明确选择的静态 PNG；路径不会交给模型或作为工具参数。"""
    selected = Path(path)
    if selected.is_symlink() or not selected.is_file() or selected.suffix.lower() != '.png':
        raise ValueError('只支持明确选择的本地静态 PNG 截图')
    descriptor = os.open(selected, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 2_000_000:
            raise ValueError('PNG截图最多2MB，请选择普通文件')
        data = stream.read(2_000_001)
    if len(data) > 2_000_000 or not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('PNG文件无效或过大')
    pos, compressed, width, height, channels = 8, bytearray(), 0, 0, 0
    ended, seen_idat, after_idat, seen_palette = False, False, False, False
    while pos + 12 <= len(data):
        size, = struct.unpack('>I', data[pos:pos+4])
        kind, payload = data[pos+4:pos+8], data[pos+8:pos+8+size]
        if pos+12+size > len(data) or zlib.crc32(kind+payload) & 0xffffffff != int.from_bytes(data[pos+8+size:pos+12+size], 'big'):
            raise ValueError('PNG校验失败')
        if pos == 8 and kind != b'IHDR':
            raise ValueError('PNG头部无效')
        if not re.fullmatch(b'[A-Za-z]{4}', kind) or kind[2] & 32:
            raise ValueError('PNG区块类型无效')
        if seen_idat and kind not in {b'IDAT', b'IEND'}:
            after_idat = True
        if kind == b'IHDR':
            if width or size != 13:
                raise ValueError('PNG头部重复或无效')
            width, height, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', payload)
            channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color, 0)
            if not (0 < width <= 4096 and 0 < height <= 4096 and width*height <= 12_000_000
                    and depth == 8 and channels and compression == filtering == interlace == 0):
                raise ValueError('请使用非隔行、8位灰度/RGB/RGBA PNG，最多4096边长和1200万像素')
        elif kind in {b'acTL', b'fcTL', b'fdAT'}:
            raise ValueError('不接受动画PNG')
        elif kind == b'PLTE':
            if seen_palette or seen_idat or color in {0, 4} or not 0 < size <= 768 or size % 3:
                raise ValueError('PNG调色板无效')
            seen_palette = True
        elif kind == b'IDAT':
            if after_idat:
                raise ValueError('PNG像素区块必须连续')
            seen_idat = True
            compressed.extend(payload)
        elif kind == b'IEND':
            ended = size == 0 and pos+12 == len(data)
            break
        elif not kind[0] & 32:
            raise ValueError('PNG包含不支持的关键区块')
        pos += size+12
    expected = height * (width*channels+1)
    try:
        decoder = zlib.decompressobj()
        pixels = decoder.decompress(bytes(compressed), expected+1)
        valid = ended and seen_idat and expected > 0 and len(pixels) == expected and decoder.eof and not decoder.unused_data
    except zlib.error:
        valid = False
    if not valid or any(pixels[row*(width*channels+1)] > 4 for row in range(height)):
        raise ValueError('PNG像素数据无效')
    fingerprint = hashlib.sha256(data).hexdigest()
    return dict(label='I'+fingerprint[:16], name=selected.name[:150], fingerprint=fingerprint,
                data_url='data:image/png;base64,' + base64.b64encode(data).decode('ascii'))
