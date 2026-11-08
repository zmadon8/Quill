# Investments program: page mockups

Static HTML and CSS pages in the suite's "Chambers" design, one for each page of the planned Investments program. **All people, holdings, prices and amounts are invented. Nothing here saves anything.** The written specification is `../INVESTMENTS_PLAN.md`.

- Open `index.html` for the list of all 51 pages. The **Auto / Full** control at the top right works on every page (it changes every rupee amount).
- `images/` has a PNG of every page (desktop, 1360 px wide) and 5 phone views (390 px wide, files ending `-phone`). Viewing the PNGs is the easiest way to see the pages without running anything.
- `mockup.css` is the one stylesheet. It uses the suite's tokens from `static/css/tokens.css` unchanged, plus two **proposed** new tokens: gain green `#2d5a3d` and loss brick `#a8441f`.
- `gen/` holds the Python scripts that generate the pages and render the PNGs. They use only the standard library. `python3 gen/build.py` rebuilds the HTML; `CHROME_BIN=/path/to/headless-chrome python3 gen/shoot.py` re-renders the PNGs. Edit the page text in `gen/pages_a.py`, `pages_b.py` and `pages_c.py`, never the generated HTML.
- Screenshots were rendered on a machine without the suite's preferred serif fonts, so headings look sans-serif in the PNGs; in a normal browser on a Mac they use Iowan Old Style or Georgia.
- Each page has a dashed "Mockup note" at the bottom saying what it demonstrates. Those notes are for the reader of the mockup and do not belong in the real program.
