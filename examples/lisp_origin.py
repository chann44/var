"""Create an original, code-led Lisp history short with readable supplied artwork."""

import json
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import studio


SCENES = [
    (4, "BEFORE YOUR AI STARTUP", "LISP", "1958 called.",
     "Before Python, before JavaScript, and before your AI startup, there was Lisp.", []),
    (5, "MIT / JOHN MCCARTHY", "1958", "Make computers handle symbols.",
     "Nineteen fifty-eight. MIT. John McCarthy wants computers to manipulate symbols, not just numbers.",
     ["numbers  ->  symbols", "calculate ->  reason"]),
    (4, "THE NAME", "LIST", "PROCESSING",
     "The name? List processing. The syntax? Parentheses with a programming language attached.",
     ["(and (more (parentheses)))"]),
    (4, "THE BIG IDEA", "CODE", "is data.",
     "Programs became nested lists. The same structure used for data.",
     ["(+ 1 2)", "'(+ 1 2)", ";; expression / list"]),
    (4, "METAPROGRAMMING", "CODE", "can write code.",
     "Now programs can inspect and transform other programs. Yes, code can write code.",
     ["program -> transform -> program"]),
    (5, "OLD LANGUAGE. BIG IDEAS.", "1950s", "Already thinking ahead.",
     "Recursion. Functions as values. Automatic garbage collection. Lisp combined these ideas remarkably early.",
     ["recursion", "functions as values", "garbage collection"]),
    (4, "SYSTEM NOTIFICATION", "GC", "has entered the chat.",
     "Your memory leaks have entered the chat.",
     ["memory_leak: ...", "garbage_collector: hello"]),
    (4, "A LANGUAGE EXPLAINS ITSELF", "eval", "A compact evaluator.",
     "McCarthy described eval: a compact evaluator explaining how the language should run.",
     ["(eval '(+ 1 2))", ";; => 3"]),
    (5, "STEVE RUSSELL", "IDEA", "becomes interpreter.",
     "Steve Russell hand-coded it, turning the description into a working interpreter.",
     ["eval description", "       |", "working interpreter"]),
    (4, "FROM THEORY TO SOFTWARE", "RUN IT", "Math paper, meet machine code.",
     "Math paper, meet machine code. Symbolic computing had a practical new tool.",
     ["theory -> implementation", ";; symbolic computation"]),
    (4, "THE FOUNDATIONAL PAPER", "1960", "A language for early AI.",
     "The foundational paper appeared in nineteen sixty. Lisp became central to early artificial intelligence.",
     ["Recursive Functions of", "Symbolic Expressions...", "Communications of the ACM"]),
    (4, "THE FAMILY TREE", "LISP", "The family keeps growing.",
     "Its family grew into Scheme, Common Lisp, and Clojure.",
     ["Scheme", "Common Lisp", "Clojure"]),
    (4, "THE IDEAS ESCAPED", "STILL", "inside modern languages.",
     "Its influence spread further: lambdas, metaprogramming, and automatic memory management.",
     ["lambda", "metaprogramming", "automatic memory management"]),
    (5, "WELCOME TO THE FUTURE", "1958", "The parentheses were a clue.",
     "So when modern languages brag about those features, Lisp says: welcome to the nineteen fifties.",
     ["((welcome) (to (the future)))"]),
]

SOURCES = """# Sources and historical notes

- [Computer History Museum: 1958](https://www.computerhistory.org/timeline/1958/):
  McCarthy, MIT, 1958, and the name List Processing.
- [McCarthy: History of Lisp, introduction](https://www-formal.stanford.edu/jmc/history/lisp/node1.html):
  symbolic processing, programs as data, functions, recursion, and garbage collection.
- [McCarthy: The implementation of Lisp](https://www-formal.stanford.edu/jmc/history/lisp/node3.html):
  implementation began in fall 1958; eval, Steve Russell's interpreter, and memory management.
- [McCarthy's original paper](https://www-formal.stanford.edu/jmc/recursive.html):
  publication in Communications of the ACM, April 1960.
- [Scheme](https://www.scheme.org/), [Common Lisp](https://lisp-lang.org/),
  [Clojure](https://clojure.org/): present-day Lisp-family context.

The script says Lisp combined ideas early, rather than claiming it invented every
feature. The name and parentheses jokes are original editorial lines. The code
cards use modern Lisp notation for illustration, not replicas of 1958 source.
The graphics are original typography and diagrams, not archival photographs.
"""


def font(size, mono=False):
    filename = "/System/Library/Fonts/Menlo.ttc" if mono else "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
    return ImageFont.truetype(filename, size)


def label(draw, text, x, y, size=22, fill="#ededdf", mono=False, max_width=624):
    face = font(size, mono)
    assert draw.textlength(text, font=face) <= max_width, f"Text does not fit: {text}"
    draw.text((x, y), text, fill=fill, font=face)


