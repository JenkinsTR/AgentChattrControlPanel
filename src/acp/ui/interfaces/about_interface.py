from __future__ import annotations

from PyQt6.QtWidgets import QWidget, QVBoxLayout

from qfluentwidgets import ScrollArea, SettingCardGroup, HyperlinkCard, FluentIcon as FIF

from ...core.state import AppState

class AboutInterface(ScrollArea):
    def __init__(self, parent, state: AppState):
        super().__init__(parent)
        self.state = state
        self.setObjectName("about")

        self.container = QWidget(self)
        self.setWidget(self.container)
        self.setWidgetResizable(True)

        self.v = QVBoxLayout(self.container)
        self.v.setContentsMargins(24, 24, 24, 24)
        self.v.setSpacing(18)

        self.group = SettingCardGroup("About", self.container)
        self.v.addWidget(self.group)

        self.creatorGroup = SettingCardGroup("Creator", self.container)
        self.v.addWidget(self.creatorGroup)

        self.creatorGroup.addSettingCard(HyperlinkCard(
            "https://github.com/JenkinsTR",
            "GitHub profile",
            FIF.GITHUB,
            "JenkinsTR",
            "Project author and maintainer.",
            parent=self.container
        ))

        self.creatorGroup.addSettingCard(HyperlinkCard(
            "https://jmd.vc",
            "Jenkins Media Digital website",
            FIF.GLOBE,
            "Jenkins Media Digital",
            "Company site and portfolio.",
            parent=self.container
        ))

        self.group.addSettingCard(HyperlinkCard(
            "https://github.com/bcurts/agentchattr",
            "agentchattr repository",
            FIF.LINK,
            "agentchattr",
            "Local coordination chat server with MCP support.",
            parent=self.container
        ))

        self.group.addSettingCard(HyperlinkCard(
            "https://developers.openai.com/codex/mcp/",
            "Codex MCP documentation",
            FIF.LINK,
            "Codex MCP",
            "How Codex configures MCP servers via config.toml.",
            parent=self.container
        ))

        self.group.addSettingCard(HyperlinkCard(
            "https://google-gemini.github.io/gemini-cli/docs/tools/mcp-server.html",
            "Gemini CLI MCP documentation",
            FIF.LINK,
            "Gemini CLI MCP",
            "How Gemini configures MCP servers via settings.json.",
            parent=self.container
        ))

        self.group.addSettingCard(HyperlinkCard(
            "https://pypi.org/project/PyQt6-Fluent-Widgets/",
            "PyQt6-Fluent-Widgets on PyPI",
            FIF.LINK,
            "QFluentWidgets",
            "QFluentWidgets (PyQt6) package details.",
            parent=self.container
        ))
