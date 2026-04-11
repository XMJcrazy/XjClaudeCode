"""
web数据和markdown数据处理的基础工具模块

功能列表：
1. 读取指定url的html数据，设置最大文件大小限制
2. 将html数据格式化并返回指定标签的信息
3. 将html数据格式化并剔除指定标签信息
4. 将html数据转化成markdown数据，也可以将html的若干标签转化成markdown数据
5. 将html数据保存本地的方法，有临时保存和永久保存的选项，两者分开存放
6. 将markdown数据保存本地的方法，有临时保存和永久保存的选项，两者分开存放
7. 读取markdown文件并将数据格式化的方法，能够根据需要获取markdown文件的部分数据（某几个标签，某几段，某些类型的数据）
"""

import os
import uuid
import asyncio
import tempfile
from typing import Literal

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify


# ==================== 模块级常量 ====================

DEFAULT_MAX_SIZE = 5 * 1024 * 1024  # 默认5MB
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
)

# 临时文件路径，执行完就删除
TEMP_DIR = os.path.join(tempfile.gettempdir(), "web_md_temp")
# 持久存放路径
PERMANENT_DIR = os.path.join(os.path.expanduser("~"), "Documents", "WebMD")

# 默认剔除的html标签
DEFAULT_STRIP_TAGS = [
    "script",
    "style",
    "nav",
    "header",
    "footer",
    "aside",
    "iframe",
    "noscript",
]

# markdown常用标签
DEFAULT_EXTRACT_TAGS = [
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "a",
    "ul",
    "ol",
    "li",
    "code",
    "pre",
    "blockquote",
    "table",
]

# ==================== 初始化 ====================

# 确保目录存在
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(PERMANENT_DIR, exist_ok=True)


# ==================== 功能1：读取HTML数据（异步） ====================


async def fetch_html(
    url: str,
    timeout: int = 30,
    max_size: int = DEFAULT_MAX_SIZE,
    user_agent: str = DEFAULT_USER_AGENT,
) -> tuple[str, str | None]:
    """
    异步读取指定URL的HTML数据

    Args:
        url: 网页URL
        timeout: 请求超时时间（秒）
        max_size: 最大文件大小（字节）
        user_agent: User-Agent

    Returns:
        tuple: (html字符串, 错误信息或None)
    """
    if not url or not url.startswith(("http://", "https://")):
        return "", f"无效的URL格式: {url}"

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
            headers={"User-Agent": user_agent},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

        html = response.text
        html_size = len(html.encode("utf-8"))

        if html_size > max_size:
            size_mb = html_size / (1024 * 1024)
            max_mb = max_size / (1024 * 1024)
            return "", f"HTML大小 ({size_mb:.2f}MB) 超过限制 ({max_mb:.2f}MB)"

        return html, None

    except httpx.TimeoutException:
        return "", f"请求超时 ({timeout}秒)"
    except httpx.HTTPStatusError as e:
        return "", f"HTTP错误: {e.response.status_code}"
    except Exception as e:
        return "", f"获取失败: {str(e)}"


# ==================== 功能2：提取指定标签 ====================


def extract_tags(html: str, tags: list[str]) -> str:
    """
    从HTML中提取指定标签的内容

    Args:
        html: HTML字符串
        tags: 要提取的标签列表，如 ["h1", "p", "code"]

    Returns:
        格式化后的文本
    """
    if not html or not tags:
        return ""

    soup = BeautifulSoup(html, "html.parser")
    results = []

    for tag in tags:
        elements = soup.find_all(tag)
        for elem in elements:
            text = elem.get_text(strip=True)
            if text:
                results.append(f"[{tag}] {text}")

    return "\n".join(results)


# ==================== 功能3：剔除指定标签 ====================


def strip_tags(html: str, tags: list[str] = None) -> str:
    """
    从HTML中剔除指定标签及其内容

    Args:
        html: HTML字符串
        tags: 要剔除的标签列表，默认为DEFAULT_STRIP_TAGS

    Returns:
        剔除后的HTML字符串
    """
    if not html:
        return ""

    tags = tags or DEFAULT_STRIP_TAGS
    soup = BeautifulSoup(html, "html.parser")

    for tag in tags:
        for elem in soup.find_all(tag):
            elem.decompose()

    return str(soup)


# ==================== 功能4：HTML转Markdown ====================


def html_to_markdown(
    html: str,
    strip_tags_list: list[str] = None,
    heading_style: Literal["atx", "setex", "underlined"] = "atx",
    bullets: str = "-",
) -> str:
    """
    将HTML转换为Markdown

    Args:
        html: HTML字符串
        strip_tags_list: 要剔除的标签列表
        heading_style: 标题样式
        bullets: 列表符号

    Returns:
        Markdown字符串
    """
    if not html:
        return ""

    # 先剔除指定标签
    if strip_tags_list:
        html = strip_tags(html, strip_tags_list)

    # 转换为Markdown
    md = markdownify(
        html,
        heading_style=heading_style,
        bullets=bullets,
        strip=strip_tags_list or DEFAULT_STRIP_TAGS,
    )

    return _cleanup_markdown(md)


