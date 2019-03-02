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

function swap(idx) {
    var sections = document.getElementsByClassName('section');

    var curr_hash = window.location.hash;
    var curr;
    if (!curr_hash) {
        curr = 1;
    }
    else {
        curr = parseInt(curr_hash.split('-')[1]);
        if (curr < 1 || curr > sections.length) {
            curr = 1;
            window.location.hash = '#section-1';
        }
    }

    var dest_id;
    if (!idx || idx === '') {
        dest_id = 1;
    }
    else if (typeof idx === 'string') {
        if (idx.indexOf('#section-') > -1) {
            dest_id = idx.replace('#section-', '');
        }
        else if (idx === 'prev' || idx === 'next') {
            if (idx === 'prev') {
                if (sections.length >= curr && curr > 1) {
                    dest_id = curr - 1;
                }
            }
            else if (idx === 'next') {
                if (1 <= curr && curr < sections.length) {
                    dest_id = curr + 1;
                }
            }
            if (dest_id) window.location.hash = `#section-${dest_id}`;
            window.scrollTo(0, 0);
        }

        dest_id = parseInt(dest_id);
    }
    else {
        dest_id = idx;
    }

    if (!dest_id) {}

    var el_id = `section-${dest_id}`;

    var target = document.getElementById(el_id);
    if (!target) {
        window.location.hash = '';
        target = document.getElementById('section-1');
    }

    for (let el of sections) {
        el.style.display = 'none';
    }

    target.style.display = null;

    for (let idata of target.querySelectorAll('img[data-src]')) {
        idata.onload = function() {
            var parent = this.closest('div.img');
            parent.classList.remove('lum-loading');
            var sibling = this.previousElementSibling;
            if (sibling.classList.contains('lum-lightbox-loader')) {
                sibling.remove();
            }
        };
        idata.src = idata.dataset.src;
        delete idata.dataset.src;
    }

    var li_prev = document.getElementById('goto-prev');
    var li_next = document.getElementById('goto-next');

    if (sections.length <= 1) {
        li_prev.classList.add('disabled');
        li_next.classList.add('disabled');
    }
    else if (dest_id === 1) {
        li_prev.classList.add('disabled');
        li_next.classList.remove('disabled');
    }
    else if (dest_id === sections.length) {
        li_next.classList.add("disabled");
        li_prev.classList.remove('disabled');
    }
    else {
        li_prev.classList.remove('disabled');
        li_next.classList.remove('disabled');
    }

    var all_lis = document.querySelectorAll('#pagination li');
    for (let ali of all_lis) {
        ali.classList.remove('active');
    }
    var li = document.getElementById(`goto-${el_id}`);
    if (li) {
        li.classList.add("active");
    }
}
