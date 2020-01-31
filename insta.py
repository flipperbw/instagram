#!/usr/bin/env python3

"""Fetch data from instagram and create custom HTML pages."""
#from zmq.tests.test_security import USER

__version__ = 1.1
DEFAULT_LOGLEVEL = 'INFO'

MAX_PAGES = 50
MAX_IMGS = 500

#RELOAD = False

MAX_CAPTION = 275  # TODO better in html?


from my_utils.parsing import parser_init

def parse_args():
    parser = parser_init(
        description=__doc__,
        usage='%(prog)s [options] username [...]',
        log_level=DEFAULT_LOGLEVEL,
        version=__version__
    )

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

    grp_output = parser.add_argument_group(title='Output')

    grp_output.add_argument(
        '-s', '--size', choices=['sm', 'md'], default='md', metavar='<size>',
        help='Size of images in HTML output (default: %(default)s)\nChoices: {%(choices)s}'
    )
    grp_output.add_argument(
        '-r', '--rows', type=int, default=4, metavar='<num>',
        help='Max rows for images in HTML (default: %(default)d)'
    )
    # todo: sm does not work with video

    return parser.parse_args()

ARGS = None
if __name__ == '__main__':
    ARGS = parse_args()


import hashlib
import json
import math
import os
import pickle
import re
import requests
import time
from datetime import datetime
from glob import glob
from mimetypes import guess_extension
from pprint import pformat
from typing import Dict, List, Union, Optional

from jinja2 import Environment, FileSystemLoader
from my_utils.logs import log_init

# todo can I just do this instead? causes requests to show
# import logging
# logging.basicConfig(level=logging.DEBUG)


lo = log_init(DEFAULT_LOGLEVEL)

# todo: save data as pickle and load
#   lazyload images
#   fix ratelimiting at 20 requests?
#   filter by video
#   stories?
#   fix limit of nav numbers so there is a ... if they overlap
#   why is video_url missing now? login?
#   include link to original post


SLEEP_DELAY = 1.1
SLEEP_DELAY_IMG = 0.1
CONNECT_TIMEOUT = 3
MAX_RETRIES = 3
RETRY_DELAY = 2

BASE_URL = 'https://www.instagram.com/'
GQL_URL = BASE_URL + 'graphql/query/?query_hash=42323d64886122307be10013ad2dcc44&variables={}'
GQL_VARS_FIRST = '{{"id":"{0}","first":50}}'
GQL_VARS = '{{"id":"{0}","first":50,"after":"{1}"}}'

#https://www.instagram.com/user/?__a=1 ? seems to be working again. rate limited?

#USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/67.0.3396.87 Safari/537.36'
USER_AGENT = 'Instagram 52.0.0.8.83 (iPhone; CPU iPhone OS 11_4 like Mac OS X; en_US; en-US; scale=2.00; 750x1334) AppleWebKit/605.1.15'
STORIES_UA = 'Instagram 52.0.0.8.83 (iPhone; CPU iPhone OS 11_4 like Mac OS X; en_US; en-US; scale=2.00; 750x1334) AppleWebKit/605.1.15'

COOKIE_NAME = 'cookies'

PICKLE_DIRNAME = 'pkls/'
TEMPLATE_DIRNAME = 'templates/'
HTML_DIRNAME = 'html/'
IMGS_DIRNAME = 'img/'
THUMB_DIRNAME = 'thumb/'

PICKLE_DIR = PICKLE_DIRNAME
TEMPLATE_DIR = TEMPLATE_DIRNAME
HTML_DIR = HTML_DIRNAME
IMG_DIR = HTML_DIR + IMGS_DIRNAME
THUMB_DIR = IMG_DIR + THUMB_DIRNAME

