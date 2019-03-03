#!/usr/bin/env python3

"""Fetch data from instagram and create custom HTML pages."""

import argparse
import hashlib
import json
import os
import pickle
import re
import shutil
import sys
import textwrap
import time
from datetime import datetime
from glob import glob
from mimetypes import guess_extension
from pprint import pformat
from typing import Dict, List, Union

from colored import fg, attr, stylize
import requests
from jinja2 import Environment, FileSystemLoader
from utils.logs import log_init

__version__ = 1.0

DEFAULT_LOGLEVEL = 'INFO'
lo = log_init(DEFAULT_LOGLEVEL)

# todo: save data as pickle and load
# todo: lazyload images

# - Vars

MAX_PAGES = 50
MAX_IMGS = 250

#RELOAD = False

PAGE_ITEMS = 20
GRID_TYPE = 'sm'
# PAGE_ITEMS = 16
# GRID_TYPE = 'md'

# -

SLEEP_DELAY = 1
SLEEP_DELAY_IMG = 0.25
CONNECT_TIMEOUT = 3
MAX_RETRIES = 5
RETRY_DELAY = 2

BASE_URL = 'https://www.instagram.com/'
GQL_URL = BASE_URL + 'graphql/query/?query_hash=f2405b236d85e8296cf30347c9f08c2a&variables={}'
GQL_VARS = '{{"id":"{0}","first":50,"after":"{1}"}}'

#https://www.instagram.com/user/?__a=1 ? seems to be working again. rate limited?

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/67.0.3396.87 Safari/537.36'

COOKIE_NAME = 'cookies'

HTML_DIRNAME = 'html/'
IMGS_DIRNAME = 'imgs/'
THUMB_DIRNAME = 'thumbs/'
TEMPLATE_DIRNAME = 'templates/'
PICKLE_DIRNAME = 'pkls/'
HTML_DIR = HTML_DIRNAME
IMGS_DIR = HTML_DIR + IMGS_DIRNAME
THUMB_DIR = IMGS_DIR + THUMB_DIRNAME
TEMPLATE_DIR = HTML_DIR + TEMPLATE_DIRNAME
PICKLE_DIR = PICKLE_DIRNAME


class PartialContentException(Exception):
    pass

# all optional None, make custom typing dict
class Media:
    def __init__(self, **info):
        self.id: str = info['id']
        self.shortcode: str = info['shortcode']
        self.display_url: str = info['display_url']
        self.thumbnail_src: str = info['thumbnail_src']
        self.is_video: bool = info['is_video']
        self.video_url: str = info['video_url']
        self.video_view_count: int = info['video_view_count']
        self.accessibility_caption: str = info['accessibility_caption']
        self.comments_disabled: bool = info['comments_disabled']
        self.taken_at_timestamp: int = info['taken_at_timestamp']
        self.likes: int = info['likes']
        self.comments: int = info['comments']
        self.captions: List[str] = info['captions']
        self.dimensions: Dict[str, int] = info['dimensions']  # height, width
        self.location: Dict[str, Union[str, bool]] = info['location']  # id: int, has_public_page: bool, name: str, slug: str

        #self.mimetype: str = None
        self.thumb_file: str = None
        #self.content = None  # todo do i need this? and make these all thumb_

    def __str__(self):
        return f'Code: {self.shortcode}, Likes: {self.likes}, Vid: {self.is_video}'

    def __repr__(self):
        return self.__str__()


