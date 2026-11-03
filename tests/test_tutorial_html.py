from html.parser import HTMLParser
from types import SimpleNamespace

from github_stars.tutorial_html import export_tutorial, render_tutorial


def lesson_fixture():
    return {"title": "理解并实践研究工具", "summary": "把数据经过可解释的流程，得到可检验结果。",
            "concepts": [{"name": "表示", "explanation": "先定义输入输出。", "example": "将图像编码为向量。"}],
            "workflow": [{"title": "准备数据", "detail": "先确认授权和格式。"}, {"title": "评估", "detail": "使用未见过的样本。"}],
            "prerequisites": ["已安装 Python", "具有来源说明的数据"],
            "steps": [{"title": "运行最小示例", "goal": "确认依赖和输入均可用。", "instructions": "按官方示例准备输入。",
                       "command": "python demo.py --input sample.png", "expected": "生成可查看的结果文件。", "troubleshooting": "核对输入路径。"}],
            "configuration": [{"name": "input", "purpose": "选择输入", "example": "sample.png", "source": "README 示例"}],
            "related_projects": [{"name": "相关项目", "url": "https://github.com/example/related", "relationship": "同类接口，适合比较。", "evidence": "README 链接"}],
            "improvement_ideas": ["为输入为空添加明确错误提示。"], "contribution_steps": ["阅读 CONTRIBUTING", "新增能暴露问题的测试", "提交小范围 PR"],
            "checkpoints": [{"question": "怎样判断示例运行成功？", "answer": "根据预期结果检查输出，而不只看退出码。"}],
            "limitations": "未实际执行，性能需独立评估。"}


def row_fixture():
    return {"id": 42, "name": "example/research", "readme_url": "https://github.com/example/research/blob/main/README.md",
            "readme_sha": "readme-snapshot", "readme_at": "2026-11-03T09:00:00+08:00"}


class Document(HTMLParser):
    def __init__(self, document):
        super().__init__()
        self.elements = []
        self.text = []
        self.feed(document)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def test_lesson_has_readable_evidence_and_meaningful_learning_controls():
    document = Document(render_tutorial(row_fixture(), lesson_fixture()))
    elements = document.elements
    assert any(tag == "html" and attrs.get("data-theme") == "dark" for tag, attrs in elements)
    assert sum("data-flow" in attrs for _, attrs in elements) == 2
    assert sum("data-step-panel" in attrs for _, attrs in elements) == 1
    assert any(tag == "input" and attrs.get("type") == "checkbox" for tag, attrs in elements)
    assert any(tag == "progress" and attrs.get("max") == "1" for tag, attrs in elements)
    assert any(tag == "details" for tag, _ in elements)
    text = " ".join(document.text)
    assert "怎样判断示例运行成功" in text and "CONTRIBUTING" in text
    assert "readme-snapshot" in text and "2026-11-03" in text


def test_model_content_is_text_and_only_safe_github_urls_become_links():
    lesson = lesson_fixture()
    lesson["title"] = '<img src="x" onerror="alert(1)">'
    lesson["steps"][0]["command"] = '</pre><script>alert("model")</script>'
    lesson["related_projects"] += [
        {"name": "恶意链接", "url": "javascript:alert(1)", "relationship": "<iframe src=x>", "evidence": "不可信内容"},
        {"name": "冒充 GitHub", "url": "https://github.com.evil.example/owner/repo", "relationship": "应显示文字", "evidence": "测试"},
        {"name": "带身份信息", "url": "https://user:password@github.com/owner/repo", "relationship": "应显示文字", "evidence": "测试"},
        {"name": "离开仓库的路径", "url": "https://github.com/owner/repo/../../login", "relationship": "应显示文字", "evidence": "测试"},
    ]
    document = Document(render_tutorial(row_fixture(), lesson))
    assert not any(tag in {"img", "iframe"} for tag, _ in document.elements)
    assert sum(tag == "script" for tag, _ in document.elements) == 1  # 只剩本程序固定交互脚本。
    links = [attrs["href"] for tag, attrs in document.elements if tag == "a"]
    assert "https://github.com/example/related" in links
    assert all(link.startswith(("#", "https://github.com/")) for link in links)
    assert 'javascript:alert(1)' not in links
    assert '</pre><script>alert("model")</script>' in "".join(document.text)
    assert not any(tag in {"script", "link", "img"} and ("src" in attrs or "href" in attrs) for tag, attrs in document.elements)


def test_export_uses_safe_project_id_and_applies_selected_light_theme(tmp_path):
    paths = SimpleNamespace(data=tmp_path / "data")
    row = row_fixture()
    row["name"] = "../../not-a-filename"
    target = export_tutorial(paths, row, lesson_fixture(), 7, theme="light")
    assert target == paths.data / "tutorials" / "42-7.html"
    document = Document(target.read_text(encoding="utf-8"))
    assert any(tag == "html" and attrs.get("data-theme") == "light" for tag, attrs in document.elements)
    assert "切换深色" in "".join(document.text)
    assert not list(target.parent.glob("*.tmp"))


def test_missing_material_stays_explicit_instead_of_inventing_steps():
    document = Document(render_tutorial(row_fixture(), {"title": "材料不足", "summary": "等待补充", "limitations": "README 未说明"}))
    text = " ".join(document.text)
    assert "当前证据不足以提供实践步骤" in text
    assert "没有可核对的相关项目" in text
    assert not any("data-copy" in attrs for _, attrs in document.elements)
