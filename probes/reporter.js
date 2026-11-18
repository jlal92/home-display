/* Tiny on-page error reporter. ES5 only. Same-origin GET /report?... (no POST, no fetch).
   Shows the last error as a red bar and tries to log it to the server. */
(function () {
  function show(msg) {
    try {
      var d = document.getElementById('__err');
      if (!d) {
        d = document.createElement('div');
        d.id = '__err';
        d.style.cssText = 'position:fixed;left:0;right:0;bottom:0;background:#b00;color:#fff;font:16px monospace;padding:8px;z-index:9999';
        (document.body || document.documentElement).appendChild(d);
      }
      d.appendChild(document.createTextNode(msg + ' | '));
    } catch (e) {}
  }
  function send(msg) {
    try {
      var x = new XMLHttpRequest();
      x.open('GET', 'report?m=' + encodeURIComponent(msg.slice(0, 500)) + '&p=' + encodeURIComponent(location.pathname), true);
      x.send();
    } catch (e) {}
  }
  window.onerror = function (message, source, line, col) {
    var m = message + ' @' + (source || '').split('/').pop() + ':' + line + ':' + col;
    show(m);
    send(m);
  };
})();
