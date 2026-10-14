import logging
import re
import httpx
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse
from app.schemas.jira_schema import JiraProject, JiraExportResponse
from core.config import settings

logger = logging.getLogger(__name__)


class JiraService:
    def __init__(self):
        self.api_base = "https://api.atlassian.com"
        self.auth_base = "https://auth.atlassian.com"

    def normalize_browse_base_url(self, site_url: Optional[str]) -> Optional[str]:
        """Return a Jira browse base URL, never the Atlassian API hostname."""
        if not site_url:
            return None
        normalized = site_url.strip().rstrip("/")
        if not normalized:
            return None
        parsed = urlparse(normalized)
        if not parsed.scheme or not parsed.netloc:
            return None
        if parsed.netloc == "api.atlassian.com":
            return None
        return normalized

    async def get_accessible_resources(self, access_token: str) -> List[Dict[str, Any]]:
        """Fetch accessible Atlassian resources (cloud_ids)."""
        url = f"{self.api_base}/oauth/token/accessible-resources"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {access_token}"})
            resp.raise_for_status()
            return resp.json()

    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh an Atlassian OAuth 2.0 access token."""
        url = f"{self.auth_base}/oauth/token"
        payload = {
            "grant_type": "refresh_token",
            "client_id": settings.JIRA_CLIENT_ID,
            "client_secret": settings.JIRA_CLIENT_SECRET,
            "refresh_token": refresh_token,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                logger.error("Jira token refresh failed: %s", resp.text)
                resp.raise_for_status()
            return resp.json()

    async def get_myself(self, cloud_id: str, access_token: str) -> Dict[str, Any]:
        """Get current user information (to find accountId)."""
        url = f"{self.api_base}/ex/jira/{cloud_id}/rest/api/3/myself"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {access_token}"})
            resp.raise_for_status()
            return resp.json()

    async def get_projects(self, cloud_id: str, access_token: str) -> List[JiraProject]:
        """Fetch Jira projects for a given cloud site."""
        url = f"{self.api_base}/ex/jira/{cloud_id}/rest/api/3/project"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {access_token}"})
            resp.raise_for_status()
            projects_data = resp.json()
            return [JiraProject(key=p["key"], name=p["name"], id=p["id"]) for p in projects_data]

    async def get_server_info(self, cloud_id: str, access_token: str) -> Dict[str, Any]:
        """Fetch Jira server information (baseUrl, etc)."""
        url = f"{self.api_base}/ex/jira/{cloud_id}/rest/api/3/serverInfo"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {access_token}"})
            resp.raise_for_status()
            return resp.json()

    async def create_project(
        self, cloud_id: str, access_token: str, name: str, key: str, lead_account_id: str
    ) -> JiraProject:
        """Create a new Jira project (Kanban)."""
        url = f"{self.api_base}/ex/jira/{cloud_id}/rest/api/3/project"
        payload = {
            "key": key,
            "name": name,
            "leadAccountId": lead_account_id,
            "projectTypeKey": "software",
            "projectTemplateKey": "com.pyxis.greenhopper.jira:gh-simplified-agility-kanban",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if resp.status_code != 201:
                logger.error("Jira project creation failed: %s", resp.text)
                resp.raise_for_status()
            p = resp.json()
            return JiraProject(key=p["key"], name=name, id=p["id"])

    def _process_inline_markdown(self, text: str) -> List[Dict[str, Any]]:
        """Process inline markdown (bold, italic, links) into ADF marks."""
        # This is a basic regex-based parser for inline formatting
        # In a real app, a full markdown parser would be better

        parts = []
        last_idx = 0

        # Combined regex for links, bold, and italic
        # [text](url), **bold**, *italic*
        pattern = re.compile(r"(\[(.*?)\]\((.*?)\))|(\*\*(.*?)\*\*)|(\*(.*?)\*)")

        for match in pattern.finditer(text):
            # Add preceding plain text
            if match.start() > last_idx:
                parts.append({"type": "text", "text": text[last_idx : match.start()]})

            if match.group(1):  # Link [text](url)
                link_text = match.group(2)
                link_url = match.group(3)
                parts.append(
                    {
                        "type": "text",
                        "text": link_text,
                        "marks": [{"type": "link", "attrs": {"href": link_url}}],
                    }
                )
            elif match.group(4):  # Bold **text**
                bold_text = match.group(5)
                parts.append({"type": "text", "text": bold_text, "marks": [{"type": "strong"}]})
            elif match.group(6):  # Italic *text*
                italic_text = match.group(7)
                parts.append({"type": "text", "text": italic_text, "marks": [{"type": "em"}]})

            last_idx = match.end()

        # Add remaining text
        if last_idx < len(text):
            parts.append({"type": "text", "text": text[last_idx:]})

        return parts if parts else [{"type": "text", "text": text}]

    def _normalize_prompt_ai_markdown(self, text: str) -> str:
        if not text:
            return ""

        section_headings = {
            "strategic context",
            "technical implementation",
            "acceptance criteria",
            "rollout notes",
            "success verification",
            "actionable steps",
            "implementation guide",
        }

        normalized_lines: list[str] = []
        for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = raw_line.strip()
            if not line:
                normalized_lines.append("")
                continue

            if line.startswith("#"):
                normalized_lines.append(line)
                continue

            if re.match(r"^technical implementation guide\s*:", line, re.IGNORECASE):
                normalized_lines.append(f"## {line}")
                continue

            if re.match(r"^step\s+\d+\s*[:.-]", line, re.IGNORECASE):
                normalized_lines.append(f"### {line}")
                continue

            heading_candidate = line.rstrip(":").strip().lower()
            if heading_candidate in section_headings:
                normalized_lines.append(f"## {line.rstrip(':')}")
                continue

            if re.match(r"^\d+\.\s+", line):
                normalized_lines.append(line)
                continue

            if re.match(r"^[-*]\s+\[[ xX]\]\s+", line):
                normalized_lines.append(re.sub(r"^[-*]\s+\[[ xX]\]\s+", "- ", line))
                continue

            if re.match(r"^[-*]\s+", line):
                normalized_lines.append(line)
                continue

            normalized_lines.append(line)

        normalized_text = "\n".join(normalized_lines)
        normalized_text = re.sub(r"\n{3,}", "\n\n", normalized_text)
        return normalized_text.strip()

    def markdown_to_adf(self, text: str) -> Dict[str, Any]:
        """
        Improved Markdown to Atlassian Document Format (ADF) converter.
        Supports: Headings, Bullet Lists, Ordered Lists, Bold, Italic, Links.
        """
        if not text:
            return {"version": 1, "type": "doc", "content": []}

        lines = self._normalize_prompt_ai_markdown(text).split("\n")
        content = []
        current_list = None

        for line in lines:
            stripped = line.strip()

            # Handle empty lines - terminate list
            if not stripped:
                current_list = None
                continue

            # Headings
            if line.startswith("# "):
                current_list = None
                content.append(
                    {
                        "type": "heading",
                        "attrs": {"level": 1},
                        "content": self._process_inline_markdown(line[2:]),
                    }
                )
            elif line.startswith("## "):
                current_list = None
                content.append(
                    {
                        "type": "heading",
                        "attrs": {"level": 2},
                        "content": self._process_inline_markdown(line[3:]),
                    }
                )
            elif line.startswith("### "):
                current_list = None
                content.append(
                    {
                        "type": "heading",
                        "attrs": {"level": 3},
                        "content": self._process_inline_markdown(line[4:]),
                    }
                )
            # Bullet lists
            elif line.startswith("- ") or line.startswith("* "):
                if not current_list or current_list.get("type") != "bulletList":
                    current_list = {"type": "bulletList", "content": []}
                    content.append(current_list)

                current_list["content"].append(
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": self._process_inline_markdown(line[2:]),
                            }
                        ],
                    }
                )
            elif re.match(r"^\d+\.\s+", line):
                if not current_list or current_list.get("type") != "orderedList":
                    current_list = {"type": "orderedList", "attrs": {"order": 1}, "content": []}
                    content.append(current_list)

                item_text = re.sub(r"^\d+\.\s+", "", line, count=1)
                current_list["content"].append(
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": self._process_inline_markdown(item_text),
                            }
                        ],
                    }
                )
            # Regular paragraphs
            else:
                current_list = None
                content.append(
                    {"type": "paragraph", "content": self._process_inline_markdown(line)}
                )

        return {"version": 1, "type": "doc", "content": content}

    async def create_issue(
        self,
        cloud_id: str,
        access_token: str,
        project_key: str,
        summary: str,
        description_md: str,
        issue_type: str = "Task",
        site_url: Optional[str] = None,
    ) -> JiraExportResponse:
        """Create a Jira issue using ADF for description."""
        url = f"{self.api_base}/ex/jira/{cloud_id}/rest/api/3/issue"

        adf_description = self.markdown_to_adf(description_md)

        payload = {
            "fields": {
                "project": {"key": project_key},
                "summary": summary,
                "description": adf_description,
                "issuetype": {"name": issue_type},
            }
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if resp.status_code != 201:
                logger.error("Jira issue creation failed: %s", resp.text)
                resp.raise_for_status()

            data = resp.json()

            # Construct a direct clickable URL
            # Favor the provided site_url (e.g., https://your-domain.atlassian.net)
            # If site_url looks like an API URL or is missing, we use a slightly worse fallback
            clean_site_url = self.normalize_browse_base_url(site_url)
            browse_url = (
                f"{clean_site_url}/browse/{data['key']}"
                if clean_site_url
                else f"https://api.atlassian.com/ex/jira/{cloud_id}/browse/{data['key']}"
            )

            return JiraExportResponse(
                issue_id=data["id"], issue_key=data["key"], issue_url=browse_url
            )


jira_service = JiraService()
