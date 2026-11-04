/* A small rich text box for the Item editor (docs/DESIGN.md section 5.5, decision M3-17).
   Only bold, italic, underline, paragraphs and line breaks. Buttons and Ctrl/Cmd+B, I, U.
   Pasted text (from Word or a web page) is cleaned down to those tags before it goes in.
   The cleaned HTML is written to the textarea that sits in the same .rt box, and that textarea is
   what the form posts. The server cleans it again (diary/richtext.py); it is the authority.
   Without this script the textarea stays visible and takes HTML. No library. */
(function () {
  "use strict";

  var DROP = { SCRIPT: 1, STYLE: 1, HEAD: 1, TITLE: 1, TEMPLATE: 1, META: 1, LINK: 1, NOSCRIPT: 1 };
  var BLOCK = {
    P: 1, DIV: 1, LI: 1, UL: 1, OL: 1, H1: 1, H2: 1, H3: 1, H4: 1, H5: 1, H6: 1, BLOCKQUOTE: 1, PRE: 1,
    TABLE: 1, TR: 1, TD: 1, TH: 1, SECTION: 1, ARTICLE: 1, HEADER: 1, FOOTER: 1
  };

  function esc(text) {
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  /* Which of b, i, u an element stands for: by tag, and for spans by their style. */
  function marksOf(el) {
    var tag = el.tagName, marks = [];
    if (tag === "B" || tag === "STRONG") { marks.push("b"); }
    if (tag === "I" || tag === "EM") { marks.push("i"); }
    if (tag === "U") { marks.push("u"); }
    var style = el.getAttribute("style") || "";
    if (style && !/^H[1-6]$/.test(tag)) {
      var weight = /font-weight\s*:\s*(bold|bolder|[6-9]00)/i.test(style);
      if (weight && marks.indexOf("b") < 0) { marks.push("b"); }
      if (/font-style\s*:\s*(italic|oblique)/i.test(style) && marks.indexOf("i") < 0) { marks.push("i"); }
      if (/text-decoration[a-z-]*\s*:[^;]*underline/i.test(style) && marks.indexOf("u") < 0) { marks.push("u"); }
    }
    return marks;
  }

  /* HTML (a string) or a DOM node cleaned to p, br, b, i, u. */
  function clean(source) {
    var root = source;
    if (typeof source === "string") {
      root = document.createElement("div");
      var doc = new DOMParser().parseFromString(source, "text/html");
      root.innerHTML = "";
      Array.prototype.slice.call(doc.body.childNodes).forEach(function (n) { root.appendChild(document.importNode(n, true)); });
    }
    var out = [], buf = [], open = [];

    function flush() {
      var closing = open.slice().reverse().map(function (t) { return "</" + t + ">"; }).join("");
      var html = buf.join("") + closing;
      var text = html.replace(/<[^>]+>/g, "").replace(/&nbsp;/g, " ").trim();
      if (text) {
        html = html.replace(/^(<br>)+/, "").replace(/(<br>)+((<\/[biu]>)*)$/, "$2");
        out.push("<p>" + html + "</p>");
      }
      buf = open.map(function (t) { return "<" + t + ">"; });
    }

    function walk(node) {
      if (node.nodeType === 3) {
        buf.push(esc(node.nodeValue.replace(/\u00a0/g, " ").replace(/[ \t\r\n]+/g, " ")));
        return;
      }
      if (node.nodeType !== 1 || DROP[node.tagName]) { return; }
      if (node.tagName === "BR") { buf.push("<br>"); return; }
      var block = !!BLOCK[node.tagName];
      var marks = marksOf(node);
      if (block) { flush(); }
      marks.forEach(function (t) { buf.push("<" + t + ">"); open.push(t); });
      Array.prototype.forEach.call(node.childNodes, walk);
      marks.slice().reverse().forEach(function (t) { buf.push("</" + t + ">"); open.pop(); });
      if (block) { flush(); }
    }

    Array.prototype.forEach.call(root.childNodes, walk);
    flush();
    var html = out.join("");
    var before;
    do { before = html; html = html.replace(/<(b|i|u)><\/\1>/g, ""); } while (html !== before);
    return html;
  }

  function plainToHtml(text) {
    return text.replace(/\r\n?/g, "\n").split(/\n{2,}/).map(function (para) {
      return para.trim() ? "<p>" + esc(para.trim()).replace(/\n/g, "<br>") + "</p>" : "";
    }).join("");
  }

  var COMMANDS = [
    { cmd: "bold", label: "B", name: "Bold", key: "b", tag: "b" },
    { cmd: "italic", label: "I", name: "Italic", key: "i", tag: "i" },
    { cmd: "underline", label: "U", name: "Underline", key: "u", tag: "u" }
  ];

  function init(box) {
    if (box.getAttribute("data-rt-ready")) { return; }
    var source = box.querySelector("textarea");
    if (!source || !document.execCommand) { return; }
    box.setAttribute("data-rt-ready", "1");

    var bar = document.createElement("div");
    bar.className = "rt-toolbar";
    bar.setAttribute("role", "toolbar");
    bar.setAttribute("aria-label", "Formatting");
    var area = document.createElement("div");
    area.className = "rt-area";
    area.contentEditable = "true";
    area.setAttribute("role", "textbox");
    area.setAttribute("aria-multiline", "true");
    area.setAttribute("aria-label", source.getAttribute("aria-label") || "Text");
    area.innerHTML = clean(source.value);
    // The grey hint (round 16): the textarea's placeholder, shown inside the box whenever it holds no text.
    var hint = source.getAttribute("placeholder") || "";
    if (hint) { area.setAttribute("data-placeholder", hint); area.setAttribute("aria-placeholder", hint); }
    area.style.minHeight = (Number(source.getAttribute("rows")) || 3) * 1.5 + "em";

    var buttons = {};
    COMMANDS.forEach(function (c) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "rt-btn";
      b.setAttribute("aria-label", c.name);
      b.setAttribute("aria-pressed", "false");
      b.setAttribute("aria-keyshortcuts", "Control+" + c.key.toUpperCase());
      b.title = c.name + " (Ctrl+" + c.key.toUpperCase() + ")";
      var face = document.createElement(c.tag);
      face.textContent = c.label;
      b.appendChild(face);
      b.addEventListener("mousedown", function (e) { e.preventDefault(); });
      b.addEventListener("click", function () { area.focus(); run(c); });
      bar.appendChild(b);
      buttons[c.cmd] = b;
    });

    function run(c) {
      document.execCommand(c.cmd, false, null);
      sync();
      state();
    }
    function sync() {
      source.value = clean(area);
      area.classList.toggle("rt-empty", !(area.textContent || "").replace(/\u00a0/g, " ").trim());
    }
    function state() {
      COMMANDS.forEach(function (c) {
        var on = false;
        try { on = document.queryCommandState(c.cmd); } catch (e) { on = false; }
        buttons[c.cmd].setAttribute("aria-pressed", on ? "true" : "false");
      });
    }

    area.addEventListener("input", sync);
    area.addEventListener("blur", sync);
    area.addEventListener("keyup", state);
    area.addEventListener("mouseup", state);
    area.addEventListener("keydown", function (e) {
      if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey) { return; }
      var key = (e.key || "").toLowerCase();
      COMMANDS.forEach(function (c) {
        if (c.key === key) { e.preventDefault(); run(c); }
      });
    });
    area.addEventListener("paste", function (e) {
      var data = e.clipboardData;
      if (!data) { return; }
      e.preventDefault();
      var html = data.getData("text/html");
      var cleaned = html ? clean(html) : plainToHtml(data.getData("text/plain") || "");
      if (cleaned) { document.execCommand("insertHTML", false, cleaned); }
      sync();
    });
    area.addEventListener("drop", function (e) { e.preventDefault(); });

    try { document.execCommand("defaultParagraphSeparator", false, "p"); } catch (e) { /* older browsers */ }
    source.hidden = true;
    box.insertBefore(bar, source);
    box.insertBefore(area, source);
    sync();

    /* Lets other scripts (the Add form) put HTML into the box, and read it back as plain text. */
    box.rtApi = {
      setHtml: function (html) { area.innerHTML = clean(html); sync(); },
      getPlain: function () { return (area.innerText || area.textContent || "").replace(/\s+/g, " ").trim(); }
    };

    var form = box.closest("form");
    if (form) { form.addEventListener("submit", sync, true); }
  }

  function initAll(scope) {
    Array.prototype.forEach.call((scope || document).querySelectorAll("[data-richtext]"), init);
  }

  window.QuillRichText = { init: init, initAll: initAll, clean: clean };
  initAll();
})();
