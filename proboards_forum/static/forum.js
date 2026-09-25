// BBCode toolbar buttons and small conveniences. Everything works without
// JavaScript; this only adds shortcuts.
(function () {
  "use strict";

  function wrap(textarea, open, close) {
    var start = textarea.selectionStart;
    var end = textarea.selectionEnd;
    var value = textarea.value;
    var selected = value.slice(start, end);
    textarea.value = value.slice(0, start) + open + selected + close +
      value.slice(end);
    textarea.focus();
    var cursor = selected ? start + open.length + selected.length + close.length
      : start + open.length;
    textarea.setSelectionRange(cursor, cursor);
  }

  document.querySelectorAll(".bbcode-toolbar").forEach(function (toolbar) {
    var textarea = document.getElementById(toolbar.dataset.target);
    toolbar.addEventListener("click", function (event) {
      var button = event.target.closest("button[data-open]");
      if (!button) return;
      event.preventDefault();
      var open = button.dataset.open;
      var close = button.dataset.close || "";
      if (button.dataset.prompt) {
        var value = window.prompt(button.dataset.prompt, "https://");
        if (!value) return;
        open = open.replace("{}", value);
      }
      wrap(textarea, open, close);
    });
  });

  // Confirm destructive actions.
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  // Keep the shoutbox scrolled to the newest message.
  var shouts = document.querySelector("#shoutbox .shouts");
  if (shouts) shouts.scrollTop = shouts.scrollHeight;
})();
