"""
符合 Anthropic 标准的本地联网搜索工具
1. WebFetchTool - 网页内容获取工具
2. CodeSearchTool - 代码搜索工具 (类似 Sourcegraph)
"""
from typing import  Optional
from dataclasses import dataclass
import httpx
from urllib.parse import urlparse
from bs4 import BeautifulSoup

from base_comp.tool_base import ToolBase, ToolResp, TOOL_SUCCESS, TOOL_ERROR_AI, TOOL_ERROR_USER


# ============================================================================
# 搜索结果数据结构
# ============================================================================

@dataclass
class SearchResult:
    """单个搜索结果"""
    title: str
    url: str
    snippet: str
    repository: Optional[str] = None
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    score: Optional[float] = None


@dataclass
class SearchResults:
    """搜索结果集合"""
    total: int
    results: list[SearchResult]
    query: str
    truncated: bool = False


# ============================================================================
# 网页内容获取工具 (类似 OpenCode 的 fetch)
# ============================================================================

class WebFetchToolBase(ToolBase):
    """
    网页内容获取工具

    功能:
    - 从指定 URL 获取内容
    - 支持 text/markdown/html 三种格式
    - 自动处理 HTML 到 text/markdown 的转换
    - 内置安全检查(URL 验证、大小限制)
    """

    def __init__(
            self,
            max_response_size: int = 5 * 1024 * 1024,  # 5MB
            user_agent: str = "XJ-WebFetchTool/1.0"
    ):
        self.max_response_size = max_response_size
        self.user_agent = user_agent
        self.name = "web_fetch"
        self.description = """从 URL 获取网页内容并以指定格式返回。

        何时使用:
        - 需要获取网页、文档或 API 响应内容时
        - 用于研究、获取外部信息辅助完成任务时
        
        支持格式:
        - text: 纯文本格式，自动提取 HTML 中的文本内容
        - markdown: Markdown 格式，适合保留基本格式结构
        - html: 原始 HTML 内容
        
        限制:
        - 最大响应大小 5MB
        - 仅支持 HTTP 和 HTTPS 协议
        - 部分网站可能阻止自动化请求
        """

    def _get_input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要获取内容的 URL 地址"
                },
                "format": {
                    "type": "string",
                    "description": "返回格式: text, markdown, html",
                    "enum": ["text", "markdown", "html"]
                },
                "timeout": {
                    "type": "integer",
                    "description": "请求超时时间(秒)，最大120",
                    "minimum": 1,
                    "maximum": 120
                }
            },
            "required": ["url", "format"]
        }


    async def execute(self, *args, url: str, format: str = "text", timeout: int = 30) -> ToolResp:
        """执行网页获取，返回 ToolResp 对象"""
        # 验证 URL
        valid, error_msg = validate_url(url)
        if not valid:
            return ToolResp(status_code=TOOL_ERROR_AI, content=f"错误: {error_msg}")

        # 限制超时，最大120秒
        timeout = min(timeout, 120)

        try:
            async with httpx.AsyncClient(
                    timeout=httpx.Timeout(timeout),
                    follow_redirects=True,
                    headers={"User-Agent": self.user_agent}
            ) as client:
                response = await client.get(url)
                response.raise_for_status()

                # 检查响应大小
                content_length = len(response.content)
                if content_length > self.max_response_size:
                    return ToolResp(
                        status_code=TOOL_ERROR_AI,
                        content=f"错误: 响应大小 ({content_length} bytes) 超过限制 ({self.max_response_size} bytes)"
                    )

                content = response.text
                content_type = response.headers.get("Content-Type", "")

                # 根据格式处理内容
                if format == "text":
                    if "text/html" in content_type:
                        return ToolResp(status_code=TOOL_SUCCESS, content=extract_text_from_html(content))
                    return ToolResp(status_code=TOOL_SUCCESS, content=content)

                elif format == "markdown":
                    if "text/html" in content_type:
                        return ToolResp(status_code=TOOL_SUCCESS, content=convert_html_to_markdown(content))
                    return ToolResp(status_code=TOOL_SUCCESS, content=f"```\n{content}\n```")

                elif format == "html":
                    return ToolResp(status_code=TOOL_SUCCESS, content=content)

                return ToolResp(status_code=TOOL_SUCCESS, content=content)

        except httpx.TimeoutException:
            return ToolResp(status_code=TOOL_ERROR_AI, content=f"错误: 请求超时 ({timeout}秒)")
        except httpx.HTTPStatusError as e:
            return ToolResp(status_code=TOOL_ERROR_AI, content=f"错误: HTTP {e.response.status_code}")
        except Exception as e:
            return ToolResp(status_code=TOOL_ERROR_AI, content=f"错误: {str(e)}")


