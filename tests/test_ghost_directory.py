import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from friend_circle_lite.ghost_directory import extract_friends, sync_directory, validate_feed
from friend_circle_lite.crawler.service import FriendCircleCrawlService
from friend_circle_lite.cli import FriendCircleLiteApplication
from friend_circle_lite.config.models import ApplicationConfig


def card(name="A", url="https://a.example/?ref=ghost.example", avatar="/content/images/a.webp"):
    return (f'<div class="kg-product-card"><h4 class="kg-product-card-title">{name}</h4>'
            f'<img class="kg-product-card-image" src="{avatar}">'
            f'<p><a href="https://description.example/">A description link</a></p>'
            f'<a class="kg-product-card-button" href="{url}">Visit</a></div>')


def page(cards):
    return ('<body class="friends-page"><nav><a href="https://nav.example">Nav</a></nav>'
            '<div class="friends-directory">' + cards + '</div>'
            '<div class="friend-circle">' + card("Not a friend", "https://article.example/") + '</div></body>')


class GhostDirectoryTest(unittest.TestCase):
    def test_extracts_only_directory_product_cards_and_resolves_images(self):
        result = extract_friends(page(card()), "https://ghost.example/links/")
        self.assertEqual(result, {"friends": [{"name": "A", "url": "https://a.example/",
                                               "avatar": "https://ghost.example/content/images/a.webp"}]})

    def test_rejects_wrong_template_empty_directory_or_incomplete_card(self):
        for html in ["<h1>Sign in</h1>", page(""), page(card().replace('kg-product-card-button', 'other')),
                     page(card(name="")), page(card(url="javascript:alert(1)")), page(card(avatar="data:image/png,x"))]:
            with self.subTest(html=html):
                with self.assertRaises(ValueError):
                    extract_friends(html, "https://ghost.example/links/")

    def test_duplicate_names_and_homepages_fail_instead_of_dropping_friends(self):
        for second in [card("A", "https://b.example/"), card("B", "https://a.example/#top")]:
            with self.assertRaises(ValueError):
                extract_friends(page(card() + second), "https://ghost.example/links/")

    def test_accepts_optional_avatar_and_preserves_image_query_string(self):
        image = 'https://images.example/image?url=avatar.png&amp;w=750&amp;q=100'
        result = extract_friends(page(card(avatar=image)), "https://ghost.example/links/")
        self.assertEqual(result['friends'][0]['avatar'], 'https://images.example/image?url=avatar.png&w=750&q=100')
        result = extract_friends(page(card().replace('<img class="kg-product-card-image" src="/content/images/a.webp">', '')),
                                 "https://ghost.example/links/")
        self.assertEqual(result['friends'][0]['avatar'], '')

    def test_next_sync_applies_add_delete_rename_and_avatar_changes(self):
        initial = extract_friends(page(card() + card("B", "https://b.example/")), "https://ghost.example/links/")
        changed = extract_friends(page(card("Renamed", avatar="/new.webp") + card("C", "https://c.example/")),
                                  "https://ghost.example/links/")
        self.assertEqual([x['name'] for x in changed['friends']], ['Renamed', 'C'])
        self.assertEqual(changed['friends'][0]['url'], initial['friends'][0]['url'])
        self.assertEqual(changed['friends'][0]['avatar'], 'https://ghost.example/new.webp')
        self.assertNotIn('B', [x['name'] for x in changed['friends']])

    def test_network_and_parse_failures_preserve_previous_file(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'friends.json'
            output.write_text('previous valid list', encoding='utf-8')
            with patch('friend_circle_lite.ghost_directory.requests.get', side_effect=requests.Timeout):
                with self.assertRaises(requests.Timeout):
                    sync_directory('https://ghost.example/links/', output)
            self.assertEqual(output.read_text(), 'previous valid list')
            response = Mock(text=page(''), url='https://ghost.example/links/')
            with patch('friend_circle_lite.ghost_directory.requests.get', return_value=response):
                with self.assertRaises(ValueError):
                    sync_directory('https://ghost.example/links/', output)
            self.assertEqual(output.read_text(), 'previous valid list')

    def test_sync_writes_list_atomically_using_redirected_page_url(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'friends.json'
            response = Mock(text=page(card()), url='https://canonical.example/links/')
            with patch('friend_circle_lite.ghost_directory.requests.get', return_value=response):
                sync_directory('https://ghost.example/links/', output)
            self.assertEqual(json.loads(output.read_text())['friends'][0]['avatar'],
                             'https://canonical.example/content/images/a.webp')

    def test_crawler_reads_generated_local_list_without_a_network_request(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'friends.json'
            path.write_text(json.dumps(extract_friends(page(card()), 'https://ghost.example/links/')))
            service = FriendCircleCrawlService(str(path), 10, cache_file=str(Path(directory) / 'cache.sqlite3'))
            session = Mock()
            websites = service._load_websites(session)
            self.assertEqual(websites[0].name, 'A')
            session.get.assert_not_called()
            path.write_text('[]')
            self.assertIsNone(service._load_websites(session))

    def test_failed_source_fetch_is_a_failed_run(self):
        app = FriendCircleLiteApplication(ApplicationConfig.from_dict({}))
        with patch('friend_circle_lite.cli.fetch_and_process_data', return_value=None):
            with self.assertRaises(RuntimeError):
                app.run_crawler_if_enabled()

    def test_preserves_all_sites_above_the_legacy_150_article_cutoff(self):
        articles = [dict(title=str(i), author='Recent', avatar='', link=f'https://a.example/{i}',
                         created='2025-01-01 00:00') for i in range(150)]
        articles.append(dict(title='Older friend', author='Older', avatar='', link='https://b.example/old',
                             created='2024-01-01 00:00'))
        result = {'statistical_data': {'article_num': 151}, 'article_data': articles}
        app = FriendCircleLiteApplication(ApplicationConfig.from_dict({'spider_settings': {'keep_all_articles': True}}))
        with patch('friend_circle_lite.cli.fetch_and_process_data', return_value=(result, [], {})), \
             patch('friend_circle_lite.cli.write_json') as write:
            app.run_crawler_if_enabled()
        output = write.call_args_list[0].args[1]
        self.assertEqual(len(output['article_data']), 151)
        self.assertEqual(output['article_data'][-1]['author'], 'Older')

    def test_publication_rejects_empty_stale_or_mismatched_results(self):
        directory = extract_friends(page(card()), 'https://ghost.example/links/')
        good = {'statistical_data': {'friends_num': 1, 'article_num': 1},
                'article_data': [{'title': 'Post', 'author': 'A', 'avatar': directory['friends'][0]['avatar'],
                                  'link': 'https://a.example/post'}]}
        validate_feed(directory, good)
        for key, value in [('author', 'Removed'), ('avatar', 'old-avatar.webp'), ('link', 'javascript:alert(1)')]:
            invalid = copy.deepcopy(good)
            invalid['article_data'][0][key] = value
            with self.assertRaises(ValueError):
                validate_feed(directory, invalid)
        with self.assertRaises(ValueError):
            validate_feed(directory, {'article_data': []})
        invalid = copy.deepcopy(good)
        invalid['statistical_data']['friends_num'] = 2
        with self.assertRaises(ValueError):
            validate_feed(directory, invalid)


if __name__ == '__main__':
    unittest.main()