HTML_TEMPLATE = 'main'


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
        self.thumb_file: Optional[str] = None
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
        self.rhx_gis = ''
        self.is_authed = False

        self.last_request = None

        self.user: Optional[str] = None

        self.jinja_env = Environment(
            loader=FileSystemLoader(TEMPLATE_DIR),
            trim_blocks=True,
            lstrip_blocks=True
        )

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

                status = response.status_code
                if status in (403, 404, 429):
                    if status == 403:
                        lo.w(f'Forbidden: {url}')
                    elif status == 404:
                        lo.w(f'Not found: {url}')
                    elif status == 429:
                        lo.w(f'Rate limited: {url}')

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

    def save_media(self, media: Media, overwrite: bool = True):
        shortcode = media.shortcode

        if not overwrite:
            matches = glob(THUMB_DIR + shortcode + '.*')
        else:
            matches = []

        if matches:
            media.thumb_file = matches[0]

            if len(matches) == 1:  # more checks here on size, or set saved on media
                lo.d(f'{media.thumb_file} already saved, skipping.')
            else:
                lo.w(f'Found multiple files for {shortcode}: {", ".join(matches)}. Using {media.thumb_file}.')

        else:
            lo.d(f'Retrieving thumbnail for {shortcode}...')

            img_data = self.safe_get(media.thumbnail_src, secs=SLEEP_DELAY_IMG)
            if img_data is None:
                #lo.w(f'Could not fetch {media.thumbnail_src}')
                return

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
            return

        if is_json:
            return resp.json()
        else:
            return resp.text  # todo: json?

    def auth(self):
        self.session.headers.update({'Referer': BASE_URL, 'user-agent': STORIES_UA})
        req = self.safe_get(BASE_URL)

        if req:
            self.session.headers.update({'X-CSRFToken': req.cookies['csrftoken']})
            self.session.headers.update({'user-agent': USER_AGENT})

            self.rhx_gis = ''
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
            lo.w(f'Could not find pickle for {filepath}')
            return

        with open(filepath, 'rb') as f:
            return pickle.load(f)

    def get_shared_data(self, data: str):
        if '_sharedData' in data:
            try:
                shared_data = data.split("window._sharedData = ")[1].split(";</script>")[0]
                data_json = json.loads(shared_data)
                self.rhx_gis = ''
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

    def get_media(self, data: dict, first: bool = False):
        if not data:
            return

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

        ret = {
            'count': count,
            'has_next_page': has_next_page,
            'end_cursor': end_cursor
        }

        if first:
            return ret

        media_list: List[Media] = []

        for edge in edges:
            node = edge.get('node', {})

            fn = node.get('shortcode', '_none')
            if fn != '_none':
                fn = 'm_' + fn

            self.to_pickle(node, fn)

            info = self.convert_node(node)

            media_list.append(info)

        ret['media_list'] = media_list

        return ret

    def save_cookies(self):
        if self.cookiejar:
            with open(self.cookiejar, 'wb') as f:
                pickle.dump(self.session.cookies, f)

    def update_ig_gis_header(self, params):
        data = self.rhx_gis + ":" + params
        ig_gis = hashlib.md5(data.encode()).hexdigest()
        self.session.headers.update({'x-instagram-gis': ig_gis})

    def get_gql(self, qid, end_cursor):
        if end_cursor is None:
            params = GQL_VARS_FIRST.format(qid)
        else:
            params = GQL_VARS.format(qid, end_cursor)

        self.update_ig_gis_header(params)

        resp = self.get_txt(GQL_URL.format(params), is_json=True)
        if not resp:
            data = {}
        else:
            data = resp['data']['user']

        return self.get_media(data)

    def fetch_profile(self):
        lo.i('Parsing profile...')
        url = BASE_URL + self.user + '/'

        resp = self.get_txt(url)
        #if resp is None:
        #    lo.e('Could not fetch profile')
        return resp

    def fetch_media(self, profile_id: str, max_pages: int, page_data: dict):
        first_page_data = self.get_media(page_data, first=True)

        total_items = first_page_data['count']
        has_next = first_page_data['has_next_page']
        end_cursor = None

        lo.i(f'{total_items:,} total items')

        actual_pages = math.ceil(total_items / 50)
        if actual_pages < max_pages:
            lo.w(f'Lowering total pages from {max_pages} to {actual_pages}')
            max_pages = actual_pages

        all_media: List[Media] = []
        pnum = 1

        # do max items instead? or always 50, but 12 on first page
        while pnum <= max_pages:
            if not has_next:
                lo.w('No more entries.')
                break

            lo.i(f'Parsing page {pnum} of {max_pages}...')

            gql_data = self.get_gql(profile_id, end_cursor)
            if not gql_data:
                lo.w('No GQL data.')
                break

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

        # todo technically wrong if max images too high, past last page
        #   also if max imgs is 250, request 10 then 11, skips
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

    def gen_html(self, _prof: dict, media_sort: List[Media], rows, size, template_name = HTML_TEMPLATE):
        lo.i('Creating html...')

        env = self.jinja_env
        template = env.get_template(f'{template_name}.html')
        re_html = re.compile(r'^{}'.format(HTML_DIR))

        if size == 'sm':
            #TODO this depends on screen resolution
            max_items = rows * 7  # 5 for 1080p
        else:
            max_items = rows * 5  # 4 for 1080p
            if size != 'md':
                lo.e('Invalid size, using "md"')

        all_data = []
        for m in media_sort:
            str_date = datetime.utcfromtimestamp(m.taken_at_timestamp).strftime('%b %d, %y')

            if m.thumb_file:
                thumb_url = re_html.sub('', m.thumb_file)
            else:
                thumb_url = m.thumbnail_src

            # TODO hide if cant find this link
            if m.is_video:
                display_url = m.video_url
            else:
                display_url = m.display_url

            caption = '<br />'.join(
                cap.strip()[:max(0, MAX_CAPTION - 3)] + ' [...]' if len(cap.strip()) > MAX_CAPTION else cap.strip()
                for cap in m.captions
            )

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

        if not all_data:
            lo.w('No media to display.')
        else:
            return template.render(
                all_data=all_data, user=self.user, max_items=max_items, grid_type=size
            )



def main(
    username: List[str], overwrite: bool, no_save_imgs: bool, max_pages: int, max_images: int, rows: int, size: str, log_level: str, **_kw):

    #todo allow int
    log_level = log_level.upper()
    if log_level != DEFAULT_LOGLEVEL:
        lo.set_level(log_level)

    scraper = InstaGet(cookiejar=COOKIE_NAME)

    for user in username:
        lo.s(f'Running for {user}')
        scraper.user = user

        total_possible_imgs = max_pages * 50
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
            to_save: List[Media] = []
            for m in media_sort:
                shortcode = m.shortcode
                fmatch = glob(THUMB_DIR + shortcode + '.*')
                if not fmatch:
                    to_save.append(m)
                else:
                    m.thumb_file = fmatch[0]

            if not to_save:
                lo.i('No new images to save')
            else:
                lo.i(f'Saving images ({len(to_save)})...')

                for m in to_save:
                    # TODO print stdout
                    scraper.save_media(m)

        html = scraper.gen_html(prof, media_sort, rows, size)

        if html:
            filename = HTML_DIR + user + '.html'
            with open(filename, 'w') as f:
                f.writelines(html)
                lo.s(f'Wrote file: http://127.0.0.1:9999/{user}.html')
                lo.i('(make sure python is running with: cd ~/dev/instagram/html && python -m http.server 9999 --bind 127.0.0.1')

    lo.s('Done')

if __name__ == '__main__':
    dargs = vars(ARGS)
    main(**dargs)
