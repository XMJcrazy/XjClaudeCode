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
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify

from base_comp import ROOT_PATH

# ==================== 模块级常量 ====================

DEFAULT_MAX_SIZE = 5 * 1024 * 1024  # 默认5MB
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
)

# 临时文件路径，执行完就删除
TEMP_DIR = os.path.join(tempfile.gettempdir(), "web_md_temp")
# 持久存放路径
PERMANENT_DIR = os.path.join(ROOT_PATH, "data", "WebMD")

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

# 确保目录存在
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(PERMANENT_DIR, exist_ok=True)


def _validate_url(url: str) -> tuple[bool, str]:
    """验证 URL"""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False, "URL 必须以 http:// 或 https:// 开头"
        if not parsed.netloc:
            return False, "URL 缺少域名部分"
        return True, ""
    except Exception as e:
        return False, f"URL 格式错误: {e}"


async def fetch_html(
    url: str,
    format: str,
    timeout: int = 30,
    ignore_tags: list[str] = None,
    max_size: int = DEFAULT_MAX_SIZE,
    user_agent: str = DEFAULT_USER_AGENT,
) -> tuple[str, str | None]:
    """
    异步读取指定URL的HTML数据

    Args:
        url: 网页URL
        format: 转化成的格式，仅允许 html,text,markdown三种格式，默认是html
        timeout: 请求超时时间（秒）
        ignore_tags: 忽略的html标签，不传入就是默认配置
        max_size: 最大文件大小（字节）
        user_agent: User-Agent

    Returns:
        tuple: (html字符串, 错误信息或None)
    """
    is_ok, err_info = _validate_url(url)
    if not is_ok:
        return "", err_info
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
            headers={"User-Agent": user_agent},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

        html = response.text

        # 默认移除不重要的html标签，避免过多的无效数据
        soup = BeautifulSoup(html, "html.parser")
        if ignore_tags is None:
            ignore_tags = DEFAULT_STRIP_TAGS
        for tag in ignore_tags:
            for elem in soup.find_all(tag):
                elem.decompose()

        if format == "markdown":
            text = html_to_markdown(str(soup))
        elif format == "text":
            # 获取文本
            text = soup.get_text(separator=" ", strip=True)

            # 清理多余空白
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = " ".join(chunk for chunk in chunks if chunk)
        else:
            text = str(soup)

        if len(text) > max_size:
            size_mb = len(text) / (1024 * 1024)
            max_mb = max_size / (1024 * 1024)
            return "", f"网络数据大小 ({size_mb:.2f}MB) 超过限制 ({max_mb:.2f}MB)"

        return text, None
    except httpx.TimeoutException:
        return "", f"请求超时 ({timeout}秒)"
    except httpx.HTTPStatusError as e:
        return "", f"HTTP错误: {e.response.status_code}"
    except Exception as e:
        return "", f"获取失败: {str(e)}"


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


def html_to_markdown(
    html: str,
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

    # 转换为Markdown
    md = markdownify(
        html,
        heading_style=heading_style,
        bullets=bullets,
    )

    return _cleanup_markdown(md)


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

