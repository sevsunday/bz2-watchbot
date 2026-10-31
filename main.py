import asyncio
import json
import logging
import logging.handlers
from datetime import datetime
import aiohttp
import config
import sys
import os
import re

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

class CustomFormatter(logging.Formatter):
    """Custom formatter that adds colors and simplified error format"""
    grey = "\x1b[38;21m"
    blue = "\x1b[38;5;39m"
    yellow = "\x1b[38;5;226m"
    red = "\x1b[38;5;196m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"

    FORMATS = {
        logging.DEBUG: f"{grey}%(message)s{reset}",
        logging.INFO: f"{blue}%(message)s{reset}",
        logging.WARNING: f"{yellow}WARNING: %(message)s{reset}",
        logging.ERROR: f"{red}ERROR: %(message)s{reset}",
        logging.CRITICAL: f"{bold_red}CRITICAL: %(message)s{reset}",
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)

def setup_logging():
    """Configure logging with both console and file output"""
    os.makedirs('logs', exist_ok=True)
    logger = logging.getLogger('bzbot')
    logger.setLevel(logging.DEBUG)  # Changed from INFO to DEBUG
    
    logger.handlers = []
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)  # Changed from INFO to DEBUG
    console_handler.setFormatter(CustomFormatter())
    logger.addHandler(console_handler)
    
    file_handler = logging.handlers.RotatingFileHandler(
        'logs/bzbot.log',
        maxBytes=1024 * 1024,
        backupCount=5,
        encoding='utf-8'
    )
    file_format = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_format)
    file_handler.setLevel(logging.DEBUG)  # Changed from INFO to DEBUG
    logger.addHandler(file_handler)
    
    return logger

logger = logging.getLogger('bzbot')

STEAM_JOIN_BASE = "steam://rungame/624970/76561198955218468/-connect-mp%20"
STEAM_PROFILE_BASE = "https://steamcommunity.com/profiles/"
STOCK_MOD_ID = "0"
SUPPRESS_EMBEDS = 1 << 2
DISCORD_CONTENT_LIMIT = 2000
API_TIMEOUT = aiohttp.ClientTimeout(total=20)


def clean_join_text(value):
    """Match Game Watch site clean(): strip HTML, collapse whitespace."""
    if value is None:
        return "Undefined"
    stripped = re.sub(r"<[^>]*>", "", str(value))
    cleaned = re.sub(r"\s+", " ", stripped).strip()
    if cleaned == "":
        return "Invalid Input"
    return cleaned


def string_to_hex(text):
    return "".join(f"{ord(char):02x}" for char in text)


def build_steam_join_url(session):
    """Build a steam://rungame join URL from session name, mods, and raw NAT."""
    name = session.get("Name")
    name_len = str(len(name)) if name else "0"

    game_data = session.get("Game") or {}
    game_mod = game_data.get("Mod")
    extra_mods = game_data.get("Mods")
    if extra_mods is not None:
        extra = ";".join(str(mod) for mod in extra_mods)
        mod_prefix = str(game_mod) if game_mod is not None else "undefined"
        mod_list = f"{mod_prefix};{extra}"
    elif game_mod is not None:
        mod_list = str(game_mod)
    else:
        mod_list = None

    if mod_list:
        mod_list_len = str(len(mod_list))
        mod_list_value = mod_list
    else:
        mod_list_len = "0"
        mod_list_value = ""

    nat = (session.get("Address") or {}).get("NAT") or ""
    plain_args = ",".join([
        "N",
        name_len,
        clean_join_text(name),
        mod_list_len,
        mod_list_value,
        nat,
        "0",
    ]) + ","
    return STEAM_JOIN_BASE + string_to_hex(plain_args)


_MARKDOWN_SPECIAL = re.compile(r"([\\*_~`|\[\]()<>#])")


def escape_markdown(text):
    return _MARKDOWN_SPECIAL.sub(r"\\\1", str(text))


def player_steam_id(player):
    steam_id = ((player.get('IDs') or {}).get('Steam') or {}).get('ID')
    return str(steam_id) if steam_id else None


