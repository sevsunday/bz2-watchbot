import asyncio
import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiohttp

import config
import main

logging.getLogger('bzbot').addHandler(logging.NullHandler())
logging.getLogger('bzbot').propagate = False

PROFILE = "https://steamcommunity.com/profiles/"


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status = status
        self._payload = payload or {}

    async def json(self):
        return self._payload

    async def text(self):
        return ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeHTTP:
    """Stands in for aiohttp.ClientSession and records every Discord request."""

    def __init__(self):
        self.next_id = 0
        self.posts = []
        self.patches = []
        self.fail_next_patch = False
        self.patch_404 = set()

    def post(self, url, json=None):
        webhook_id = url.split('?')[0].rsplit('/', 1)[-1]
        self.next_id += 1
        self.posts.append((webhook_id, json))
        return FakeResponse(200, {"id": str(self.next_id)})

    def patch(self, url, json=None):
        base, message_id = url.split('/messages/')
        webhook_id = base.rsplit('/', 1)[-1]
        if self.fail_next_patch:
            self.fail_next_patch = False
            raise aiohttp.ClientError("simulated network failure")
        if webhook_id in self.patch_404:
            self.patch_404.discard(webhook_id)
            return FakeResponse(404)
        self.patches.append((webhook_id, message_id, json))
        return FakeResponse(200)

    async def close(self):
        pass


def steam_player(name, steam_id, slot, nickname=None):
    return {
        "Name": name,
        "Type": "Player",
        "Team": {"ID": "1", "SubTeam": {"ID": str(slot)}},
        "IDs": {"Slot": {"ID": slot}, "BZRNet": {"ID": f"S{steam_id}"}, "Steam": {"Raw": steam_id, "ID": steam_id}},
        "_nickname": nickname or name,
    }


def gog_player(name, gog_id, slot):
    return {
        "Name": name,
        "Type": "Player",
        "Team": {"ID": "1", "SubTeam": {"ID": str(slot)}},
        "IDs": {"Slot": {"ID": slot}, "BZRNet": {"ID": "G123"}, "Gog": {"Raw": "123", "ID": gog_id}},
    }


SEV = steam_player("Sev", "76561199653748651", 1)
XOHM = steam_player("Xohm", "76561198846500539", 1)
ALICE = steam_player("Alice", "76561190000000001", 2)
BOB = steam_player("Bob", "76561190000000002", 3)
CAROL = steam_player("Carol", "76561190000000003", 4)
DAVE = steam_player("Dave", "76561190000000004", 5)


def make_session(players, session_id="Rebellion:G1", name="vsr", mode="STRAT", state="PreGame", count=None):
    return {
        "ID": session_id,
        "Name": name,
        "PlayerTypes": [{"Types": ["Player"], "Max": 10}],
        "PlayerCount": {"Player": len(players) if count is None else count},
        "Level": {"MapFile": "vsreuropa25.bzn", "GameMode": {"ID": mode}, "Name": "VSR: Europa"},
        "Status": {"State": state},
        "Players": players,
        "Address": {"NAT": "abc", "NAT_TYPE": "FULL CONE"},
        "Game": {"Mod": "1325933293", "Version": "2.0"},
        "Time": {"Seconds": 0},
    }


def make_response(*sessions, gog=None):
    steam = {}
    for session in sessions:
        for player in session["Players"]:
            steam_id = player["IDs"].get("Steam", {}).get("ID")
            if steam_id:
                steam[steam_id] = {"Nickname": player["_nickname"], "ProfileUrl": f"https://steamcommunity.com/id/vanity{steam_id}/"}
    return {
        "Sessions": list(sessions),
        "Mods": {"0": {"Name": "Stock"}, "1325933293": {"Name": "VSR"}},
        "DataCache": {"Players": {"IDs": {"Steam": steam, "Gog": gog or {}}}},
    }


def link(name, steam_id):
    return f"[{name}]({PROFILE}{steam_id}/)"


class WatchBotTestCase(unittest.TestCase):
    webhooks = ("T",)

    def setUp(self):
        self._saved_webhooks = config.DISCORD_WEBHOOKS
        config.DISCORD_WEBHOOKS = {
            webhook_id: config.WebhookConfig(url=f"http://webhook.test/{webhook_id}", notification_tag="<@&42>")
            for webhook_id in self.webhooks
        }
        self.bot = main.BZBot()
        self.http = FakeHTTP()
        self.bot.session = self.http

    def tearDown(self):
        config.DISCORD_WEBHOOKS = self._saved_webhooks

    def poll(self, api_response):
        async def fetch():
            return api_response
        self.bot.fetch_api_data = fetch
        start = len(self.http.posts)
        asyncio.run(self.bot.check_sessions())
        return self.http.posts[start:]

    @staticmethod
    def join_leave(posts):
        return [payload["content"] for _, payload in posts if "embeds" not in payload]

    @staticmethod
    def game_ups(posts):
        return [(webhook_id, payload) for webhook_id, payload in posts if "embeds" in payload]


