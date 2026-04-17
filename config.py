import os
from dotenv import load_dotenv
from typing import Dict, NamedTuple
import logging

# Configure logging
logger = logging.getLogger('bzbot')

load_dotenv()

class WebhookConfig(NamedTuple):
    url: str
    notification_tag: str

def validate_webhook_configs() -> Dict[str, WebhookConfig]:
    """
    Validates webhook configurations and returns only valid ones.
    A valid webhook must have a non-empty URL from environment variables.
    """

    raw_configs = {
        "VSRCORD": WebhookConfig(
            url=os.getenv('DISCORD_WEBHOOK_URL'),
            notification_tag=""
        ),
        #"GREENCORD": WebhookConfig(
        #    url=os.getenv('GREENCORD_WEBHOOK_URL'),
        #    notification_tag=""  # no role ping for greencord
        #),
        # "SEVCORD": WebhookConfig(
        #    url=os.getenv('DISCORD_WEBHOOK_URL'),
        #     notification_tag=""  # ID for @BZ2Player
        #)

        # "STRATCORD": WebhookConfig(
        #     url=os.getenv('STRATCORD_WEBHOOK_URL'),
        #     notification_tag="<@&1119505038058991667>"  # ID for @BZ2Player
        # ),
        # "DEVWB_1": WebhookConfig(
        #     url=os.getenv('DEV_WEBHOOK_1'),
        #     notification_tag="<@&1302048771961520188>"  # ID-based role ping for @BZ2Player
        # ),
        # "DEVWB_2": WebhookConfig(
        #     url=os.getenv('DEV_WEBHOOK_2'),
        #     notification_tag="no-role-id"  # ID-based role ping for @BZ2Player
        # ),
        # Add more webhooks as needed, for example:
        # "SECONDARY": WebhookConfig(
        #     url=os.getenv('DISCORD_WEBHOOK_URL_2'),
        #     notification_tag="<@&your_role_id_here>"
        # ),
    }

    valid_configs = {}
    for webhook_id, config in raw_configs.items():
        if not config.url:
            logger.warning(f"Skipping webhook '{webhook_id}': Missing URL in environment variables")
            continue
        if not isinstance(config.url, str):
            logger.warning(f"Skipping webhook '{webhook_id}': URL must be a string")
            continue
        if not config.url.startswith(('http://', 'https://')):
            logger.warning(f"Skipping webhook '{webhook_id}': Invalid URL format")
            continue
        valid_configs[webhook_id] = config
        logger.info(f"Loaded webhook configuration for '{webhook_id}'")

    if not valid_configs:
        logger.warning("No valid webhook configurations found! Please check your .env file.")

    return valid_configs

# Dictionary of webhook configurations
# Each key is a unique identifier for the webhook (e.g., "MAIN", "SECONDARY")
# Each value is a WebhookConfig object containing the webhook URL and notification tag
DISCORD_WEBHOOKS: Dict[str, WebhookConfig] = validate_webhook_configs()

API_URL = "https://multiplayersessionlist.iondriver.com/api/1.0/sessions?game=bigboat:battlezone_combat_commander" 

# one of these players must be the game host, for a game to be posted
MONITORED_STEAM_IDS = [
    "76561198006115793",  # Domakus
    "76561198846500539",  # Xohm
    "76561198824607769",  # Cyber
    "76561197962996353",  # Herp
    "76561198076339639",  # Sly
    "76561198820311491",  # m.s 
    "76561198026325621",  # F9Bomber
    "76561199653748651",  # Sev
    # "76561198825563594",  # Maverick
    "76561198045619216",  # Zack
    "76561198043392032",  # blue_banana
    "76561199066952713",  # Nomad
    # "76561197974548434",  # VTrider
    # "76561198068133931",  # Econchump
    # "76561198825004088",  # Lamper
    # "76561198088036138",  # dd
    # "76561198058690608",  # JudgeGuns
    # "76561199732480793",  # XPi
    # "76561198088149233",  # Muffin
    # "76561198064801924",  # HappyOtter
    # "76561197970538803",  # Graves
    "76561198345909972",  # Vivify
]

CHECK_INTERVAL = 30 # seconds 
