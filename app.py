import sys
import os
import json
import re
import shutil
import asyncio
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import QSizePolicy
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QCheckBox,
    QPushButton, QTextEdit, QLabel, QComboBox, QFormLayout, QInputDialog, QMessageBox
)
from PyQt5.QtCore import Qt
from telethon.sync import TelegramClient
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

IMAGE_MIME_TYPES = ['image/jpeg', 'image/png']
AUDIO_MIME_TYPES = ['audio/mpeg', 'audio/ogg']
DOWNLOAD_FOLDER = os.path.join(os.path.expanduser("~"), "Téléchargements", "telegram_medias")
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

API_KEYS_FILE = os.path.join(os.path.expanduser("~"), ".api_keys.json")

def load_api_keys():
    if os.path.exists(API_KEYS_FILE):
        with open(API_KEYS_FILE, "r") as f:
            return json.load(f)
    return []

def save_api_keys(keys):
    with open(API_KEYS_FILE, "w") as f:
        json.dump(keys, f, indent=2)

def file_already_downloaded(filename):
    for root, _, files in os.walk(DOWNLOAD_FOLDER):
        if filename in files:
            return True
    return False

class DownloadWorker(QThread):
    log_signal = pyqtSignal(str)

    def __init__(self, api_key, channel, options, parent=None):
        super().__init__(parent)
        self.api_key = api_key
        self.channel = channel
        self.options = options  # dictionnaire de booléens

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.download())

    async def download(self):
        try:
            session_name = ".session_" + self.api_key['name']
            SESSION_PATH = os.path.join(os.path.expanduser("~"), ".telegram_sessions", session_name)
            client = TelegramClient(SESSION_PATH, self.api_key['api_id'], self.api_key['api_hash'])

            await client.connect()

            if not await client.is_user_authorized():
                self.log_signal.emit("Connexion requise.")
                phone, ok = QInputDialog.getText(None, "Connexion", "Entrez votre numéro de téléphone :")
                if not ok or not phone:
                    self.log_signal.emit("Téléphone manquant.")
                    return

                await client.send_code_request(phone)
                code, ok = QInputDialog.getText(None, "Code de vérification", "Entrez le code reçu :")
                if not ok or not code:
                    self.log_signal.emit("Code non fourni.")
                    return

                try:
                    await client.sign_in(phone, code)
                except Exception as e:
                    if 'password' in str(e).lower():
                        password, ok = QInputDialog.getText(None, "Mot de passe requis", "Entrez votre mot de passe Telegram :", echo=QLineEdit.Password)
                        if not ok or not password:
                            self.log_signal.emit("Mot de passe non fourni.")
                            return
                        await client.sign_in(password=password)
                    else:
                        raise e

            self.log_signal.emit(f"Connexion réussie. Téléchargement du canal : {self.channel}")

            async for message in client.iter_messages(self.channel):
                if self.options.get("texts") and message.message:
                    content = message.message.strip()
                    if content:
                        self.log_signal.emit(f"[Message Texte #{message.id}]: {content[:60]}...")

                if message.media:

                    if isinstance(message.media, MessageMediaPhoto):
                        if not self.options.get("images"):
                            continue

                        filename = f"photo_{message.id}.jpg"
                        # ... reste inchangé

                    elif isinstance(message.media, MessageMediaDocument):
                        mime = message.media.document.mime_type or ""

                        if "video" in mime and not self.options.get("videos"):
                            continue
                        if "audio" in mime and not self.options.get("audios"):
                            continue
                        if mime.startswith("image/") and not self.options.get("images"):
                            continue
                        if mime in ["application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"] and not self.options.get("documents"):
                            continue

                        filename = "fichier_sans_nom"
                        for attr in message.media.document.attributes:
                            if hasattr(attr, 'file_name'):
                                filename = attr.file_name
                                break

                        if file_already_downloaded(filename):
                            self.log_signal.emit(f"Déjà téléchargé : {filename}")
                            continue

                        self.log_signal.emit(f"Téléchargement de `{filename}`...")
                        try:
                            path = await client.download_media(message.media, file=os.path.join(DOWNLOAD_FOLDER, filename))
                            self.log_signal.emit(f"✅ Terminé : {os.path.basename(path)}")
                        except Exception as e:
                            self.log_signal.emit(f"Erreur : {e}")

            await client.disconnect()
            self.log_signal.emit(f"Fin du téléchargement pour le canal : {self.channel}")

        except Exception as e:
            self.log_signal.emit(f"❌ Erreur : {e}")



