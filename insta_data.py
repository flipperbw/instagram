#!/usr/bin/env python
# coding: utf-8

import json
import requests
from time import sleep
import sys
from datetime import datetime
import pytz
#import re
#import string

if len(sys.argv) < 2:
    print 'input insta name'
    sys.exit()

name = sys.argv[1]

base_url = 'https://www.instagram.com'

#valid_letters = re.compile(r'[^{}]'.format(string.punctuation + string.digits + string.letters + ' '))
local_tz = pytz.timezone('America/New_York')

maxim = 199
if len(sys.argv) > 2:
    maxim = int(sys.argv[2])

more = True
maxid = None

i = 0

#print 'now|uploaded|likes|is_vid|code|caption|url'

while more and i < maxim:
    url = '{}/{}/?__a=1'.format(base_url, name)
    if maxid:
        url += '&max_id={}'.format(maxid)
    
    i += 1

    q = requests.get(url)
    if q.status_code != 200:
        sleep(1)
        continue

    try:
        u = q.json().get('user', {}).get('media')
    except:
        sleep(1)
        continue

    p = u.get('page_info')
    maxid = p.get('end_cursor')
    more = p.get('has_next_page')

    now_time = datetime.now(pytz.utc).astimezone(local_tz).strftime('%Y-%m-%d %H:%M:%S')
    
    n = u.get('nodes')
    
    for nn in n:
        li = nn.get('likes', {}).get('count')
        #im = nn.get('display_src')
        is_vid = nn.get('is_video')
        #ca = nn.get('caption', '').encode('utf-8')
        code = nn.get('code', '')
        da = nn.get('date')
        
        #ca_safe = valid_letters.sub('_', ca)

        date_fmt = datetime.utcfromtimestamp(da).replace(tzinfo=pytz.utc).astimezone(local_tz).strftime('%Y-%m-%d %H:%M:%S')
        
        #print '{}|{}|{}|{}|{}|{}|{}'.format(now_time, date_fmt, li, is_vid, code, ca_safe, im)
        print '{}|{}|{}|{}|{}'.format(now_time, date_fmt, li, is_vid, code)
        
    sleep(1)