# ============================================================================
# 代码搜索工具 (类似 OpenCode 的 sourcegraph)
# ============================================================================

class CodeSearchToolBase(ToolBase):
    """
    代码搜索工具

    功能:
    - 使用 Sourcegraph API 搜索公开仓库代码
    - 支持丰富的查询语法 (file:, repo:, lang: 等)
    - 返回代码片段及上下文

    查询语法:
    - 基础搜索: "fmt.Println" 精确匹配
    - 文件过滤: "file:.go" 仅搜索 Go 文件
    - 仓库过滤: "repo:^github\\.com/golang/go$" 特定仓库
    - 语言过滤: "lang:python" Python 代码
    - 布尔运算: "AND", "OR", "NOT"
    """

    # Sourcegraph GraphQL 端点
    GRAPHQL_URL = "https://sourcegraph.com/.api/graphql"

    def __init__(
            self,
            user_agent: str = "XClaudeCode-CodeSearchTool/1.0",
            max_results: int = 20
    ):
        self.user_agent = user_agent
        self.max_results = max_results
        self.name = "code_search"
        self.description = """使用 Sourcegraph 搜索公开仓库代码。

何时使用:
- 需要在公开仓库中查找代码示例或实现时
- 研究他人如何解决类似问题时
- 发现开源代码中的模式和最佳实践时

查询语法:
- 基础搜索: "fmt.Println" 精确匹配
- 文件过滤: "file:.go" 仅 Go 文件
- 仓库过滤: "repo:^github\\.com/user/repo$" 特定仓库
- 语言过滤: "lang:python" Python 代码
- 布尔运算: "term1 AND term2", "term1 OR term2"
- 类型过滤: "type:symbol" 符号, "type:file" 文件

示例:
- "file:.go context.WithTimeout" - Go 代码示例
- "lang:typescript useState" - React Hooks
- "repo:kubernetes/kubernetes pod list" - Kubernetes 相关

限制:
- 仅搜索公开仓库
- 每次最多返回 20 条结果
"""

    def _get_input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Sourcegraph 搜索查询语句"
                },
                "count": {
                    "type": "integer",
                    "description": "返回结果数量，默认10，最大20",
                    "minimum": 1,
                    "maximum": 20
                },
                "context_lines": {
                    "type": "integer",
                    "description": "匹配行周围显示的上下文行数",
                    "minimum": 1,
                    "maximum": 20
                },
                "timeout": {
                    "type": "integer",
                    "description": "请求超时时间(秒)",
                    "minimum": 1,
                    "maximum": 120
                }
            },
            "required": ["query"]
        }

    def _build_graphql_query(self, query: str, count: int, context_lines: int) -> dict:
        """构建 GraphQL 查询"""
        return {
            "query": """query Search($query: String!) {
                search(
                    query: $query,
                    version: V2,
                    patternType: keyword
                ) {
                    results {
                        matchCount
                        limitHit
                        resultCount
                        approximateResultCount
                        results {
                            __typename
                            ... on FileMatch {
                                repository { name }
                                file { path url content }
                                lineMatches {
                                    preview
                                    lineNumber
                                    offsetAndLengths
                                }
                            }
                        }
                    }
                }
            }""",
            "variables": {"query": query}
        }

    def _format_results(self, data: dict, context_lines: int) -> str:
        """格式化搜索结果"""
        output = []

        if data.get("errors"):
            error_messages = [err.get("message", "Unknown error") for err in data["errors"]]
            return f"Sourcegraph API 错误: {', '.join(error_messages)}"

        search_data = data.get("data", {}).get("search", {})
        results = search_data.get("results", {})

        if not results:
            return "未找到结果或 API 返回格式异常"

        match_count = results.get("matchCount", 0)
        result_count = results.get("resultCount", 0)
        limit_hit = results.get("limitHit", False)

        output.append(f"# 搜索结果")
        output.append(f"找到 {match_count} 个匹配，来自 {result_count} 个结果")
        if limit_hit:
            output.append("(结果已截断，建议使用更精确的查询)")
        output.append("")

        matches = results.get("results", [])

        for i, match in enumerate(matches[:10], 1):  # 最多显示10条
            if match.get("__typename") != "FileMatch":
                continue

            repo = match.get("repository", {}).get("name", "unknown")
            file_path = match.get("file", {}).get("path", "")
            file_url = match.get("file", {}).get("url", "")
            line_matches = match.get("lineMatches", [])

            output.append(f"## {i}. {repo}/{file_path}")
            output.append(f"URL: {file_url}")
            output.append("")

            for lm in line_matches[:3]:  # 每个文件最多3个匹配
                line_number = lm.get("lineNumber", 0)
                preview = lm.get("preview", "")

                output.append(f"```{file_path}:{line_number}")
                output.append(f"{line_number}: {preview}")
                output.append("```")
                output.append("")

        if not matches:
            output.append("未找到结果，请尝试不同的查询语句")

        return "\n".join(output)

    async def execute(
            self,
            *args,
            query: str,
            count: int = 10,
            context_lines: int = 5,
            timeout: int = 30,
    ) -> ToolResp:
        """执行代码搜索，返回 ToolResp 对象"""
        # 检查查询语句是否为空
        if not query or not query.strip():
            return ToolResp(status_code=TOOL_ERROR_AI, content="错误: 查询语句不能为空")

        # 限制参数范围：count和context_lines最大20，timeout最大120
        count = min(max(count, 1), 20)
        context_lines = min(max(context_lines, 1), 20)
        timeout = min(timeout, 120)

        # 构建 GraphQL 查询
        graphql_query = self._build_graphql_query(query, count, context_lines)

        try:
            async with httpx.AsyncClient(
                    timeout=httpx.Timeout(timeout),
                    headers={
                        "User-Agent": self.user_agent,
                    }
            ) as client:
                response = await client.post(
                    self.GRAPHQL_URL,
                    json=graphql_query
                )
                response.raise_for_status()

                data = response.json()

                # 检查 GraphQL 错误
                if "errors" in data:
                    error_messages = [
                        err.get("message", "Unknown error")
                        for err in data["errors"]
                    ]
                    return ToolResp(status_code=TOOL_ERROR_AI, content=f"GraphQL 错误: {', '.join(error_messages)}")

                # 格式化并返回搜索结果
                formatted_results = self._format_results(data, context_lines)
                return ToolResp(status_code=TOOL_SUCCESS, content=formatted_results)

        except httpx.TimeoutException:
            return ToolResp(status_code=TOOL_ERROR_AI, content=f"错误: 请求超时 ({timeout}秒)")
        except httpx.HTTPStatusError as e:
            return ToolResp(status_code=TOOL_ERROR_AI, content=f"错误: HTTP {e.response.status_code}")
        except Exception as e:
            return ToolResp(status_code=TOOL_ERROR_AI, content=f"错误: {str(e)}")


def validate_url(url: str) -> tuple[bool, str]:
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

def extract_text_from_html(html: str) -> str:
    """从 HTML 提取纯文本"""
    soup = BeautifulSoup(html, "html.parser")

    # 移除 script 和 style 标签
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    # 获取文本
    text = soup.get_text(separator=" ", strip=True)

    # 清理多余空白
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text = " ".join(chunk for chunk in chunks if chunk)

    return text

def convert_html_to_markdown(html: str) -> str:
    """HTML 转 Markdown (简化实现)"""
    try:
        from markdownify import markdownify
        return markdownify(html)
    except ImportError:
        # 如果没有 markdownify，降级为纯文本
        return extract_text_from_html(html)

