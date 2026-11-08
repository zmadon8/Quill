# ruff: noqa
"""Render every mockup page to a PNG with the sandbox's headless Chrome (height measured per page)."""
import glob, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)) + os.sep
BIN = os.environ.get("CHROME_BIN", "chrome-headless-shell")  # any headless Chrome or Chromium; set CHROME_BIN to its full path
FLAGS = ["--no-sandbox", "--disable-gpu", "--disable-crash-reporter", "--disable-breakpad", "--no-crashpad", "--hide-scrollbars"]
os.makedirs(ROOT + "images", exist_ok=True)


def run(args, timeout=90):
    return subprocess.run([BIN] + FLAGS + args, capture_output=True, text=True, timeout=timeout)


def shoot(name, width=1360, suffix=""):
    src = ROOT + name
    tmp = ROOT + "_m_" + str(width) + "_" + name
    html = open(src, encoding="utf-8").read()
    probe = "<script>window.addEventListener('load',function(){document.title='H='+document.documentElement.scrollHeight})</script></body>"
    open(tmp, "w", encoding="utf-8").write(html.replace("</body>", probe))
    try:
        out = run([f"--user-data-dir=/tmp/cp-{width}-{name}", f"--window-size={width},1000", "--virtual-time-budget=2000", "--dump-dom", "file://" + tmp]).stdout
        m = re.search(r"<title>H=(\d+)</title>", out)
        h = int(m.group(1)) + 4 if m else 2400
        png = ROOT + "images/" + name.replace(".html", suffix + ".png")
        run([f"--user-data-dir=/tmp/cs-{width}-{name}", f"--window-size={width},{h}", f"--screenshot={png}", "file://" + src])
        return name, h, os.path.exists(png)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


if __name__ == "__main__":
    names = sys.argv[1:] or sorted(os.path.basename(p) for p in glob.glob(ROOT + "*.html"))
    width = 1360
    suffix = ""
    if names and names[0].startswith("--w="):
        width = int(names[0][4:])
        suffix = "-phone" if width < 600 else ""
        names = names[1:]
    with ThreadPoolExecutor(4) as ex:
        for n, h, ok in ex.map(lambda n: shoot(n, width, suffix), names):
            print(n, h, "ok" if ok else "FAILED")
