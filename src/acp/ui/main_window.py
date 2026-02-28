from __future__ import annotations

from PyQt6.QtWidgets import QApplication

from qfluentwidgets import FluentWindow, FluentIcon as FIF, NavigationItemPosition, setTheme, Theme

from ..core.state import AppState
from .log_bus import LogBus
from .interfaces.setup_interface import SetupInterface
from .interfaces.workspaces_interface import WorkspacesInterface
from .interfaces.config_interface import ConfigInterface
from .interfaces.run_interface import RunInterface
from .interfaces.network_interface import NetworkInterface
from .interfaces.logs_interface import LogsInterface
from .interfaces.about_interface import AboutInterface


class MainWindow(FluentWindow):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state

        setTheme(Theme.DARK)

        self.setWindowTitle("AgentChattr Control Panel")
        self.resize(1100, 760)
        self._center()

        # Shared log bus
        self.logBus = LogBus()

        # Interfaces (pass bus where useful)
        self.setupInterface = SetupInterface(self, state, self.logBus)
        self.workspacesInterface = WorkspacesInterface(self, state)
        self.configInterface = ConfigInterface(self, state)
        self.runInterface = RunInterface(self, state, self.logBus)
        self.networkInterface = NetworkInterface(self, state)
        self.logsInterface = LogsInterface(self, state, self.logBus)
        self.aboutInterface = AboutInterface(self, state)

        # Navigation — ordered by workflow: Setup → Workspaces → Config → LAN → Run
        self.addSubInterface(self.setupInterface, FIF.DOWNLOAD, "Setup")
        self.addSubInterface(self.workspacesInterface, FIF.FOLDER, "Workspaces")
        self.addSubInterface(self.configInterface, FIF.SETTING, "Config")
        self.addSubInterface(self.networkInterface, FIF.WIFI, "LAN & Security")
        self.addSubInterface(self.runInterface, FIF.PLAY, "Run")

        self.navigationInterface.addSeparator()

        self.addSubInterface(self.logsInterface, FIF.DOCUMENT, "Logs")

        self.addSubInterface(
            self.aboutInterface,
            FIF.INFO,
            "About",
            NavigationItemPosition.BOTTOM
        )

    def _center(self):
        desk = QApplication.primaryScreen().availableGeometry()
        self.move(desk.center() - self.rect().center())