def player_gog_id(player):
    gog_id = ((player.get('IDs') or {}).get('Gog') or {}).get('ID')
    return str(gog_id) if gog_id else None


def player_cache(api_response):
    return (((api_response or {}).get('DataCache') or {}).get('Players') or {}).get('IDs') or {}


def player_key(player):
    """Stable identity for a player: Steam ID, then GOG ID, then BZRNet ID, then in-game name."""
    steam_id = player_steam_id(player)
    if steam_id:
        return f"S{steam_id}"
    gog_id = player_gog_id(player)
    if gog_id:
        return f"G{gog_id}"
    bzr_id = ((player.get('IDs') or {}).get('BZRNet') or {}).get('ID')
    if bzr_id:
        return f"bzr:{bzr_id}"
    return f"name:{player.get('Name', '')}"


def player_display_name(player, api_response):
    cache = player_cache(api_response)
    steam_id = player_steam_id(player)
    if steam_id:
        nickname = ((cache.get('Steam') or {}).get(steam_id) or {}).get('Nickname')
        if nickname:
            return nickname
    gog_id = player_gog_id(player)
    if gog_id:
        username = ((cache.get('Gog') or {}).get(gog_id) or {}).get('Username')
        if username:
            return username
    return player.get('Name') or 'Unknown'


def player_profile_url(player, api_response):
    steam_id = player_steam_id(player)
    if steam_id:
        return f"{STEAM_PROFILE_BASE}{steam_id}/"
    gog_id = player_gog_id(player)
    if gog_id:
        return ((player_cache(api_response).get('Gog') or {}).get(gog_id) or {}).get('ProfileUrl')
    return None


def player_label(player, api_response):
    """(display name, profile URL) for a player; the URL is None when no profile is known."""
    return player_display_name(player, api_response), player_profile_url(player, api_response)


def format_label(label, linked=True):
    name, url = label
    escaped = escape_markdown(name)
    return f"[{escaped}]({url})" if linked and url else escaped


def build_roster(session, api_response):
    """Ordered {player_key: label} for every player in the session, in API order."""
    roster = {}
    for player in session.get('Players') or []:
        key = player_key(player)
        if key not in roster:
            roster[key] = player_label(player, api_response)
    return roster


def diff_rosters(previous, current):
    joined = [key for key in current if key not in previous]
    left = [key for key in previous if key not in current]
    return joined, left


def get_host(session, api_response):
    """(host player, display name, is monitored) for the session host, which the API lists first."""
    players = session.get('Players') or []
    if not players:
        return None, "Unknown", False
    host = players[0]
    is_monitored = player_steam_id(host) in config.MONITORED_STEAM_IDS
    return host, player_display_name(host, api_response), is_monitored


def get_max_players(session):
    player_types = session.get('PlayerTypes') or [{}]
    return player_types[0].get('Max', 0)


def format_join_leave_content(session, changes, linked=True):
    game_name = escape_markdown(session.get('Name') or 'Unnamed')
    player_count = (session.get('PlayerCount') or {}).get('Player', 0)
    max_players = get_max_players(session)
    change_text = ", ".join(f"{format_label(label, linked)} {action}" for label, action in changes)
    return f"**{game_name}** {player_count}/{max_players} ({change_text})"


