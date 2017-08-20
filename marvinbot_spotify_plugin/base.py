from marvinbot.utils import localized_date, get_message, trim_markdown
from marvinbot.handlers import CommonFilters, CommandHandler, MessageHandler, CallbackQueryHandler
from marvinbot.plugins import Plugin
from marvinbot.net import download_file

from telegram import MessageEntity, InlineKeyboardMarkup, InlineKeyboardButton
from telegram import ChatAction

import re
import logging
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

log = logging.getLogger(__name__)


class SpotifyPlugin(Plugin):
    AUTH_BASE_URL = 'https://accounts.spotify.com/api/token'
    API_BASE_URL = 'https://api.spotify.com/v1/'

    def __init__(self):
        super(SpotifyPlugin, self).__init__('spotify')
        self.spotify = None
        self.url_pattern = None

    def get_default_config(self):
        return {
            'short_name': self.name,
            'enabled': True,
            'client_id': "",
            'client_secret': "",
            'url_pattern': r"https://open\.spotify\.com/(?P<type>track|album|artist)/(?P<id>[a-zA-Z0-9]+)"
        }

    def configure(self, config):
        log.info("Initializing Spotify Plugin")
        client_id = config.get("client_id")
        del config["client_id"]
        client_secret = config.get("client_secret")
        del config["client_secret"]
        self.url_pattern = re.compile(config.get("url_pattern"), flags=re.IGNORECASE)
        client_credentials_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
        self.spotify = spotipy.Spotify(client_credentials_manager=client_credentials_manager)

    def setup_handlers(self, adapter):
        self.add_handler(CommandHandler('spotify', self.on_spotify_command, command_description='Allows the user to search for songs on Spotify.')
                         #  .add_argument('--artists', help='Search for artists', action='store_true')
                         #  .add_argument('--albums', help='Search for albums', action='store_true')
                         #  .add_argument('--playlists', help='Search for playlists', action='store_true')
                         #.add_argument('--skip', help='Results to skip', default='0')
                         .add_argument('--count', help='Number of results', default='1')
                         .add_argument('terms', nargs='*', help='Search terms'))
        self.add_handler(MessageHandler(CommonFilters.entity(MessageEntity.URL), self.on_url))
        self.add_handler(CallbackQueryHandler('spotify:fetch-preview', self.on_button), priority=1)

    def on_spotify_command(self, update, **kwargs):
        message = get_message(update)
        query = (" ".join(kwargs.get('terms'))).strip()

        artists = kwargs.get('artists')
        albums = kwargs.get('albums')
        playlists = kwargs.get('playlists')
        n = int(kwargs.get('count',1))
        n = n if n >= 1 else 1
        s = int(kwargs.get('skip',0))
        s = s if s >= 0 else 0

        if artists:
            query_type = 'artist'
        elif albums:
            query_type = 'album'
        elif playlists:
            query_type = 'playlist'
        else:
            query_type = 'track'

        data = self.spotify.search(q=query, type=query_type)

        responses = []
        if query_type == 'track':
            for item in data["tracks"]["items"][s:s + n]:
                artists = ", ".join(
                    map(lambda a: "[{}]({})".format(trim_markdown(a["name"]),
                        a["external_urls"]["spotify"]), item["artists"]))
                track = "[{}]({})".format(trim_markdown(item["name"]), item["external_urls"]["spotify"])
                album = "[{}]({})".format(trim_markdown(item["album"]["name"]), item["album"]["external_urls"]["spotify"])
                response = "🎼 {track} by 🎙{artists} from 💽 {album}".format(track=track, album=album, artists=artists)
                responses.append(response)
        else:
            self.adapter.bot.sendMessage(chat_id=message.chat_id, text="Not yet implemented")
            return

        if not responses:
            self.adapter.bot.sendMessage(chat_id=message.chat_id, text="No results")
            return

        track_id = data["tracks"]["items"][s]["id"]
        callback_data = "{name}:{action}:{track_id}".format(name=self.name, action="fetch-preview", track_id=track_id)
        preview_button = InlineKeyboardButton(text="Preview", callback_data=callback_data)
        keyboard = [[preview_button]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        self.adapter.bot.sendMessage(chat_id=message.chat_id,
                                     text="\n\n".join(responses),
                                     parse_mode="Markdown",
                                     disable_web_page_preview=True,
                                     reply_markup=reply_markup)

    def on_url(self, update):
        message = get_message(update)

        urls = map(lambda url: message.text[url.offset:url.offset + url.length],
                   filter(lambda entity: entity.type == MessageEntity.URL, message.entities))

        for url in urls:
            m = self.url_pattern.match(url)
            if not m:
                continue
            if m.group("type") == "track":
                track_id = m.group("id")
                preview_url, filename = self.get_track_preview(track_id)
                self.fetch_and_send(message.chat_id, preview_url, filename)
            else:
                self.adapter.bot.sendMessage(chat_id=message.chat_id,
                                             text="❌ URL type not supported.")

    def on_button(self, update):
        query = update.callback_query
        data = query.data.split(":")
        track_id = data[2]
        query.answer('Fetching...')
        query.message.edit_reply_markup(reply_markup=None)
        preview_url, filename = self.get_track_preview(track_id)
        self.fetch_and_send(query.message.chat_id, preview_url, filename)

    def get_track_preview(self, track_id):
        track = self.spotify.track(track_id)
        preview_url = track["preview_url"]
        track_name = track["name"]
        artists = ", ".join(
            map(lambda a: trim_markdown(a["name"]), track["artists"]))
        filename = "{} - {}.mp3".format(artists, track_name)
        return preview_url, filename

    def fetch_and_send(self, chat_id, url, target_filename):
        def on_done(filename):
            self.adapter.bot.sendChatAction(chat_id=chat_id, action=ChatAction.UPLOAD_AUDIO)
            with open(filename, 'rb') as fp:
                self.adapter.bot.sendAudio(chat_id=chat_id, audio=fp)
        download_file(url=url, on_done=on_done, target_filename=target_filename)