# ==================== 功能5：保存HTML到本地（异步） ====================


async def save_html(
    html: str, filename: str = None, permanent: bool = False
) -> tuple[str, str | None]:
    """
    异步保存HTML到本地文件

    Args:
        html: HTML字符串
        filename: 文件名（不包含扩展名），默认自动生成
        permanent: True永久保存，False临时保存

    Returns:
        tuple: (文件路径, 错误信息或None)
    """
    if not html:
        return "", "HTML内容为空"

    if filename is None:
        filename = f"html_{uuid.uuid4().hex[:8]}"

    # 确保有.html扩展名
    if not filename.endswith(".html"):
        filename += ".html"

    # 选择目录
    save_dir = PERMANENT_DIR if permanent else TEMP_DIR
    file_path = os.path.join(save_dir, filename)

    try:
        await asyncio.to_thread(_write_file, file_path, html)
        return file_path, None
    except Exception as e:
        return "", f"保存失败: {str(e)}"


# ==================== 功能6：保存Markdown到本地（异步） ====================


async def save_markdown(
    markdown: str, filename: str = None, permanent: bool = False
) -> tuple[str, str | None]:
    """
    异步保存Markdown到本地文件

    Args:
        markdown: Markdown字符串
        filename: 文件名（不包含扩展名），默认自动生成
        permanent: True永久保存，False临时保存

    Returns:
        tuple: (文件路径, 错误信息或None)
    """
    if not markdown:
        return "", "Markdown内容为空"

    if filename is None:
        filename = f"md_{uuid.uuid4().hex[:8]}"

    # 确保有.md扩展名
    if not filename.endswith(".md"):
        filename += ".md"

    # 选择目录
    save_dir = PERMANENT_DIR if permanent else TEMP_DIR
    file_path = os.path.join(save_dir, filename)

    try:
        await asyncio.to_thread(_write_file, file_path, markdown)
        return file_path, None
    except Exception as e:
        return "", f"保存失败: {str(e)}"


# ==================== 功能7：读取Markdown文件 ====================


def read_markdown(
    file_path: str, max_lines: int = None, tags: list[str] = None
) -> tuple[str, str | None]:
    """
    读取Markdown文件并可按需获取部分数据

    Args:
        file_path: Markdown文件路径
        max_lines: 最大行数限制，None则读取全部
        tags: 要提取的内容类型，如 ["h1", "h2", "code", "pre"]

    Returns:
        tuple: (Markdown内容, 错误信息或None)
    """
    if not os.path.exists(file_path):
        return "", f"文件不存在: {file_path}"

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # 限制行数
        if max_lines:
            lines = lines[:max_lines]

        content = "".join(lines)

        # 按标签类型提取
        if tags:
            content = extract_markdown_by_tags(content, tags)

        return content, None

    except Exception as e:
        return "", f"读取失败: {str(e)}"


# ==================== 内部辅助函数 ====================


def _write_file(file_path: str, content: str):
    """同步写入文件（供 asyncio.to_thread 调用）"""
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)


def _cleanup_markdown(md: str) -> str:
    """清理Markdown多余空白"""
    lines = []
    for line in md.splitlines():
        stripped = line.strip()
        if stripped:
            lines.append(stripped)

    # 合并，去除连续空行
    cleaned = []
    prev_empty = False
    for line in lines:
        current_empty = not line.strip()
        if not (current_empty and prev_empty):
            cleaned.append(line)
        prev_empty = current_empty

    return "\n".join(cleaned).strip()


def extract_markdown_by_tags(markdown: str, tags: list[str]) -> str:
    """
    从Markdown中按标签类型提取内容

    Args:
        markdown: Markdown字符串
        tags: 要提取的标签类型

    Returns:
        过滤后的Markdown内容
    """
    lines = markdown.splitlines()
    filtered = []
    tag_set = set(tags)

    for line in lines:
        line_type = _get_markdown_line_type(line)

        if line_type in tag_set:
            filtered.append(line)
        elif line_type == "list_item":
            if {"ul", "ol", "li"} & tag_set:
                filtered.append(line)
        elif line_type == "table":
            if "table" in tag_set:
                filtered.append(line)
        elif line_type == "code_block":
            if "pre" in tag_set or "code" in tag_set:
                filtered.append(line)

    return "\n".join(filtered)


def _get_markdown_line_type(line: str) -> str:
    """判断Markdown行的类型"""
    stripped = line.strip()

    if stripped.startswith("# "):
        return "h1"
    elif stripped.startswith("## "):
        return "h2"
    elif stripped.startswith("### "):
        return "h3"
    elif stripped.startswith("#### "):
        return "h4"
    elif stripped.startswith("##### "):
        return "h5"
    elif stripped.startswith("###### "):
        return "h6"
    elif stripped.startswith("```"):
        return "code_block"
    elif stripped.startswith(">"):
        return "blockquote"
    elif stripped.startswith("|"):
        return "table"
    elif (
        stripped.startswith("- ")
        or stripped.startswith("* ")
        or stripped.startswith("+ ")
    ):
        return "list_item"
    elif stripped[0].isdigit() and ". " in stripped[:5]:
        return "list_item"
    elif stripped.startswith("    ") or stripped.startswith("\t"):
        return "code"
    else:
        return "p" if stripped else ""


