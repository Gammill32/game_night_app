// gallery.js — tap a photo to enlarge it; arrows / swipe / keys move through them.
(function () {
  'use strict';
  var dialog = document.getElementById('lightbox');
  var items = Array.prototype.slice.call(document.querySelectorAll('[data-photo]'));
  if (!dialog || !items.length) return;
  var img = dialog.querySelector('[data-lightbox-img]');
  var cap = dialog.querySelector('[data-lightbox-caption]');
  var index = 0, startX = null;

  function show(i) {
    index = (i + items.length) % items.length;
    var el = items[index];
    img.src = el.dataset.photo;
    img.alt = el.dataset.caption || 'Photo from the night';
    var bits = [el.dataset.caption, el.dataset.by ? 'Added by ' + el.dataset.by : ''].filter(Boolean);
    cap.textContent = bits.join(' · ') + '  (' + (index + 1) + ' of ' + items.length + ')';
    dialog.querySelector('[data-lightbox-prev]').hidden = items.length < 2;
    dialog.querySelector('[data-lightbox-next]').hidden = items.length < 2;
    if (!dialog.open) dialog.showModal();
  }
  items.forEach(function (el, i) { el.addEventListener('click', function () { show(i); }); });
  dialog.querySelector('[data-lightbox-close]').addEventListener('click', function () { dialog.close(); });
  dialog.querySelector('[data-lightbox-prev]').addEventListener('click', function () { show(index - 1); });
  dialog.querySelector('[data-lightbox-next]').addEventListener('click', function () { show(index + 1); });
  dialog.addEventListener('click', function (e) { if (e.target === dialog) dialog.close(); });
  dialog.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowLeft') show(index - 1);
    if (e.key === 'ArrowRight') show(index + 1);
  });
  dialog.addEventListener('touchstart', function (e) { startX = e.touches[0].clientX; }, { passive: true });
  dialog.addEventListener('touchend', function (e) {
    if (startX === null) return;
    var dx = e.changedTouches[0].clientX - startX;
    if (Math.abs(dx) > 50) show(index + (dx < 0 ? 1 : -1));
    startX = null;
  });
})();