class BZBot:
    def __init__(self):
        """Initialize the GameWatch client"""
        self.session = None
        self.message_ids = {webhook_id: {} for webhook_id in config.DISCORD_WEBHOOKS}
        self.is_running = True
        self.mods = {}
        self.active_sessions = {}
        self.rosters = {}
        self.missed_polls = {}
        self.last_api_responses = {}
        self.last_known_states = {}
        self.last_known_mods = {}
        
        try:
            with open('vsrmaplist.json', 'r') as f:
                self.vsr_maps = json.load(f)
        except Exception as e:
            logger.error(f"Warning: Could not load vsrmaplist.json: {e}")
            self.vsr_maps = []

    async def initialize(self):
        """Initialize the bot and verify webhook configurations"""
        self.session = aiohttp.ClientSession()
        
        if not config.DISCORD_WEBHOOKS:
            logger.error("No valid webhook configurations available. Please check your .env file and webhook configurations.")
            self.is_running = False
            return False
        return True

    async def close(self):
        if self.session:
            await self.session.close()

    async def fetch_api_data(self):
        """Fetch data from the API with better error handling"""
        try:
            logger.info(f"Fetching data from API: {config.API_URL}")
            async with self.session.get(config.API_URL, timeout=API_TIMEOUT) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    logger.error(f"API request failed with status {response.status}")
                    logger.debug(f"Response: {await response.text()}")
                    return None
        except asyncio.TimeoutError:
            logger.error(f"API request timed out after {API_TIMEOUT.total} seconds")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"Network error during API request: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error during API request: {str(e)}")
            return None

    async def format_session_embed(self, session, mods_mapping, api_response=None):
        """Creates a Discord embed for a game session"""
        try:
            _, host_name, _ = get_host(session, api_response)
            
            player_count = session.get('PlayerCount', {}).get('Player', 0)
            max_players = get_max_players(session)
            
            level = session.get('Level', {})
            game_mode = level.get('GameMode', {}).get('ID', 'Unknown')

            status = session.get('Status', {}).get('State', 'Unknown')
            time_seconds = session.get('Time', {}).get('Seconds', 0)
            time_mins = time_seconds // 60
            
            if status == "PreGame":
                status = f"In-Lobby ({time_mins} mins)"
                embed_color = 3447003  # Discord blue color
            elif status == "InGame":
                status = f"In-Game ({time_mins} mins)"
                embed_color = 3066993  # Discord green color
            else:
                embed_color = 3447003  # Default blue color
            
            nat_type = session.get('Address', {}).get('NAT_TYPE', 'Unknown')
            
            game_version = session.get('Game', {}).get('Version', 'Unknown')
            mod_id = str(session.get('Game', {}).get('Mod') or STOCK_MOD_ID)
            mod_name = mods_mapping.get(mod_id, {}).get('Name', 'Unknown')
            mod_url = mods_mapping.get(mod_id, {}).get('Url')

            if mod_url:
                mod_field = f"[{mod_name}]({mod_url})\n{game_version}"
            else:
                mod_field = f"{mod_name}\n{game_version}"

            steam_join_url = build_steam_join_url(session)
            encoded_args = steam_join_url.split("-connect-mp%20", 1)[-1]
            join_url = f"https://battlezonescrapfield.github.io/BZCC-Website/?join={encoded_args}"

            embed = {
                "title": "▶️  Join Game",
                "url": join_url,
                "fields": [],
                "footer": {
                    "text": f"GameWatch • Last Updated: {datetime.now().strftime('%I:%M %p')} 🔄"
                },
                "color": embed_color  # Use our dynamic color
            }

            # Add "View in Browser" link at the top
            embed["fields"].extend([
                {"name": "", "value": "[View in Browser](https://battlezonescrapfield.github.io/BZCC-Website/)", "inline": False},
            ])

            embed["fields"].extend([
                {"name": "🎮  Game Name", "value": f"```{session.get('Name', 'Unnamed')}```", "inline": True},
                {"name": "👤  Host", "value": f"```{host_name}```", "inline": True},
                {"name": "\u200b", "value": "\u200b", "inline": True},
                {"name": "👥  Players", "value": f"```{player_count}/{max_players}```", "inline": True},
                {"name": "📊  Status", "value": f"```{status}```", "inline": True},
                {"name": "\u200b", "value": "\u200b", "inline": True},
                {"name": "🎲  Mode", "value": f"```{game_mode}```", "inline": True},
                {"name": "🌐  NAT Type", "value": f"```{nat_type}```", "inline": True},
                {"name": "\u200b", "value": "\u200b", "inline": True},
            ])

            is_locked = session.get('Status', {}).get('IsLocked', False)
            if is_locked:
                embed["fields"].extend([
                    {"name": "🔒  Locked", "value": "```ansi\n\u001b[31mYes\u001b[0m```", "inline": True},
                    {"name": "\u200b", "value": "\u200b", "inline": True},
                    {"name": "\u200b", "value": "\u200b", "inline": True},
                ])

            teams = {}

            for player in session.get('Players', []):
                team_data = player.get('Team', {})
                team_id = str(team_data.get('ID', team_data.get('SubTeam', {}).get('ID', -1)))
                
                if team_id not in teams:
                    teams[team_id] = []
                
                prefix = "C: " if team_data.get('Leader') is True else ""
                player_name = f"{prefix}{format_label(player_label(player, api_response))}"
                
                kills = player.get('Stats', {}).get('Kills', 0)
                deaths = player.get('Stats', {}).get('Deaths', 0)
                score = player.get('Stats', {}).get('Score', 0)
                
                player_with_stats = f"{player_name} ({kills}/{deaths}/{score})"
                teams[team_id].append(player_with_stats)

            is_mpi = game_mode == "MPI"
            is_strat = game_mode == "STRAT"
            
            if is_strat or is_mpi:
                embed["fields"].append({"name": "\u200b", "value": "\u200b", "inline": False})

                team1_players = teams.get('1', [])
                team1_value = "\n".join(team1_players) if team1_players else "*Empty*"
                embed["fields"].append({
                    "name": "👥  **TEAM 1**",
                    "value": team1_value,
                    "inline": True
                })

                if is_mpi:
                    team2_value = "**Computer**"
                else:
                    team2_players = teams.get('2', [])
                    team2_value = "\n".join(team2_players) if team2_players else "*Empty*"
                
                embed["fields"].append({
                    "name": "👥  **TEAM 2**",
                    "value": team2_value,
                    "inline": True
                })

                embed["fields"].append({"name": "\u200b", "value": "\u200b", "inline": True})

                embed["fields"].append({"name": "\u200b", "value": "\u200b", "inline": False})

            map_file = level.get('MapFile', 'Unknown')
            map_name = level.get('Name', 'Unknown')
            
            if ':' in map_name:
                map_name = map_name.split(':')[-1].strip()
            
            clean_map_file = map_file.lower().replace('.bzn', '')
            if clean_map_file.endswith('25'):
                clean_map_file = clean_map_file[:-2]
            
            map_details = f"Name: {map_name}\n"
            map_details += f"File: {clean_map_file}\n"
            
            if map_file:
                vsr_map = next((m for m in self.vsr_maps if m.get('File', '').lower() == clean_map_file.lower()), None)
                
                if vsr_map:
                    pools = vsr_map.get('Pools', 'Unknown')
                    loose = vsr_map.get('Loose', 'Unknown')
                    b2b = vsr_map.get('Size', {}).get('baseToBase', 'Unknown')
                    size = vsr_map.get('Size', {}).get('formattedSize', 'Unknown')
                    author = vsr_map.get('Author', 'Unknown')
                    
                    map_details += f"\nPools: {pools}"
                    map_details += f"\nLoose: {loose}"
                    map_details += f"\nB2B Distance (m): {b2b}"
                    map_details += f"\nSize (m): {size}"
                    map_details += f"\nAuthor: {author}"
            
            embed["fields"].extend([
                {"name": "🗺️  Map Details", "value": f"[Browse Maps](https://vtstats.bz/map) | [View Map](https://vtstats.bz/map/{clean_map_file}/)\n```{map_details}```", "inline": False},
            ])

            embed["fields"].extend([
                {"name": "", "value": mod_field, "inline": True}
            ])

            map_image = level.get('Image')
            if map_image:
                embed["thumbnail"] = {"url": map_image}

            return embed
            
        except Exception as e:
            logger.error(f"An error occurred: {str(e)}")
            return None

    async def send_discord_notification(self, session, api_response=None, ping=False):
        """Post a "Game Up" message to every webhook that has no message for this session yet."""
        session_id = session['ID']
        targets = [
            (webhook_id, webhook_config)
            for webhook_id, webhook_config in config.DISCORD_WEBHOOKS.items()
            if session_id not in self.message_ids[webhook_id]
        ]
        if not targets:
            return

        embed = await self.format_session_embed(session, self.mods, api_response)
        if embed is None:
            logger.error(f"Could not build embed for session {session_id}, skipping Game Up post")
            return

        host, host_name, host_is_monitored = get_host(session, api_response)
        host_steam_id = player_steam_id(host) if host else None
        no_ping_ids = ["add_steam_ids_here"]  # ping for everyone
        # no_ping_ids = ["76561198825563594","76561198820311491", "76561199653748651"]  # mav | m.s | sev

        for webhook_id, webhook_config in targets:
            try:
                notification_suffix = ""
                if ping and host_is_monitored and host_steam_id not in no_ping_ids:
                    notification_suffix = webhook_config.notification_tag

                webhook_data = {
                    "username": "WatchBot",
                    "content": f"🆕 Game Up (Host: {escape_markdown(host_name)}) {notification_suffix}",
                    "embeds": [embed],
                    "allowed_mentions": {"parse": ["roles"]},
                }
                logger.info(f"Webhook content for {webhook_id}: {webhook_data['content']}")

                webhook_url = f"{webhook_config.url}?wait=true"
                async with self.session.post(webhook_url, json=webhook_data) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        self.message_ids[webhook_id][session_id] = response_data['id']
                        logger.info(f"Created new message for session {session_id} in webhook {webhook_id}")
                    else:
                        error_body = await response.text()
                        logger.error(f"Error creating message in webhook {webhook_id}: {response.status}")
                        logger.error(f"Webhook error body: {error_body}")
            except Exception as e:
                logger.error(f"Error processing webhook {webhook_id}: {str(e)}")

    async def update_session_embeds(self, session, api_response):
        """PATCH the embed in every webhook that already has a message for this session."""
        session_id = session['ID']
        targets = [
            (webhook_id, webhook_config)
            for webhook_id, webhook_config in config.DISCORD_WEBHOOKS.items()
            if session_id in self.message_ids[webhook_id]
        ]
        if not targets:
            return

        embed = await self.format_session_embed(session, self.mods, api_response)
        if embed is None:
            return

        for webhook_id, webhook_config in targets:
            message_id = self.message_ids[webhook_id][session_id]
            webhook_url = f"{webhook_config.url}/messages/{message_id}"
            try:
                async with self.session.patch(webhook_url, json={"embeds": [embed]}) as response:
                    if response.status == 404:
                        logger.warning(f"Message {message_id} not found in webhook {webhook_id}, will create new message")
                        self.message_ids[webhook_id].pop(session_id, None)
                    elif response.status not in [200, 204]:
                        logger.error(f"Error updating embed in webhook {webhook_id}: {response.status}")
            except Exception as e:
                logger.error(f"Error updating embed in webhook {webhook_id}: {str(e)}")

    async def end_game_embeds(self, session_id, previous_session, previous_response):
        """Mark the previous round's embed as ended so the next round gets a fresh one."""
        old_embed = await self.format_session_embed(previous_session, self.last_known_mods, previous_response)
        for webhook_id, webhook_config in config.DISCORD_WEBHOOKS.items():
            old_message_id = self.message_ids[webhook_id].pop(session_id, None)
            if not old_message_id or old_embed is None:
                continue
            ended_embed = {**old_embed, "title": "❌  Game Ended", "color": 15105570}  # Orange for ended games
            ended_embed.pop('url', None)
            webhook_url = f"{webhook_config.url}/messages/{old_message_id}"
            try:
                async with self.session.patch(webhook_url, json={"embeds": [ended_embed]}) as response:
                    if response.status not in [200, 204]:
                        logger.error(f"Error updating old embed in webhook {webhook_id}: {response.status}")
            except Exception as e:
                logger.error(f"Error updating old embed in webhook {webhook_id}: {e}")

    async def send_join_leave_notification(self, session, changes):
        """Send one message listing every join and leave seen in this poll."""
        if not config.DISCORD_WEBHOOKS:
            logger.warning("No valid webhooks available, skipping join/leave notification")
            return

        content = format_join_leave_content(session, changes)
        if len(content) > DISCORD_CONTENT_LIMIT:
            content = format_join_leave_content(session, changes, linked=False)[:DISCORD_CONTENT_LIMIT]

        summary = ", ".join(f"{name} {action}" for (name, _), action in changes)
        logger.info(f"[{session.get('Name', 'Unknown')}] {summary}")

        webhook_data = {
            "username": "WatchBot",
            "content": content,
            "flags": SUPPRESS_EMBEDS,
            "allowed_mentions": {"parse": []},
        }
        for webhook_id, webhook_config in config.DISCORD_WEBHOOKS.items():
            try:
                async with self.session.post(webhook_config.url, json=webhook_data) as response:
                    if response.status not in [200, 204]:
                        logger.error(f"Failed to send join/leave notification to webhook {webhook_id}: {response.status}")
            except Exception as e:
                logger.error(f"Error sending join/leave notification to webhook {webhook_id}: {str(e)}")

    def has_monitored_player(self, session):
        if (session.get('Name') or '').lower() == 'test':
            return False
        
        if session.get('Level', {}).get('GameMode', {}).get('ID') != "STRAT":
            return False
        
        _, _, host_is_monitored = get_host(session, None)
        return host_is_monitored

    async def check_sessions(self):
        try:
            api_response = await self.fetch_api_data()
            if not api_response:
                return

            self.mods = api_response.get('Mods') or {}
            self.last_known_mods = {**self.last_known_mods, **self.mods}
            
            sessions = [session for session in api_response.get('Sessions') or [] if session.get('ID')]
            current_session_ids = {session['ID'] for session in sessions}
            
            for session_id in list(self.active_sessions.keys()):
                if session_id in current_session_ids:
                    self.missed_polls.pop(session_id, None)
                    continue
                missed = self.missed_polls.get(session_id, 0) + 1
                if missed < config.SESSION_END_GRACE_POLLS:
                    self.missed_polls[session_id] = missed
                    logger.info(f"Session {session_id} missing from API ({missed}/{config.SESSION_END_GRACE_POLLS}), waiting before marking ended")
                    continue
                logger.info(f"Session {session_id} has ended, marking as ended")
                try:
                    await self.mark_session_ended(session_id)
                except Exception as e:
                    logger.error(f"Error marking session {session_id} as ended: {e}")
                    logger.exception("Full traceback:")

            for session in sessions:
                try:
                    await self.process_session(session, api_response)
                except Exception as e:
                    logger.error(f"Error processing session {session.get('ID')}: {e}")
                    logger.exception("Full traceback:")

        except Exception as e:
            logger.error(f"Error checking sessions: {e}")
            logger.exception("Full traceback:")

    async def process_session(self, session, api_response):
        session_id = session['ID']
        session_name = session.get('Name', 'Unknown')

        previous_session = self.active_sessions.get(session_id)
        is_monitored = self.has_monitored_player(session)
        if previous_session is None and not is_monitored:
            return

        previous_roster = self.rosters.get(session_id, {})
        previous_state = self.last_known_states.get(session_id)
        previous_response = self.last_api_responses.get(session_id)
        current_state = session.get('Status', {}).get('State')
        current_roster = build_roster(session, api_response)

        # Commit the new baseline before any Discord I/O so a failed request can't replay this poll's changes.
        self.active_sessions[session_id] = session
        self.rosters[session_id] = current_roster
        self.last_known_states[session_id] = current_state
        self.last_api_responses[session_id] = api_response

        if previous_session is None:
            logger.info(f"New session detected: {session_name}")
            await self.send_discord_notification(session, api_response, ping=True)
            return

        if not is_monitored:
            return

        if previous_state == "InGame" and current_state == "PreGame":
            logger.info(f"[{session_name}] Game ended, creating new embed")
            await self.end_game_embeds(session_id, previous_session, previous_response)

        await self.update_session_embeds(session, api_response)
        await self.send_discord_notification(session, api_response, ping=False)

        joined, left = diff_rosters(previous_roster, current_roster)
        if joined or left:
            changes = [(current_roster[key], "joined") for key in joined]
            changes += [(previous_roster[key], "left") for key in left]
            await self.send_join_leave_notification(session, changes)

    async def run(self):
        if not await self.initialize():
            logger.error("Failed to initialize bot. Exiting...")
            return

        try:
            logger.info(f"Bot started - checking every {config.CHECK_INTERVAL} seconds")
            logger.info(f"Active webhooks: {', '.join(config.DISCORD_WEBHOOKS.keys())}")
            logger.info("Press Ctrl+C to stop")
            while self.is_running:
                try:
                    await self.check_sessions()
                    await asyncio.sleep(config.CHECK_INTERVAL)
                except asyncio.CancelledError:
                    logger.info("Received shutdown signal...")
                    break
                except Exception as e:
                    logger.error(f"Error in main loop: {str(e)}")
                    logger.exception("Full traceback:")
                    await asyncio.sleep(config.CHECK_INTERVAL)  # Still sleep on error to prevent rapid retries
        except Exception as e:
            logger.error(f"An error occurred: {e}")
        finally:
            logger.info("Closing session...")
            await self.close()
            logger.info("Bot stopped")

    async def mark_session_ended(self, session_id):
        """Mark a session as ended and update its Discord message"""
        try:
            session = self.active_sessions.get(session_id)
            if session is None:
                return

            last_embed = await self.format_session_embed(session, self.last_known_mods, self.last_api_responses.get(session_id))
            if last_embed is None:
                logger.error(f"Could not build final embed for ended session {session_id}, leaving message as-is")
                return

            last_embed["title"] = "❌  Session Ended"
            last_embed.pop("url", None)
            last_embed["color"] = 15158332  # Red for ended sessions

            for webhook_id, webhook_config in config.DISCORD_WEBHOOKS.items():
                message_id = self.message_ids[webhook_id].get(session_id)
                if not message_id:
                    continue
                update_url = f"{webhook_config.url}/messages/{message_id}"
                try:
                    async with self.session.patch(update_url, json={"embeds": [last_embed]}) as response:
                        if response.status in [200, 204]:
                            logger.info(f"Updated message for ended session {session_id} in webhook {webhook_id}")
                        else:
                            logger.error(f"Failed to update ended session message in webhook {webhook_id}: {response.status}")
                except Exception as e:
                    logger.error(f"Error updating ended session message in webhook {webhook_id}: {e}")
        finally:
            for webhook_messages in self.message_ids.values():
                webhook_messages.pop(session_id, None)
            self.active_sessions.pop(session_id, None)
            self.rosters.pop(session_id, None)
            self.missed_polls.pop(session_id, None)
            self.last_api_responses.pop(session_id, None)
            self.last_known_states.pop(session_id, None)