class JoinLeaveTests(WatchBotTestCase):
    def test_single_join_links_steam_profile_by_id(self):
        self.poll(make_response(make_session([SEV])))
        posts = self.poll(make_response(make_session([SEV, ALICE])))
        self.assertEqual(self.join_leave(posts), [f"**vsr** 2/10 ({link('Alice', '76561190000000001')} joined)"])

    def test_swap_in_one_poll_reports_both(self):
        self.poll(make_response(make_session([SEV, ALICE])))
        posts = self.poll(make_response(make_session([SEV, BOB])))
        self.assertEqual(self.join_leave(posts), [
            f"**vsr** 2/10 ({link('Bob', '76561190000000002')} joined, {link('Alice', '76561190000000001')} left)"
        ])

    def test_multiple_joins_all_reported_in_api_order(self):
        self.poll(make_response(make_session([SEV])))
        posts = self.poll(make_response(make_session([SEV, ALICE, BOB, CAROL])))
        self.assertEqual(self.join_leave(posts), [
            f"**vsr** 4/10 ({link('Alice', '76561190000000001')} joined, "
            f"{link('Bob', '76561190000000002')} joined, {link('Carol', '76561190000000003')} joined)"
        ])

    def test_leave_and_two_joins_same_poll(self):
        self.poll(make_response(make_session([SEV, ALICE])))
        posts = self.poll(make_response(make_session([SEV, BOB, CAROL])))
        self.assertEqual(self.join_leave(posts), [
            f"**vsr** 3/10 ({link('Bob', '76561190000000002')} joined, "
            f"{link('Carol', '76561190000000003')} joined, {link('Alice', '76561190000000001')} left)"
        ])

    def test_duplicate_display_names_tracked_by_steam_id(self):
        first = steam_player("Player", "76561190000000011", 2)
        second = steam_player("Player", "76561190000000012", 3)
        self.poll(make_response(make_session([SEV, first])))
        posts = self.poll(make_response(make_session([SEV, first, second])))
        self.assertEqual(self.join_leave(posts), [f"**vsr** 3/10 ({link('Player', '76561190000000012')} joined)"])

    def test_count_ahead_of_player_list_waits_for_roster(self):
        self.poll(make_response(make_session([SEV])))
        self.assertEqual(self.join_leave(self.poll(make_response(make_session([SEV], count=2)))), [])
        posts = self.poll(make_response(make_session([SEV, ALICE], count=2)))
        self.assertEqual(self.join_leave(posts), [f"**vsr** 2/10 ({link('Alice', '76561190000000001')} joined)"])

    def test_filtered_session_keeps_baseline_fresh(self):
        self.poll(make_response(make_session([SEV, ALICE])))
        self.assertEqual(self.poll(make_response(make_session([SEV, BOB], mode="MPI"))), [])
        self.assertEqual(self.poll(make_response(make_session([SEV, BOB, CAROL], mode="MPI"))), [])
        posts = self.poll(make_response(make_session([SEV, BOB, CAROL, DAVE])))
        self.assertEqual(self.join_leave(posts), [f"**vsr** 4/10 ({link('Dave', '76561190000000004')} joined)"])

    def test_failed_embed_patch_does_not_repeat_join(self):
        self.poll(make_response(make_session([SEV])))
        self.http.fail_next_patch = True
        first = self.poll(make_response(make_session([SEV, ALICE])))
        second = self.poll(make_response(make_session([SEV, ALICE])))
        self.assertEqual(len(self.join_leave(first)), 1)
        self.assertEqual(self.join_leave(second), [])

    def test_two_games_messages_name_their_game(self):
        g1 = lambda players: make_session(players, session_id="Rebellion:G1", name="vsr")
        g2 = lambda players: make_session(players, session_id="Rebellion:G2", name="vsr 2")
        self.poll(make_response(g1([SEV]), g2([XOHM])))
        posts = self.poll(make_response(g1([SEV, ALICE]), g2([XOHM, BOB])))
        self.assertEqual(self.join_leave(posts), [
            f"**vsr** 2/10 ({link('Alice', '76561190000000001')} joined)",
            f"**vsr 2** 2/10 ({link('Bob', '76561190000000002')} joined)",
        ])

    def test_leave_uses_name_from_previous_poll(self):
        renamed = steam_player("Alice", "76561190000000001", 2, nickname="AliceSteam")
        self.poll(make_response(make_session([SEV, renamed])))
        posts = self.poll(make_response(make_session([SEV])))
        self.assertEqual(self.join_leave(posts), [f"**vsr** 1/10 ({link('AliceSteam', '76561190000000001')} left)"])

    def test_gog_player_uses_cached_profile(self):
        gog = gog_player("mueller43", "58299767644965591", 2)
        gog_cache = {"58299767644965591": {"Username": "mueller43", "ProfileUrl": "https://www.gog.com/u/mueller43"}}
        self.poll(make_response(make_session([SEV]), gog=gog_cache))
        posts = self.poll(make_response(make_session([SEV, gog]), gog=gog_cache))
        self.assertEqual(self.join_leave(posts), ["**vsr** 2/10 ([mueller43](https://www.gog.com/u/mueller43) joined)"])

    def test_markdown_in_names_is_escaped(self):
        tricky = steam_player("xX_Alice_Xx", "76561190000000021", 2)
        self.poll(make_response(make_session([SEV], name="vsr_fun")))
        posts = self.poll(make_response(make_session([SEV, tricky], name="vsr_fun")))
        escaped_link = link("xX\\_Alice\\_Xx", "76561190000000021")
        self.assertEqual(self.join_leave(posts), ["**vsr\\_fun** 2/10 (" + escaped_link + " joined)"])

    def test_join_leave_payload_suppresses_previews_and_mentions(self):
        self.poll(make_response(make_session([SEV])))
        posts = self.poll(make_response(make_session([SEV, ALICE])))
        payload = [p for _, p in posts if "embeds" not in p][0]
        self.assertEqual(payload["flags"], 4)
        self.assertEqual(payload["allowed_mentions"], {"parse": []})

    def test_overlong_message_falls_back_to_plain_names(self):
        players = [SEV] + [steam_player("N" * 200 + str(i), f"7656119000000010{i}", i + 2) for i in range(9)]
        self.poll(make_response(make_session([SEV])))
        posts = self.poll(make_response(make_session(players)))
        content = self.join_leave(posts)[0]
        self.assertLessEqual(len(content), main.DISCORD_CONTENT_LIMIT)
        self.assertNotIn(PROFILE, content)


