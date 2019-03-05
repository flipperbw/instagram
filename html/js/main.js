var urlParams = new URLSearchParams(window.location.search);

var img_as = document.querySelectorAll('a.zimg');
var span_dls = document.querySelectorAll('span.download');
var sections = document.getElementsByClassName('section');
var pag_div = document.getElementById('pagination');
var all_lis = pag_div.getElementsByTagName('li');
var li_prev = document.getElementById('goto-prev');
var li_next = document.getElementById('goto-next');
var pag_lias = pag_div.querySelectorAll('#pagination-compact li a');


function setTitle(dest) {
    document.title = document.title.split(':')[0] + `: Page ${dest}`;
}

function setp(dest) {
    var o_params = urlParams.toString();

    var i = dest;
    if (!i) {
        urlParams.delete('p');
        i = 1;
    }
    else {
        urlParams.set('p', i);
    }

    var n_params = urlParams.toString();
    var s = '';
    if (n_params) {
        s = `?${n_params}`;
    }

    var data = {p: i};

    if (o_params === n_params) {
        history.replaceState(data, '', s);
        return;
    }

    history.pushState(data, '', s);
}

function getp() {
    return urlParams.get('p');
}

function getCurr() {
    var curr_str = getp();
    if (curr_str === null) return 1;

    let curr = parseInt(curr_str);
    if (!curr || curr <= 1 || curr > sections.length) {
        setp(1);
        setTitle(1);
        return 1;
    }

    return curr;
}

function getDest(idx, curr) {
    var idx_typ = typeof idx;

    if (!idx || !['string', 'number'].includes(idx_typ)) {
        return 1;
    }

    if (idx_typ === 'string') {
        if (idx === 'prev') {
            return Math.max(Math.min(curr - 1, sections.length), 1);
        }
        if (idx === 'next') {
            return Math.min(Math.max(curr + 1, 1), sections.length);
        }
        return 1;
    }

    if (idx_typ === 'number') {
        return parseInt(idx);
    }
}

function getSect(idx) {
    var sect = 'section';
    return document.getElementById(`${sect}-${idx}`);
}

function whichTransitionEvent() {
    var el = document.createElement("fakeelement");

    var transitions = {
        "transition"      : "transitionend",
        "OTransition"     : "oTransitionEnd",
        "MozTransition"   : "transitionend",
        "WebkitTransition": "webkitTransitionEnd"
    };

    for (let t in transitions) {
        if (el.style[t] !== undefined) {
            return transitions[t];
        }
    }
}
var transitionEvent = whichTransitionEvent();

function transitionEndCb(evt) {
    var el = evt.target;
    el.classList.remove('hidden');
    el.style.opacity = null;
}

function clearLoading(el) {
    var parent = el.closest('div.img');
    parent.classList.remove('lum-loading');

    var sibling = el.previousElementSibling;
    if (sibling.classList.contains('lum-lightbox-loader')) {
        sibling.remove();
    }
}

function imgLoadCb() {
    this.style.opacity = 1;
    clearLoading(this);
    delete this.dataset.src;
}

function imgErrorCb() {
    //show placeholder
    clearLoading(this);
}

function createEventPromise(el, typ, fnc) {
    return new Promise(function(res, _rej) {
        el.addEventListener(typ, function(evt) {
            fnc.call(this, evt);
            res(el);
        }, {once: true});
    });
}

function loadNext(dest) {
    var next_div = getSect(dest);
    if (!next_div) return;

    var next_datasrc = next_div.querySelectorAll('img[data-src]');

    for (let idata of next_datasrc) {
        idata.addEventListener('error', imgErrorCb, {once: true});
        idata.addEventListener('load', imgLoadCb, {once: true});
        idata.addEventListener(transitionEvent, transitionEndCb, {once: true});

        idata.src = idata.dataset.src;
    }
}