class InstaGet:
    def __init__(self, cookiejar=None):
        self.cookiejar = cookiejar

        self.session = requests.Session()
        self.session.headers = {'user-agent': USER_AGENT}
        if self.cookiejar and os.path.exists(self.cookiejar):
            with open(self.cookiejar, 'rb') as f:
                self.session.cookies.update(pickle.load(f))
        self.session.cookies.set('ig_pr', '1')

        self.cookies = None
        self.rhx_gis = None
        self.is_authed = False

        self.last_request = None

        self.user: str = None

    def _sleep(self, secs: float = None):
        if secs is None:
            if not self.last_request:
                secs = 0
            else:
                curr_time = time.time()
                sdiff = curr_time - self.last_request
                secs = SLEEP_DELAY - sdiff

        if secs > 0:
            time.sleep(secs)

    def _set_last(self):
        self.last_request = time.time()

    def safe_get(self, url: str, stream: bool = False, secs: float = None):
        tries = 0
        retry_delay = RETRY_DELAY

        while tries <= MAX_RETRIES:
            self._sleep(secs=secs)

            try:
                response = self.session.get(
                    url, timeout=CONNECT_TIMEOUT, cookies=self.cookies, stream=stream
                )
                if response.status_code == 404:
                    return
                response.raise_for_status()

                if not stream:
                    content_length = response.headers.get('Content-Length')
                    if content_length is not None and len(response.content) != int(content_length):
                        raise PartialContentException('Partial response')

            except (requests.exceptions.RequestException, PartialContentException) as e:
                if tries < MAX_RETRIES:
                    lo.w('Retrying after {} seconds for exception {} on {}...'.format(retry_delay, repr(e), url))
                    self._sleep(retry_delay)
                    self._set_last()
                    retry_delay *= 2
                    tries += 1
                    continue
                else:
                    lo.e('Max retries hit on {}'.format(url))
                    self._set_last()
                    return

            else:
                self._set_last()
                return response

    def save_media(self, media: Media):
        shortcode = media.shortcode

        matches = glob(THUMB_DIR + shortcode + '.*')
        matches_num = len(matches)

        if matches:
            media.thumb_file = matches[0]

            if matches_num == 1:  # more checks here on size, or set saved on media
                lo.d(f'{media.thumb_file} already saved, skipping.')
            else:
                lo.w(f'Found multiple files for {shortcode}: {", ".join(matches)}. Using {media.thumb_file}.')

        else:
            lo.d(f'Retrieving thumbnail for {shortcode}...')

            img_data = self.safe_get(media.thumbnail_src, secs=SLEEP_DELAY_IMG)

            ext = guess_extension(img_data.headers.get('content-type', '').partition(';')[0].strip())
            if not ext:
                ext = ''
            elif ext == '.jpe':
                ext = '.jpg'

            #media.mimetype = ext
            media.thumb_file = THUMB_DIR + shortcode + ext
            #media.content = img_data.content

            with open(media.thumb_file, 'wb') as f:
                f.write(img_data.content)

            lo.d(f'Saved {media.thumb_file}')

    def get_txt(self, url: str, is_json: bool = False):
        resp = self.safe_get(url)

        if resp is None:
            lo.e(f'No data for {url}')
        else:
            if is_json:
                return resp.json()
            else:
                return resp.text  # todo: json?

    def auth(self):
        self.session.headers.update({'Referer': BASE_URL})
        req = self.safe_get(BASE_URL)
        if req:
            self.session.headers.update({'X-CSRFToken': req.cookies['csrftoken']})
            self.is_authed = True
        else:
            lo.e('Could not auth.')

    def to_pickle(self, data: dict, filename: str):
        username = self.user or '_nouser'
        dirname = PICKLE_DIR + username
        if not os.path.exists(dirname):
            os.mkdir(dirname)

        with open(f'{dirname}/{filename}.pkl', 'wb') as f:
            pickle.dump(data, f)

    def load_pickle(self, filepath: str):
        if '/' not in filepath:
            username = self.user or '_nouser'
            filepath = f'{PICKLE_DIR}{username}/{filepath.replace(".pkl","")}.pkl'

        if not os.path.exists(filepath):
            lo.e(f'Could not find pickle for {filepath}')
            return

        with open(filepath, 'rb') as f:
            return pickle.load(f)

    def get_shared_data(self, data: str):
        if '_sharedData' in data:
            try:
                shared_data = data.split("window._sharedData = ")[1].split(";</script>")[0]
                data_json = json.loads(shared_data)
                self.rhx_gis = data_json['rhx_gis']
                return data_json
            except (TypeError, KeyError, IndexError) as e:
                lo.e(f'Exception {e} getting sharedData in response')
        else:
            lo.e('No sharedData in response')

    @staticmethod
    def get_page_data(data: dict):
        try:
            return data['entry_data']['ProfilePage'][0]['graphql']['user']
        except (AttributeError, TypeError, KeyError, IndexError) as e:
            lo.e(f'Exception {e} getting profile data')

    @staticmethod
    def convert_profile(page_data: dict):
        profile_data = {
            k: page_data.get(k) for k in
            ('biography', 'full_name', 'id', 'profile_pic_url_hd')
        }
        profile_data['followers'] = page_data.get('edge_followed_by', {}).get('count')
        return profile_data

    @staticmethod
    def convert_node(node: dict):
        info = {
            k: node.get(k) for k in
            ('id', 'shortcode', 'display_url', 'thumbnail_src', 'is_video', 'video_url', 'video_view_count',
             'accessibility_caption', 'comments_disabled', 'dimensions', 'location', 'taken_at_timestamp')
        }

        info['likes'] = node.get('edge_media_preview_like', {}).get('count')
        info['comments'] = node.get('edge_media_to_comment', {}).get('count')

        # todo: is this ever more than 1?
        #       combine to comprehension
        captions = []
        for caption in node.get('edge_media_to_caption', {}).get('edges', []):
            cap_txt = caption.get('node', {}).get('text')
            if cap_txt is not None:
                captions.append(cap_txt)

        info['captions'] = captions

        return Media(**info)

    def get_media(self, data: dict):
        media = data['edge_owner_to_timeline_media']
        if not media:
            return

        edges = media.get('edges')
        if not edges:
            return

        count = media.get('count')

        page_info = media.get('page_info')
        has_next_page = page_info['has_next_page']
        end_cursor = page_info['end_cursor']

        media_list: List[Media] = []

        for edge in edges:
            node = edge.get('node', {})

            fn = node.get('shortcode', '_none')
            if fn != '_none':
                fn = 'm_' + fn

            self.to_pickle(node, fn)

            info = self.convert_node(node)

            media_list.append(info)

        return {
            'count': count,
            'has_next_page': has_next_page,
            'end_cursor': end_cursor,
            'media_list': media_list
        }

    def save_cookies(self):
        if self.cookiejar:
            with open(self.cookiejar, 'wb') as f:
                pickle.dump(self.session.cookies, f)

    def update_ig_gis_header(self, params):
        data = self.rhx_gis + ":" + params
        ig_gis = hashlib.md5(data.encode('utf-8')).hexdigest()
        self.session.headers.update({'x-instagram-gis': ig_gis})

    def get_gql(self, qid, end_cursor):
        params = GQL_VARS.format(qid, end_cursor)
        self.update_ig_gis_header(params)

        resp = self.get_txt(GQL_URL.format(params), is_json=True)

        data = resp['data']['user']

        return self.get_media(data)

    def fetch_profile(self):
        lo.i('Parsing profile...')
        url = BASE_URL + self.user

        resp = self.get_txt(url)
        if resp is None:
            lo.e('Could not fetch profile')
        return resp

    def fetch_media(self, profile_id: str, max_pages: int, page_data: dict):
        lo.i(f'Parsing page 1 of {max_pages}...')

        first_page_data = self.get_media(page_data)

        total_items = first_page_data['count']

        lo.i(f'{total_items:,} total items')

        all_media = first_page_data['media_list']

        actual_pages = ((total_items - len(all_media)) // 50) + 2
        if actual_pages < max_pages:
            lo.w(f'Lowering total pages from {max_pages} to {actual_pages}')
            max_pages = actual_pages

        has_next = first_page_data['has_next_page']
        end_cursor = first_page_data['end_cursor']

        pnum = 2

        while pnum <= max_pages:  # do max items instead? or always 50, but 12 on first page
            if not has_next:
                lo.w('No more entries.')
                break

            lo.i(f'Parsing page {pnum} of {max_pages}...')

            gql_data = self.get_gql(profile_id, end_cursor)

            #lo.v('\n' + pformat(gql_data, indent=4))

            all_media += gql_data['media_list']

            has_next = gql_data['has_next_page']
            end_cursor = gql_data['end_cursor']

            pnum += 1

        lo.i('Done parsing')

        return all_media

    def scrape(
        self, user: str = None, max_pages: int = MAX_PAGES, max_images: int = MAX_IMGS, overwrite: bool = False
    ):
        if not user:
            user = self.user
            if not user:
                lo.e('No user set.')
                return
        else:
            self.user = user

        lo.i('Authing...')

        self.auth()
        if not self.is_authed:
            return

        if overwrite:
            shared_data = None
            page_data: dict = {}
            all_media: List[Media] = []
        else:
            lo.i('Loading cached data...')
            shared_data = None
            page_data = self.load_pickle('profile')
            all_media = [
                self.convert_node(
                    self.load_pickle(fn)
                )
                for fn in glob(f'{PICKLE_DIR}{user}/m_*.pkl')
            ]

        if not page_data:
            resp = self.fetch_profile()
            if resp is None:
                return

            shared_data = self.get_shared_data(resp)
            page_data = self.get_page_data(shared_data)
            if not isinstance(page_data, dict):
                return

            self.to_pickle(page_data, 'profile')

        profile_data = self.convert_profile(page_data)
        lo.v('\n' + pformat(profile_data, indent=4))

        # technically wrong if max images too high, past last page
        if not all_media or len(all_media) < max_images:
            if not shared_data:
                resp = self.fetch_profile()
                if resp is None:
                    return
                shared_data = self.get_shared_data(resp)
                if not shared_data:
                    return

            profile_id = profile_data['id']
            all_media = self.fetch_media(profile_id, max_pages, page_data)

        return profile_data, all_media

    @staticmethod
    def gen_html(_prof: dict, media_sort: List[Media], page_images: int = PAGE_ITEMS):
        lo.i('Creating html...')

        re_html = re.compile(r'^{}'.format(HTML_DIR))

        env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
        template = env.get_template('template.html')

        all_data = []
        for m in media_sort:
            str_date = datetime.utcfromtimestamp(m.taken_at_timestamp).strftime('%b %d, %y')

            if m.thumb_file:
                thumb_url = re_html.sub('', m.thumb_file)
            else:
                thumb_url = m.thumbnail_src

            if m.is_video:
                display_url = m.video_url
            else:
                display_url = m.display_url

            caption = '<br />'.join(cap.strip() for cap in m.captions)

            if isinstance(m.location, dict):
                location = m.location.get('name')
            else:
                location = None

            # todo add more data

            all_data.append({
                'big_url': display_url,
                'save_url': display_url,
                'small_url': thumb_url,
                'caption': caption,
                'likes': m.likes,
                'date': str_date,
                'is_video': m.is_video,
                'video_views': m.video_view_count,
                'location': location
            })

        return template.render(
            all_data=all_data, max_items=page_images, grid_type=GRID_TYPE
        )


BLUE  = fg(153)
RED   = fg(160)
GRAY  = fg(245)
RESET = attr('reset')

class CustomArgumentParser(argparse.ArgumentParser):
    def print_help(self, file=None):
        super().print_help(file)
        if self.epilog and set(self.epilog) == {'\n'}:
            self._print_message(self.epilog, file)

    def exit(self, status=0, message=None):
        if message:
            self._print_message(f'\n{stylize(message, RED)}\n', sys.stderr)
        sys.exit(status)

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, f'Error: {message}')


