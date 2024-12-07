import sys
import re
import os
import threading
import requests
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QScrollArea,
    QPushButton, QWidget, QMessageBox, QGroupBox, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer

if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    dll_path = os.path.join(sys._MEIPASS, "Libs")  # Temporary extraction path
else:
    dll_path = os.path.join(os.path.dirname(__file__), "Libs")  # Development path

os.environ["PATH"] = dll_path + os.pathsep + os.environ["PATH"]
import mpv
from datetime import datetime

class Stream:
    def __init__(self):
        current_date = datetime.now()
        date = current_date.strftime("%Y-%m-%d")
        self.baseURL = f"https://web-api.scorarab.com/api/detail-matches/{date}?t=10"
        self.session = requests.session()
        self.session.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://koora.vip/",
            "Origin": "https://koora.vip"
        }
        self.data = self._fetch_data()

    def _fetch_data(self):
        try:
            response = self.session.get(self.baseURL)
            response.raise_for_status()
            return response.json()  # Parse the JSON response
        except requests.RequestException as e:
            print(f"Error fetching data: {e}")
            return []

    def getCategories(self):
        categories = {}

        for match in self.data:
            league = match.get("league_en", "").strip()
            home_team = match.get("home_en", "").strip()
            away_team = match.get("away_en", "").strip()
            
            # Handle home == away case
            match_info = f"{home_team}" if home_team == away_team else f"{home_team} vs {away_team}"
            
            channels = match.get("channels", [])

            if channels:  # Only include categories that have channels
                # Add match info to each channel
                enriched_channels = [
                    {**channel, "match_info": match_info} for channel in channels
                ]
                if league in categories:
                    categories[league].extend(enriched_channels)
                else:
                    categories[league] = enriched_channels

        return categories

    def getChannels(self, category):
        """
        Returns all channels for a given category (league_en).
        """
        for match in self.data:
            if match.get("league_en") == category:
                return match.get("channels", [])
        return []  # Return empty if category not found

    def getStream(self, channel):
        """Fetch the stream URLs and Referer for a given channel."""
        try:
            share_url = f"https://share.koora.vip/share.php?ch={channel['ch']}"
            share_response = self.session.get(share_url)
            if share_response.status_code == 200:
                html_content = share_response.text
                match = re.search(r'var token = "(https?://[^"]+\.m3u8)"', html_content)
                if match:
                    extracted_url = match.group(1)
                    referer = self.session.headers.get("Referer", "https://koora.vip/")
                    return {"urls": [extracted_url], "Referer": referer}
                else:
                    print(f"Failed to extract token URL for channel {channel['ch']}")
            else:
                print(f"Failed to fetch share page for channel {channel['ch']}. Status code: {share_response.status_code}")
        except Exception as e:
            print(f"Error fetching stream for channel {channel['ch']}: {e}")

        # Return empty structure if no data is available
        return {"urls": [], "Referer": ""}

    def isStreamWorking(self, url):
        """Check if a stream is working by sending a HEAD request."""
        try:
            response = self.session.head(url, timeout=5)
            return response.status_code == 200
        except requests.RequestException:
            return False


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IPTV")
        self.setMinimumSize(300, 600)
        self.stream = Stream()
        self.currentView = "categories"  # Tracks the current view ('categories' or 'channels')
        self.initUI()
        self.startCategoryRefresh()

    def initUI(self):
        self.mainWidget = QWidget()
        self.mainLayout = QVBoxLayout(self.mainWidget)
        self.setCentralWidget(self.mainWidget)

        # Enable right-click for return functionality
        self.mainWidget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.mainWidget.customContextMenuRequested.connect(self.onRightClick)

        self.loadCategories()

    def startCategoryRefresh(self):
        """Set up a timer to refresh the categories every 10 seconds."""
        self.refreshTimer = QTimer(self)
        self.refreshTimer.timeout.connect(self.refreshCategories)
        self.refreshTimer.start(10000)  # Refresh every 10 seconds

    def refreshCategories(self):
        """Refresh categories only if the current view is 'categories'."""
        if self.currentView == "categories":
            self.loadCategories()

    def loadCategories(self):
        self.currentView = "categories"  # Update view state
        self.clearLayout(self.mainLayout)

        # Create a group box for categories
        self.categoryGroupBox = QGroupBox("Categories")
        self.categoryLayout = QVBoxLayout(self.categoryGroupBox)

        # Fetch categories and remove empty ones
        categories = self.stream.getCategories()

        # Create a button for each non-empty category
        for category_name, channels in categories.items():
            button = QPushButton(category_name)
            button.clicked.connect(lambda checked, name=category_name, ch=channels: self.loadChannels(name, ch))
            self.categoryLayout.addWidget(button)

        self.mainLayout.addWidget(self.categoryGroupBox)
        self.adjustSize()  # Adjust size based on categories
        self.resize(self.sizeHint())  # Resize to fit the new content

    def loadChannels(self, category_name, channels):
        self.currentView = "channels"  # Update view state
        self.clearLayout(self.mainLayout)

        self.channelGroupBox = QGroupBox(f"Channels in {category_name}")
        self.channelLayout = QVBoxLayout(self.channelGroupBox)

        # Set size policies to allow expansion
        self.channelGroupBox.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        scrollArea = QScrollArea()
        scrollArea.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        scrollArea.setWidgetResizable(True)

        scrollWidget = QWidget()
        scrollLayout = QVBoxLayout(scrollWidget)
        scrollWidget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Group channels by match_info
        grouped_channels = {}
        for channel in channels:
            match_info = channel.get("match_info", "Unknown Match")
            if match_info not in grouped_channels:
                grouped_channels[match_info] = []
            grouped_channels[match_info].append(channel)

        # Create QGroupBox for each match
        for match_info, match_channels in grouped_channels.items():
            matchGroupBox = QGroupBox(match_info)
            matchLayout = QVBoxLayout(matchGroupBox)

            # Add buttons for channels in this match
            for channel in match_channels:
                button = QPushButton(channel.get("server_name_en", "Unknown Channel"))
                button.setEnabled(False)  # Disable until test result is known

                # Test stream in a separate thread and update the button color accordingly
                threading.Thread(target=self.testStreamAndSetColor, args=(channel, button), daemon=True).start()

                button.clicked.connect(lambda checked, ch=channel: self.playChannel(ch))
                matchLayout.addWidget(button)

            # Add the match group box to the main layout
            scrollLayout.addWidget(matchGroupBox)

        # Back button
        backButton = QPushButton("Back")
        backButton.clicked.connect(self.loadCategories)
        scrollLayout.addWidget(backButton)

        # Apply layout to scrollWidget
        scrollWidget.setLayout(scrollLayout)

        scrollArea.setWidget(scrollWidget)
        self.channelLayout.addWidget(scrollArea)
        self.channelGroupBox.setLayout(self.channelLayout)

        # Add the group box to the main layout
        self.mainLayout.addWidget(self.channelGroupBox)

        # Adjust the main window size
        self.adjustSize()  # Adjust size based on channel list
        self.resize(self.sizeHint())  # Resize to fit the new content

    def testStreamAndSetColor(self, channel, button):
        stream = self.stream.getStream(channel)
        if stream["urls"]:
            is_working = self.stream.isStreamWorking(stream["urls"][0])
            if is_working:
                button.setStyleSheet("background-color: green")
            else:
                button.setStyleSheet("background-color: red")
        else:
            button.setStyleSheet("background-color: red")
        button.setEnabled(True)  # Enable button after testing is done

    def playChannel(self, channel):
        # Fetch Stream and Play Using MPV
        stream = self.stream.getStream(channel)

        if stream["urls"]:
            thread = threading.Thread(target=self.run_mpv, args=(stream, channel), daemon=True)
            thread.start()
        else:
            QMessageBox.critical(self, "Error", "No stream available for this channel")

    def run_mpv(self, stream, channel):
        player = mpv.MPV(
            input_default_bindings=True,
            input_vo_keyboard=True,
            osc=True,
            http_header_fields=f"Referer: {stream.get('Referer', '')}"
        )

        player.play(stream["urls"][0])
        player.title = channel["server_name"]
        player.loop_file = "inf"

        try:
            player.wait_for_playback()
        finally:
            player.terminate()

    def onRightClick(self, pos):
        """Handle right-click event to return to categories."""
        if hasattr(self, "channelGroupBox"):
            for i in range(self.mainLayout.count()):
                item = self.mainLayout.itemAt(i)
                if item and item.widget() == self.channelGroupBox:
                    self.loadCategories()
                    break

    def clearLayout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                self.clearLayout(item.layout())


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