class SessionLifecycleTests(WatchBotTestCase):
    def test_new_game_pings_role_once(self):
        posts = self.poll(make_response(make_session([SEV])))
        (_, payload), = self.game_ups(posts)
        self.assertIn("<@&42>", payload["content"])
        self.assertEqual(payload["allowed_mentions"], {"parse": ["roles"]})
        self.assertEqual(self.poll(make_response(make_session([SEV]))), [])

    def test_unmonitored_host_is_ignored(self):
        self.assertEqual(self.poll(make_response(make_session([ALICE, SEV]))), [])

    def test_one_missed_poll_keeps_session(self):
        self.poll(make_response(make_session([SEV, ALICE])))
        self.poll(make_response())
        posts = self.poll(make_response(make_session([SEV, ALICE])))
        self.assertEqual(posts, [])
        self.assertFalse(any("Ended" in p["embeds"][0].get("title", "") for _, _, p in self.http.patches))

    def test_two_missed_polls_end_session(self):
        self.poll(make_response(make_session([SEV, ALICE])))
        self.poll(make_response())
        self.poll(make_response())
        titles = [p["embeds"][0].get("title") for _, _, p in self.http.patches]
        self.assertIn("❌  Session Ended", titles)
        self.assertNotIn("Rebellion:G1", self.bot.active_sessions)

    def test_ingame_to_pregame_ends_round_and_posts_new_embed(self):
        self.poll(make_response(make_session([SEV, ALICE], state="InGame")))
        posts = self.poll(make_response(make_session([SEV, ALICE], state="PreGame")))
        titles = [p["embeds"][0].get("title") for _, _, p in self.http.patches]
        self.assertIn("❌  Game Ended", titles)
        (_, payload), = self.game_ups(posts)
        self.assertNotIn("<@&42>", payload["content"])

    def test_none_embed_on_ended_session_does_not_block_other_games(self):
        self.poll(make_response(make_session([SEV], session_id="G1"), make_session([XOHM], session_id="G2")))
        real_format = self.bot.format_session_embed

        async def broken_for_g1(session, mods, api_response=None):
            if session.get("ID") == "G1":
                return None
            return await real_format(session, mods, api_response)

        self.bot.format_session_embed = broken_for_g1
        self.poll(make_response(make_session([XOHM], session_id="G2")))
        self.poll(make_response(make_session([XOHM], session_id="G2")))
        posts = self.poll(make_response(make_session([XOHM], session_id="G2"), make_session([SEV], session_id="G3")))
        self.assertNotIn("G1", self.bot.active_sessions)
        self.assertEqual(len(self.game_ups(posts)), 1)
        self.assertIn("G3", self.bot.message_ids["T"])


class MultiWebhookTests(WatchBotTestCase):
    webhooks = ("W1", "W2")

    def test_404_reposts_only_to_that_webhook(self):
        self.poll(make_response(make_session([SEV])))
        w2_message = self.bot.message_ids["W2"]["Rebellion:G1"]
        self.http.patch_404.add("W1")
        posts = self.poll(make_response(make_session([SEV, ALICE])))
        self.assertEqual([webhook_id for webhook_id, _ in self.game_ups(posts)], ["W1"])
        self.assertEqual(self.bot.message_ids["W2"]["Rebellion:G1"], w2_message)


if __name__ == "__main__":
    unittest.main()