async def main():
    bot = BZBot()
    try:
        # Send startup message to all webhooks
        startup_message = {
            "username": "BZ2 WatchBot",
            "embeds": [{
                "title": "The WatchBot has been restarted.",
                "description": "WatchBot settings were updated or the host machine was restarted. Relevant BZCC games will be posted when detected. For a game to be posted here, the host must be in my pre-configured host list.\n\nEach game within a session gets its own Discord embed, which is updated in real-time.\n\nIf you are a regular game host and do NOT want a game of yours to show up here, use 'test' for your game name.",
                "color": 3066993  # Discord green color
            }]
        }
        
        if config.DISCORD_WEBHOOKS:
            async with aiohttp.ClientSession() as session:
                for webhook_id, webhook_config in config.DISCORD_WEBHOOKS.items():
                    try:
                        async with session.post(webhook_config.url, json=startup_message) as response:
                            if response.status not in [200, 204]:
                                logger.error(f"Failed to send startup message to webhook {webhook_id}: {response.status}")
                    except Exception as e:
                        logger.error(f"Error sending startup message to webhook {webhook_id}: {str(e)}")
                        continue
        else:
            logger.error("No valid webhooks available. Please check your .env file and webhook configurations.")
            return
        
        await bot.run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Bot stopped by user")

if __name__ == "__main__":
    setup_logging()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Program terminated by user") 
