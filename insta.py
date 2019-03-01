#!/usr/bin/env python3

import hashlib
import json
import os
import pickle
import sys
import time
from datetime import datetime
from pprint import pformat
from typing import Dict, List, Union
from mimetypes import guess_extension
from glob import glob
import re

import requests
from utils.logs import log_init

lo = log_init('DEBUG')

# todo: save data as pickle and load
# todo: lazyload images

# - Vars

MAX_PAGES = 2
MAX_IMGS = 5

# -

SLEEP_DELAY = 1
CONNECT_TIMEOUT = 3
MAX_RETRIES = 5
RETRY_DELAY = 2

BASE_URL = 'https://www.instagram.com/'
GQL_URL = BASE_URL + 'graphql/query/?query_hash=f2405b236d85e8296cf30347c9f08c2a&variables={}'
GQL_VARS = '{{"id":"{0}","first":50,"after":"{1}"}}'

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/67.0.3396.87 Safari/537.36'

COOKIE_NAME = 'cookies'

SAVE_THUMBS = True
HTML_DIR = 'html/'
IMGS_DIRNAME = 'imgs/'
THUMB_DIRNAME = 'thumbs/'
IMGS_DIR = HTML_DIR + IMGS_DIRNAME
THUMB_DIR = IMGS_DIR + THUMB_DIRNAME


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

    def _sleep(self, secs: int = None):
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

    def safe_get(self, url: str, stream: bool = False):
        tries = 0
        retry_delay = RETRY_DELAY

        while tries <= MAX_RETRIES:
            self._sleep()

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

            img_data = self.safe_get(media.thumbnail_src)

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
    def get_media(data: dict):
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

        media_list = []

        for edge in edges:
            node = edge.get('node')

            info = {
                k: node.get(k) for k in
                ('id', 'shortcode', 'display_url', 'thumbnail_src', 'is_video', 'video_url', 'video_view_count',
                 'accessibility_caption', 'comments_disabled', 'dimensions', 'location', 'taken_at_timestamp')
            }

            info['likes'] = node.get('edge_media_preview_like', {}).get('count')
            info['comments'] = node.get('edge_media_to_comment', {}).get('count')

            # todo: is this ever more than 1?
            #       combine to comprehension
            info['captions'] = []
            for caption in node.get('edge_media_to_caption', {}).get('edges', []):
                cap_txt = caption.get('node', {}).get('text')
                if cap_txt is not None:
                    info['captions'].append(cap_txt)

            media_list.append(Media(**info))

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


    def scrape(self, username):
        lo.i('Authing...')

        self.auth()
        if not self.is_authed:
            return

        lo.i('Parsing profile...')

        url = BASE_URL + username
        resp = self.get_txt(url)
        if resp is None:
            return

        shared_data = self.get_shared_data(resp)

        page_data = self.get_page_data(shared_data)
        if not isinstance(page_data, dict):
            return

        profile_data = {
            k: page_data.get(k) for k in
            ('biography', 'full_name', 'id', 'profile_pic_url_hd')
        }
        profile_data['followers'] = page_data.get('edge_followed_by', {}).get('count')

        lo.v('\n' + pformat(profile_data, indent=4))

        lo.i('Parsing page 1...')

        first_page_data = self.get_media(page_data)

        #lo.v('\n' + pformat(first_page_data, indent=4))

        all_media = first_page_data['media_list']

        profile_id = profile_data['id']

        has_next = first_page_data['has_next_page']
        end_cursor = first_page_data['end_cursor']

        pnum = 2

        while pnum <= MAX_PAGES:  # do max items instead? or always 50
            if not has_next:
                lo.w('No more entries.')
                return

            lo.i(f'Parsing page {pnum}...')

            gql_data = self.get_gql(profile_id, end_cursor)

            #lo.v('\n' + pformat(gql_data, indent=4))

            all_media += gql_data['media_list']

            has_next = gql_data['has_next_page']
            end_cursor = gql_data['end_cursor']

            pnum += 1

        lo.i('Done parsing')

        return profile_data, all_media


    @staticmethod
    def gen_html(prof: dict, media_sort: List[Media]):
        #todo move to jinja

        lo.i('Creating html...')

        re_html = re.compile(r'^{}'.format(HTML_DIR))

        header = '''<html><head>
<style>
    div.cont { display: inline-flex; width: 24%; position: relative; justify-content: center; margin-bottom: 15px; padding: 0 5px; }
    div.img { position: relative; }
    div.img:hover .hidden { opacity: 1; transition-delay: 0.3s; }
    img { max-width: 100%; max-height: 490px; width: auto; height: auto; }
    .hidden { transition: opacity 200ms ease-out; transition-delay: 0s; opacity: 0; filter: blur(0); }
    div.txt { display: none; }
    span.likes, .lum-lightbox-caption, .datedown span { color: white; font: bold 22px Helvetica, Sans-Serif; background: rgba(0, 0, 0, 0.6); padding: 8px; overflow-wrap: break-word;  -webkit-font-smoothing: antialiased; }
    span.likes { position: absolute; bottom: 0px; left: 0; display: block; }
    .lum-lightbox-caption { margin: 8px 150px; }
    div.datedown { position: absolute; bottom: 0px; right: 0; }
    div.datedown span { display: inline-block; }
    div.datedown span.ico { font-size: 27px; line-height: 23px; padding: 10px 12px; text-shadow: #000 0px 0px 4px; cursor: pointer; }
    span.dates { font-size: 18px; padding-top: 11px; padding-bottom: 11px; }
    [data-icon]:before { font-family: Segoe UI Symbol; vertical-align: text-bottom; content: attr(data-icon); }
    .lum-lightbox-inner { background-color: rgba(0,0,0,0.6); }
    .lum-lightbox-inner img { height: calc(100% - 3em + 32px); }
    .lum-lightbox-caption { text-shadow: -1px -1px 3px #000, 1px -1px 3px #000, -1px 1px 3px #000, 1px 1px 3px #000; }
</style>

<script>
    function forceDownload(blob, filename) {
        var a = document.createElement('a');
        a.download = filename;
        a.href = blob;
        // For Firefox https://stackoverflow.com/a/32226068
        document.body.appendChild(a);
        a.click();
        a.remove();
    }
    
    // Current blob size limit is around 500MB for browsers
    function downloadResource(url, filename) {
        if (!filename) filename = url.split('\\\\').pop().split('/').pop().split('?')[0];
        fetch(url, {
            headers: new Headers({
                'Origin': location.origin
            }),
            mode: 'cors'
        })
        .then(response => response.blob())
        .then(blob => {
            let blobUrl = window.URL.createObjectURL(blob);
            forceDownload(blobUrl, filename);
        })
        .catch(e => console.error(e));
    }
</script>
</head>
<body>'''

        footer = '''
    <script type="text/javascript" src="https://cdnjs.cloudflare.com/ajax/libs/luminous-lightbox/1.0.1/Luminous.min.js"></script>
    <script>
        var cap_fn = function(trigger) { return trigger.querySelector('div.txt').innerText; };
        var opt = { openTrigger: 'click', closeTrigger: 'click', caption: cap_fn };
        for (var a of document.querySelectorAll('a.zimg')) {
            new Luminous(a, opt);
        }
    </script>
</body>
</html>'''

        body = ''
        for m in media_sort:
            str_date = datetime.utcfromtimestamp(m.taken_at_timestamp).strftime('%b %d, %y')

            if m.thumb_file:
                thumb_url = re_html.sub('', m.thumb_file)
            else:
                thumb_url = m.thumbnail_src

            caption = '<br /'.join(m.captions)

            # todo add more data
            #      handle video

            media_html = '''
    <div class="cont">
        <div class="img">
            <a class="zimg" href="{big_url}">
                <img src="{small_url}" />
                <div class="txt hidden">{caption}</div>
            </a>
            <span class="likes">{likes:,}</span>
            <div class="datedown hidden">
                <span class="dates">{date}</span>
                <a target="_blank" href="{big_url}">
                    <span data-icon="&#127758;" class="ico" />
                </a>
                <span data-icon="&#128190;" class="ico" onclick="downloadResource('{save_url}')"/>
            </div>
        </div>
    </div>'''.format(
                big_url = m.display_url,
                save_url = m.display_url,
                small_url = thumb_url,
                caption = caption,
                likes = m.likes,
                date = str_date,
            )

            body += media_html

        return header + body + footer


def main():
    scraper = InstaGet(cookiejar=COOKIE_NAME)

    user = sys.argv[1]

    data = scraper.scrape(user)
    scraper.save_cookies()

    if data is not None:
        prof, media = data

        media_sort = sorted(media, key=lambda x: x.likes, reverse=True)
        if MAX_IMGS is not None:
            media_sort = media_sort[:MAX_IMGS]

        if SAVE_THUMBS:
            lo.i(f'Saving images ({len(media_sort)})...')
            for m in media_sort:
                scraper.save_media(m)

        html = scraper.gen_html(prof, media_sort)

        filename = HTML_DIR + user + '.html'
        with open(filename, 'w') as f:
            f.writelines(html)
            lo.s(f'Wrote to {filename}')

    lo.s('Done')

if __name__ == '__main__':
    main()