class CustomHelpFormatter(argparse.HelpFormatter):
    def __init__(self, prog):
        width = min(shutil.get_terminal_size((80, 20))[0] - 2, 120)
        max_help = 40
        super().__init__(prog, max_help_position=max_help, width=width)

    def add_usage(self, usage, actions, groups, prefix=None):
        if prefix is None:
            prefix = f'{stylize("Usage:", BLUE)}\n  '
        return super().add_usage(usage, actions, groups, prefix)

    def _split_lines(self, text, width):
        split_text = text.split('\n')
        return [line for para in split_text for line in textwrap.wrap(para, width)]

    def _fill_text(self, text, width, indent):
        split_text = text.split('\n')
        return '\n'.join(
            line for para in split_text for line in textwrap.wrap(
                para, width, initial_indent=indent, subsequent_indent=indent
            )
        )

    def _format_action_invocation(self, action):
        if not action.option_strings or action.nargs == 0:
            act_fmt = super()._format_action_invocation(action)
            if action.nargs == argparse.ONE_OR_MORE:
                return f'{act_fmt} [...]'
            return act_fmt
        else:
            default = self._get_default_metavar_for_optional(action)
            args_string = self._format_args(action, default)
            return ', '.join(action.option_strings) + ' %s' % args_string

def parse_args() -> argparse.Namespace:
    parser = CustomArgumentParser(
        description=f'{stylize(__doc__, GRAY)}',
        usage=f'{stylize("%(prog)s [options] username [...]", BLUE)}',
        formatter_class=CustomHelpFormatter,
        add_help=False,
        epilog='\n'
    )

    parser._positionals.title = 'Required'
    parser._optionals.title = 'Flags'

    parser.add_argument(
        'username', nargs='+', type=str,
        help='Instagram username'
    )

    grp_cache = parser.add_argument_group(title='Caching')

    grp_cache.add_argument(
        '-o', '--overwrite', action='store_true',
        help='Overwrite existing metadata'
    )
    grp_cache.add_argument(
        '-n', '--no-save-imgs', action='store_true',
        help='Do not save thumbnails, use instagram URLs'
    )

    grp_limits = parser.add_argument_group(title='Limits')

    grp_limits.add_argument( # none?
        '-m', '--max-pages', type=int, default=MAX_PAGES, metavar='<num>', # add <num> as default?
        help='Max pages to parse (default: %(default)d)'
    )
    grp_limits.add_argument(
        '-i', '--max-images', type=int, default=MAX_IMGS, metavar='<num>',
        help='Max images to display in HTML (default: %(default)d)'
    )
    grp_limits.add_argument(
        '-p', '--page-images', type=int, default=PAGE_ITEMS, metavar='<num>',
        help='Max images to display per page in HTML (default: %(default)d)'
    )

    grp_debug = parser.add_argument_group(title='Debug')

    grp_debug.add_argument(
        '-h', '--help', action='help', default=argparse.SUPPRESS,
        help='Show this help message and exit'
    )
    grp_debug.add_argument(
        '-v', '--version', action='version', version=f'{__version__}',
        help="Show the version number and exit"
    )
    grp_debug.add_argument(
        '-l', '--log-level', type=str, default=DEFAULT_LOGLEVEL.lower(), choices=[l.lower() for l in lo.levels], metavar='<lvl>',
        help='Log level for output (default: %(default)s)\nChoices: {%(choices)s}'
    )

    return parser.parse_args()
    # try:
    # except SystemExit as err:
    #     if err.code == 2:
    #         parser.print_help()
    #         sys.exit(2)