# ==================== 测试代码 ====================


async def run_tests():
    """逐个测试所有功能（异步版本）"""

    test_url = "https://github.com/shareAI-lab/learn-claude-code/blob/main/agents/s11_error_recovery.py"

    print("=" * 60)
    print("WebMarkdownTool 测试（静态方法版）")
    print("=" * 60)

    # 测试1：读取HTML
    print("\n【测试1】fetch_html - 读取HTML数据")
    print("-" * 40)
    html, error = await fetch_html(test_url, max_size=10 * 1024 * 1024)
    if error:
        print(f"✗ 失败: {error}")
    else:
        print(f"✓ 成功获取HTML，长度: {len(html)} 字符")
        print(f"预览（前200字符）: {html[:200]}...")

    # 测试2：提取指定标签
    print("\n【测试2】extract_tags - 提取指定标签")
    print("-" * 40)
    if html:
        extracted = extract_tags(html, ["h1", "p"])
        print(f"✓ 提取结果:\n{extracted}")
    else:
        print("⊘ 跳过（无HTML数据）")

    # 测试3：剔除指定标签
    print("\n【测试3】strip_tags - 剔除指定标签")
    print("-" * 40)
    if html:
        stripped_html = strip_tags(html, ["script", "style"])
        print(f"✓ 剔除后长度: {len(stripped_html)} 字符（原: {len(html)}）")
    else:
        print("⊘ 跳过（无HTML数据）")

    # 测试4：HTML转Markdown
    print("\n【测试4】html_to_markdown - HTML转Markdown")
    print("-" * 40)
    if html:
        md = html_to_markdown(html, strip_tags_list=["script", "style"])
        print(f"✓ 转换结果:\n{md[:300]}...")
    else:
        print("⊘ 跳过（无HTML数据）")

    # 测试5：保存HTML
    print("\n【测试5】save_html - 保存HTML到本地")
    print("-" * 40)
    if html:
        # 临时保存
        temp_path, error = await save_html(html, filename="test_temp", permanent=False)
        if error:
            print(f"✗ 临时保存失败: {error}")
        else:
            print(f"✓ 临时保存成功: {temp_path}")

        # 永久保存
        perm_path, error = await save_html(
            html, filename="test_permanent", permanent=True
        )
        if error:
            print(f"✗ 永久保存失败: {error}")
        else:
            print(f"✓ 永久保存成功: {perm_path}")
    else:
        print("⊘ 跳过（无HTML数据）")

    # 测试6：保存Markdown
    print("\n【测试6】save_markdown - 保存Markdown到本地")
    print("-" * 40)
    if html:
        md = html_to_markdown(html)
        if md:
            # 临时保存
            temp_md_path, error = await save_markdown(
                md, filename="test_md_temp", permanent=False
            )
            if error:
                print(f"✗ 临时保存失败: {error}")
            else:
                print(f"✓ 临时保存成功: {temp_md_path}")

            # 永久保存
            perm_md_path, error = await save_markdown(
                md, filename="test_md_permanent", permanent=True
            )
            if error:
                print(f"✗ 永久保存失败: {error}")
            else:
                print(f"✓ 永久保存成功: {perm_md_path}")
    else:
        print("⊘ 跳过（无HTML数据）")

    # 测试7：读取Markdown
    print("\n【测试7】read_markdown - 读取Markdown文件")
    print("-" * 40)
    if html:
        test_file = os.path.join(TEMP_DIR, "test_md_temp.md")
        if os.path.exists(test_file):
            # 完整读取
            content, error = read_markdown(test_file)
            if error:
                print(f"✗ 读取失败: {error}")
            else:
                print(f"✓ 完整读取成功，长度: {len(content)} 字符")

            # 限制行数
            content, error = read_markdown(test_file, max_lines=5)
            if error:
                print(f"✗ 限制行数读取失败: {error}")
            else:
                print(f"✓ 限制5行读取:\n{content}")

            # 按标签提取
            content, error = read_markdown(test_file, tags=["h1", "h2"])
            if error:
                print(f"✗ 标签过滤读取失败: {error}")
            else:
                print(f"✓ 按标签过滤结果:\n{content if content else '(无匹配)'}")
        else:
            print(f"⊘ 测试文件不存在，跳过: {test_file}")
    else:
        print("⊘ 跳过（无HTML数据）")

    # 清理测试文件
    print("\n【清理】删除测试文件")
    print("-" * 40)
    test_files = [
        os.path.join(TEMP_DIR, "test_temp.html"),
        # os.path.join(PERMANENT_DIR, "test_permanent.html"),
        os.path.join(TEMP_DIR, "test_md_temp.md"),
        # os.path.join(PERMANENT_DIR, "test_md_permanent.md"),
    ]
    for f in test_files:
        if os.path.exists(f):
            os.remove(f)
            print(f"✓ 已删除: {f}")

    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_tests())