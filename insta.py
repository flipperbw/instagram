#!/usr/bin/env python
# coding: utf-8

import json
import requests
from time import sleep
import sys
from datetime import datetime
import pytz
import re

valid_letters = re.compile(r'[^A-Za-z0-9_-]')

if len(sys.argv) < 2:
    print 'input insta name'
    sys.exit()

name = sys.argv[1]

local_tz = pytz.timezone('America/New_York')
base_url = 'https://www.instagram.com'

#need a check if this is valid or not, could hit p/BddfR7uFate/?__a=1 and get display_resources src
magic_repl = '/s640x640/sh0.08/'
magic_tried = False
magic_valid = False

maxim = 199
if len(sys.argv) > 2:
    maxim = int(sys.argv[2])

more = True
maxid = None

l = []

i = 0

while more and i < maxim:
    print 'Page {}'.format(i + 1)
    url = '{}/{}/?__a=1'.format(base_url, name)
    if maxid:
        url += '&max_id={}'.format(maxid)
    
    q = requests.get(url)

    u = q.json().get('user', {}).get('media')

    p = u.get('page_info')
    maxid = p.get('end_cursor')
    i += 1
    more = p.get('has_next_page')

    n = u.get('nodes')

    for nn in n:
        li = nn.get('likes', {}).get('count')
        im = nn.get('display_src')
        is_vid = nn.get('is_video')
        ca = nn.get('caption', '').encode('utf-8')
        code = nn.get('code', '')
        da = nn.get('date')
        
        l.append((li, im, is_vid, ca, code, da))

    sleep(0.3)

s = sorted(l, key=lambda (x,y,a,b,c,d):(-x,y,a,b,c,d))

print '==================================================================='
print """
<html><head><style>
    div.cont { display: inline-flex; width: 24%; position: relative; justify-content: center; margin-bottom: 15px; padding: 0 5px; }
    div.img { position: relative; }
    div.img:hover .hidden { opacity: 1; transition-delay: 0.3s; }
    img { max-width: 100%; max-height: 490px; width: auto; height: auto; }
    .hidden { transition: opacity 200ms ease-out; transition-delay: 0s; opacity: 0; filter: blur(0); }
    div.txt { display: none; }
    span { color: white; font: bold 22px Helvetica, Sans-Serif; background: rgba(0, 0, 0, 0.5); padding: 8px; overflow-wrap: break-word; display: block; -webkit-font-smoothing: antialiased; }
    span.likes { position: absolute; bottom: 0px; left: 0; }
    div.datedown { position: absolute; bottom: 0px; right: 0; }
    div.datedown span { display: inline-block; }
    div.datedown span.ico { font-size: 27px; line-height: 23px; padding: 10px 12px; text-shadow: #000 0px 0px 4px; }
    span.dates { font-size: 18px; padding-top: 11px; padding-bottom: 11px; }
    [data-icon]:before { font-family: Segoe UI Symbol; vertical-align: text-bottom; content: attr(data-icon); }
    .lum-lightbox-inner img { height: calc(100% - 3em + 16px); }
    .lum-lightbox-caption { text-shadow: -1px -1px 3px #000, 1px -1px 3px #000, -1px 1px 3px #000, 1px 1px 3px #000; }
</style></head>
<body>"""


for i in s:
    num_likes = i[0]
    img_url   = i[1]
    is_vid    = i[2]
    caption   = i[3]
    code      = i[4]
    date_int  = i[5]
    
    fmt = img_url.split('.')[-1]
    
    if fmt not in ('jpg', 'jpeg', 'png', 'bmp', 'tiff'):
        print '-> Not a valid image file: "{}"'.format(fmt)
    else:
        link = '{}/p/{}'.format(base_url, code)
        like_txt = '{}'.format(num_likes)

        click_open     = '<a target="_blank" href="{}">'.format(link)
        click_download = '<a download href="{}">'.format(img_url)

        view_url = img_url.replace('/e35/', magic_repl + 'e35/').replace('/e15/', magic_repl + 'e15/')
        
        if not magic_tried:
            m = requests.get(view_url).status_code
            if m == 200:
                magic_valid = True
            magic_tried = True

        if not magic_valid:
            view_url = img_url

        if is_vid == True:
            like_txt += ' [vid]'
            img_click = click_open
            btn_click = click_download
            ico = '&#128190;'
        else:
            img_click = click_download
            btn_click = click_open
            ico = '&#127758;'

        img_click = img_click.replace('<a ', '<a class="zimg" ')

        if type(date_int) != int:
            date_fmt = '-'
            #date_safe = 'no-date'
        else:
            date_loc = datetime.utcfromtimestamp(date_int).replace(tzinfo=pytz.utc).astimezone(local_tz)
            date_fmt = date_loc.strftime('%b %d, %y')
            #date_safe = date_loc.strftime('%m-%d-%y')
        
        #doesnt work from different origin
        #name_safe = valid_letters.sub('', name)
        #filename = 'insta_{}_{}_{}.{}'.format(name_safe, date_safe, code, fmt)

        #why does this make so many a hrefs in pratice? competing?

        cont_div = '<div class="cont"><div class="img">{}<img src="{}"><div class="txt hidden">{}</div></a><span class="likes">{}</span><div class="datedown hidden"><span class="dates">{}</span>{}<span data-icon="{}" class="ico"></span></a></div></div></div>'
        
        print cont_div.encode('utf-8').format(img_click, view_url, caption, like_txt, date_fmt, btn_click, ico)

        #print '{}|{}|{}|{}'.format(date_fmt, num_likes, is_vid, img_url)

print '<script type="text/javascript" src="https://cdnjs.cloudflare.com/ajax/libs/luminous-lightbox/1.0.1/Luminous.min.js"></script>'
print '''<script>
  var cap_fn = function(trigger) { return trigger.querySelector('div.txt').innerText; };
  var opt = { openTrigger: 'contextmenu', closeTrigger: 'contextmenu', caption: cap_fn };
  for (var a of document.querySelectorAll('a.zimg')) {
    new Luminous(a, opt);
  }
</script>'''
print '</body></html>'