function swap(idx, addHist=true) {
    var dest, dest_div;

    if (addHist === false) {
        for (let sec of sections) {
            sec.style.display = 'none';
        }
        dest = idx;
        dest_div = getSect(dest);
    }
    else {
        var curr = getCurr();
        var curr_div = getSect(curr);
        if (!curr_div) return;


        if (typeof idx === "undefined") {
            dest = curr;
        } else {
            dest = getDest(idx, curr);
        }

        if (dest === curr) {
            dest_div = curr_div;
        }
        else {
            dest_div = getSect(dest);
            if (!dest_div) return;
            curr_div.style.display = 'none';
        }

        setp(dest);
        setTitle(dest);
    }

    window.scrollTo(0, 0);
    dest_div.style.display = null;

    //probably has an issue if navigating too fast
    var target_new = dest_div.querySelectorAll('a.zimg > [data-src]');
    var imgs_new = target_new.length;

    if (imgs_new === 0) {
        loadNext(dest + 1);
    }
    else {
        var target_all = dest_div.querySelectorAll('a.zimg > img, a.zimg > video');
        var imgs_total = target_all.length;
        var imgs_loaded = imgs_total - imgs_new;

        for (let idata of target_new) {
            var promise_error = createEventPromise(idata, 'error', imgErrorCb);
            var promise_load = createEventPromise(idata, 'load', imgLoadCb);
            var promise_trans = createEventPromise(idata, transitionEvent, transitionEndCb);

            promise_error.then(el => {
                imgs_loaded++;
                console.log('error', el);
                if (imgs_loaded === imgs_total) {
                    //this will not load next on error
                    loadNext(dest + 1);
                }
            });
            Promise.all([promise_load, promise_trans]).then(_els => {
                imgs_loaded++;
                if (imgs_loaded === imgs_total) {
                    // is this scope wrong?
                    loadNext(dest + 1);
                }
            });

            idata.src = idata.dataset.src;
        }
    }

    //technically could put this at top
    if (sections.length <= 1) {
        li_prev.classList.add('disabled');
        li_next.classList.add('disabled');
    }
    else if (dest === 1) {
        li_prev.classList.add('disabled');
        li_next.classList.remove('disabled');
    }
    else if (dest === sections.length) {
        li_next.classList.add("disabled");
        li_prev.classList.remove('disabled');
    }
    else {
        li_prev.classList.remove('disabled');
        li_next.classList.remove('disabled');
    }

    for (let ali of all_lis) {
        ali.classList.remove('active');
    }

    var li = document.getElementById(`goto-${dest}`);
    if (li) {
        li.classList.add("active");
    }
}

swap();

for (let lia of pag_lias) {
    let dest = lia.dataset.sectionid;
    let dest_id;
    if (['prev', 'next'].includes(dest)) {
        dest_id = dest;
    }
    else {
        dest_id = parseInt(dest);
    }
    lia.addEventListener("click", function() {
        swap(dest_id);
    });
}

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
    let fname = filename;
    if (!fname) {
        fname = url.split('\\\\').pop().split('/').pop().split('?')[0];
    }

    fetch(url, {
        headers: new Headers({
            'Origin': location.origin
        }),
        mode: 'cors'
    })
    .then(response => response.blob())
    .then(blob => {
        let blobUrl = window.URL.createObjectURL(blob);
        forceDownload(blobUrl, fname);
    })
    .catch(e => console.error(e));
}

var runDownload = function() {
    let url = this.dataset.dlurl;
    if (!url) return;
    downloadResource(url);
};

for (let sp of span_dls) {
    sp.onclick = runDownload;
}

var make_vid = function() {
    var w = document.querySelector('.lum-opening img.lum-img');
    if (!w) return;

    var orig_el = document.querySelector(`a.zimg[href="${w.src}"`);
    if (!orig_el || !orig_el.dataset || !orig_el.dataset.isvid || orig_el.dataset.isvid === "False") return;

    var d = document.createElement('video');

    d.autoplay = true;
    d.controls = true;
    d.loop = true;
    d.muted = true;

    d.src = w.src;
    d.oncanplay = w.onload;
    w.parentNode.replaceChild(d, w);
};

var cap_fn = function(trigger) {
    return trigger.querySelector('div.txt').innerText;
};

var opt = { caption: cap_fn, onOpen: make_vid };

for (let a of img_as) {
    new window.Luminous(a, opt);
}

document.addEventListener("keydown", function (event) {
    if (event.defaultPrevented) return;
    switch (event.key) {
        case "Left":
        case "ArrowLeft":
            swap('prev');
            break;
        case "Right":
        case "ArrowRight":
            swap('next');
            break;
    }
}, true);

window.addEventListener('popstate', function(event) {
  swap(event.state.p, false);
});