class TelegramDownloader(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Telegram Medias Fast Downloader")
        self.resize(1000, 600)

        self.api_keys = load_api_keys()
        self.current_key = None

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        # Ligne 1 : Identifiants API
        api_layout = QHBoxLayout()
        api_label = QLabel("Identifiants API :")
        self.api_selector = QComboBox()
        self.api_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.api_selector.currentIndexChanged.connect(self.select_api_key)
        self.refresh_api_selector()

        self.add_api_button = QPushButton("Ajouter une clé API")
        self.add_api_button.clicked.connect(self.add_api_key)

        api_layout.addWidget(api_label)
        api_layout.addWidget(self.api_selector)
        api_layout.addWidget(self.add_api_button)

        # Ligne 2 : Canal + bouton
        channel_layout = QHBoxLayout()
        channel_label = QLabel("Canal Telegram :")
        self.channel_input = QLineEdit()
        self.channel_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.channel_input.setPlaceholderText("Lien ou ID du canal Telegram (ex: bamba_formation)")
        
        self.download_button = QPushButton("Lancer le téléchargement")
        self.download_button.clicked.connect(self.start_download)

        channel_layout.addWidget(channel_label)
        channel_layout.addWidget(self.channel_input)
        channel_layout.addWidget(self.download_button)

        # Synchroniser largeur min des deux (optionnel mais plus précis)
        self.api_selector.setMinimumWidth(300)
        self.channel_input.setMinimumWidth(300)

        # Log en bas
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet("background-color: black; color: white; font-family: Consolas; font-size: 12px;")

        # Ajout dans le layout principal
        layout.addLayout(api_layout)
        layout.addLayout(channel_layout)

        # Ligne 3 : Choix des types de médias
        media_layout = QHBoxLayout()
        self.chk_images = QCheckBox("Images")
        self.chk_audios = QCheckBox("Audios")
        self.chk_videos = QCheckBox("Vidéos")
        self.chk_docs = QCheckBox("Documents")
        self.chk_texts = QCheckBox("Textes")
        self.chk_images.setChecked(True)  # Optionnel : coché par défaut

        media_layout.addWidget(QLabel("Types à télécharger :"))
        media_layout.addWidget(self.chk_images)
        media_layout.addWidget(self.chk_audios)
        media_layout.addWidget(self.chk_videos)
        media_layout.addWidget(self.chk_docs)
        media_layout.addWidget(self.chk_texts)

        layout.addLayout(media_layout)

        # Log en bas
        layout.addWidget(self.log_output, stretch=1)

        self.setLayout(layout)


    def refresh_api_selector(self):
        self.api_selector.clear()
        for key in self.api_keys:
            self.api_selector.addItem(key['name'])
        if self.api_keys:
            self.current_key = self.api_keys[0]

    def select_api_key(self, index):
        if 0 <= index < len(self.api_keys):
            self.current_key = self.api_keys[index]

    def add_api_key(self):
        name, ok1 = QInputDialog.getText(self, "Nom de la clé", "Nom pour cette clé (ex: Clé secondaire)")
        if not ok1 or not name:
            return

        api_id, ok2 = QInputDialog.getInt(self, "API ID", "Entrez l'API ID")
        if not ok2:
            return

        api_hash, ok3 = QInputDialog.getText(self, "API Hash", "Entrez l'API Hash")
        if not ok3 or not api_hash:
            return

        self.api_keys.append({"name": name, "api_id": api_id, "api_hash": api_hash})
        save_api_keys(self.api_keys)
        self.refresh_api_selector()
        QMessageBox.information(self, "Ajouté", "Clé API ajoutée avec succès.")

    def log(self, message):
        self.log_output.append(message)
        self.log_output.ensureCursorVisible()

    def start_download(self):
        if not self.current_key:
            QMessageBox.warning(self, "Clé manquante", "Aucune clé API sélectionnée.")
            return

        channel = self.channel_input.text().strip()
        if not channel:
            QMessageBox.warning(self, "Champ vide", "Veuillez entrer un lien ou ID de canal.")
            return

        self.log_output.clear()
        self.log(f"Démarrage du téléchargement dans un thread...")

        options = {
            "images": self.chk_images.isChecked(),
            "audios": self.chk_audios.isChecked(),
            "videos": self.chk_videos.isChecked(),
            "documents": self.chk_docs.isChecked(),
            "texts": self.chk_texts.isChecked(),
        }

        self.download_thread = DownloadWorker(self.current_key, channel, options)

        self.download_thread.log_signal.connect(self.log)
        
        self.download_thread.start()


# --- MAIN ---
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TelegramDownloader()
    window.show()
    sys.exit(app.exec_())