def make_card(index, scene, output):
    seconds, eyebrow, headline, subhead, narration, code = scene
    background, ink, accent = "#10141b", "#eeeadd", "#c1f577"
    if index in (2, 11, 14):
        background, ink, accent = "#eeeadd", "#14191f", "#bc3e24"
    image = Image.new("RGB", (720, 1280), background)
    draw = ImageDraw.Draw(image)
    draw.line((48, 116, 672, 116), fill=accent, width=3)
    label(draw, "var / LANGUAGE ORIGINS", 48, 67, 20, ink, mono=True)
    label(draw, f"{index:02} / 14", 547, 67, 20, ink, mono=True, max_width=125)
    label(draw, eyebrow, 48, 166, 21, accent)
    size = 224
    while draw.textlength(headline, font=font(size)) > 624:
        size -= 2
    label(draw, headline, 42, 243, size, ink)
    words, lines, line = subhead.split(), [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=font(42)) > 620 and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    lines.append(line)
    for line_index, line in enumerate(lines):
        label(draw, line, 48, 497 + line_index * 52, 42, ink)
    assert len(lines) <= 2, subhead
    if code:
        panel_y = 680
        panel_height = max(180, len(code) * 49 + 88)
        draw.rounded_rectangle((48, panel_y, 672, panel_y + panel_height), radius=16, fill="#202832")
        for dot, color in enumerate(("#fc735c", "#efc75e", "#8cd891")):
            draw.ellipse((72 + dot * 22, panel_y + 22, 82 + dot * 22, panel_y + 32), fill=color)
        for line_index, line in enumerate(code):
            text_size = 28
            while draw.textlength(line, font=font(text_size, True)) > 570:
                text_size -= 1
            label(draw, line, 72, panel_y + 62 + line_index * 49, text_size,
                  "#c1f577" if line_index == 0 else "#dbe2e8", mono=True, max_width=576)
        assert panel_y + panel_height < 1050
    else:
        label(draw, "(the origin story)", 48, 752, 43, accent, mono=True)
        label(draw, "BEFORE AI WAS COOL.", 48, 849, 28, ink)
    label(draw, "LISP / IN ONE MINUTE", 48, 1094, 20, ink, mono=True)
    draw.rectangle((48, 1146, 672, 1152), fill="#39444a")
    draw.rectangle((48, 1146, 48 + int(624 * index / len(SCENES)), 1152), fill=accent)
    image.save(output)


def main():
    destination = Path(sys.argv[1] if len(sys.argv) > 1 else "projects/lisp-origin")
    if destination.exists():
        raise SystemExit(f"{destination} exists; choose a new folder to preserve existing work.")
    assert sum(scene[0] for scene in SCENES) == 60
    word_count = sum(len(scene[4].split()) for scene in SCENES)
    assert 150 <= word_count <= 200, word_count
    (destination / "images").mkdir(parents=True)
    project = {
        "title": "Lisp: Before AI Was Cool", "voice": "Vivian", "language": "English",
        "speech_model": studio.CHATTERBOX_MODEL, "speech_rate": 1.12,
        "target_duration": 60,
        "style": "Original editorial code graphics, charcoal, warm off-white, acid green and vermilion. Bold type, readable code, hard cuts.",
        "width": 720, "height": 1280, "scenes": [],
    }
    storyboard = ["# Lisp: Before AI Was Cool", "", "Target: 60 seconds, 9:16. Spoken delivery: brisk, curious, dry humor.",
                  "", "Graphics are supplied. Run narrate and assemble, rather than regenerating images.", ""]
    elapsed = 0
    for index, scene in enumerate(SCENES, 1):
        seconds, eyebrow, headline, subhead, narration, code = scene
        identifier = f"{index:02}"
        make_card(index, scene, destination / "images" / (identifier + ".png"))
        project["scenes"].append({"id": identifier, "narration": narration,
            "image_prompt": f"{eyebrow}. {headline}. {subhead}", "seed": 1958 + index, "references": []})
        storyboard += [f"## {elapsed:02}–{elapsed + seconds:02}s / {headline}", "", narration, ""]
        elapsed += seconds
    (destination / "project.json").write_text(json.dumps(project, indent=2) + "\n")
    (destination / "script.txt").write_text("\n\n".join(scene[4] for scene in SCENES) + "\n")
    (destination / "storyboard.md").write_text("\n".join(storyboard))
    (destination / "sources.md").write_text(SOURCES)
    (destination / "README.md").write_text(
        "# Lisp: Before AI Was Cool\n\n"
        "An original, brisk one-minute origin story: 14 portrait code graphics, dry humor, "
        "Chatterbox Turbo narration, and a 60-second target.\n\n"
        "From the repository root, using the media environment:\n\n```sh\n"
        f"python studio.py narrate {destination}\n"
        f"python studio.py assemble {destination}\n```\n\n"
        "The images are already supplied; use the commands above rather than the image-generation stage. "
        "The result is `final.mp4`. An optional `animatic.mp4` is a silent timing preview, not the narrated export.\n\n"
        "`script.txt` contains the spoken script, `storyboard.md` the planned beats, "
        "and `sources.md` the historical references. Actual scene timings follow the generated voice; "
        "assembly fits the total to 60 seconds when the required tempo remains within its safe range.\n"
    )
    lines = []
    for index, scene in enumerate(SCENES, 1):
        lines += [f"file 'images/{index:02}.png'", f"duration {scene[0]}"]
    lines += [f"file 'images/{len(SCENES):02}.png'"]
    (destination / "storyboard.ffconcat").write_text("\n".join(lines) + "\n")
    studio.load_project(destination.resolve())
    print(f"Created {destination}: {len(SCENES)} scenes, {word_count} narration words, 60-second storyboard.")


if __name__ == "__main__":
    main()