def main(
    username: List[str], overwrite: bool, no_save_imgs: bool, max_pages: int, max_images: int, page_images: int, log_level: str, **_kw):

    #todo allow int
    log_level = log_level.upper()
    if log_level != DEFAULT_LOGLEVEL:
        lo.set_level(log_level)

    scraper = InstaGet(cookiejar=COOKIE_NAME)

    for user in username:
        lo.s(f'Running for {user}')
        scraper.user = user

        total_possible_imgs = 12 + ((max_pages - 1) * 50)
        if max_images > total_possible_imgs:
            lo.w(f'Lowering max images from {max_images} to {total_possible_imgs}')
            max_images = total_possible_imgs

        data = scraper.scrape(max_pages=max_pages, max_images=max_images, overwrite=overwrite)
        scraper.save_cookies()

        if data is None:
            return

        prof, media = data

        lo.i(f'Found {len(media)} items.')

        media_sort = sorted(media, key=lambda x: x.likes, reverse=True)
        if max_images is not None:
            media_sort = media_sort[:max_images]

        if not no_save_imgs:
            lo.i(f'Saving images ({len(media_sort)})...')
            for m in media_sort:
                scraper.save_media(m)

        html = scraper.gen_html(prof, media_sort, page_images)

        filename = HTML_DIR + user + '.html'
        with open(filename, 'w') as f:
            f.writelines(html)
            lo.s(f'Wrote to {filename}')

    lo.s('Done')

if __name__ == '__main__':
    args = parse_args()
    dargs = vars(args)
    main(**dargs)
