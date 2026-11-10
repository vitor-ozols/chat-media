import bz2
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wiki.build import build
from wiki.dump import WikiDump, fts_query
from wiki.rag import Ollama, answer, language_hint, trim_history
from wiki.text import LINK_OPEN, clean_wikitext, lead, sections, to_plain

PAGES = {
    "Brazil": """{{Infobox country|conventional_long_name = Federative Republic of Brazil|capital = [[Brasília]]|image_flag = Flag.svg}}
'''Brazil''' is a [[country]] in [[South America]].<ref>Some source</ref> It is the largest country there.

== History ==
Portugal colonised Brazil in 1500. {{convert|8514877|km2}} of land.

== Geography ==
* The [[Amazon River|Amazon]] flows through the north.
* [[File:Map.png|thumb|A [[map]]]]

== References ==
{{reflist}}""",
    "Brasília": "'''Brasília''' is the [[capital city]] of [[Brazil]]. It was founded on 21 April 1960.",
    "Photosynthesis": "'''Photosynthesis''' is how [[plant]]s make food from light.",
}
REDIRECTS = {"Brasil": "Brazil"}


def page_xml(page_id, title, text=None, redirect=None):
    body = f'<redirect title="{redirect}" />' if redirect else ""
    escaped = (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (f"  <page>\n    <title>{title}</title>\n    <ns>0</ns>\n    <id>{page_id}</id>\n    {body}\n"
            f"    <revision><text bytes=\"{len(escaped)}\" xml:space=\"preserve\">{escaped}</text></revision>\n  </page>\n")


def make_dump(directory: Path):
    header = ("<mediawiki><siteinfo><sitename>Wikipedia</sitename><dbname>testwiki</dbname>"
              "<base>https://test.wikipedia.org/wiki/Main_Page</base></siteinfo>\n")
    entries = [(i, title, text, None) for i, (title, text) in enumerate(PAGES.items(), 1)]
    entries += [(10 + i, title, None, target) for i, (title, target) in enumerate(REDIRECTS.items())]
    streams = [entries[:2], entries[2:]]
    data, index = bz2.compress(header.encode()), []
    for stream in streams:
        offset = len(data)
        xml = "".join(page_xml(page_id, title, text, redirect) for page_id, title, text, redirect in stream)
        data += bz2.compress(xml.encode())
        index += [f"{offset}:{page_id}:{title}" for page_id, title, _, _ in stream]
    data += bz2.compress(b"</mediawiki>")
    (directory / "testwiki-latest-pages-articles-multistream.xml.bz2").write_bytes(data)
    (directory / "testwiki-latest-pages-articles-multistream-index.txt.bz2").write_bytes(bz2.compress("\n".join(index).encode()))


class FakeOllama(Ollama):
    def __init__(self):
        super().__init__("http://ollama.invalid", "gemma3:1b")
        self.seen = []

    def models(self):
        return ["gemma3:1b"]

    def complete(self, messages, **options):
        return "Brasilia capital"

    def stream(self, messages):
        self.seen.append(messages)
        yield {"message": {"content": "Brasília é a capital [1]."}, "done": False}
        yield {"message": {"content": ""}, "done": True, "eval_count": 6, "eval_duration": 1e9, "prompt_eval_count": 90, "total_duration": 2e9}


class WikiTextTests(unittest.TestCase):
    def test_cleaner_keeps_prose_links_and_infobox(self):
        infobox = []
        text = clean_wikitext(PAGES["Brazil"], infobox)
        self.assertIn(f"{LINK_OPEN}South America", text)
        self.assertNotIn("<ref", text)
        self.assertNotIn("File:", text)
        self.assertIn("8514877 km2", text)
        self.assertIn("capital: Brasília", infobox)
        self.assertFalse(any(line.startswith("image") for line in infobox))
        titles = [s["title"] for s in sections(text)]
        self.assertEqual(titles, ["", "History", "Geography"])
        self.assertTrue(lead(PAGES["Brazil"]).startswith("Brazil is a country in South America."))
        self.assertEqual(to_plain(f"{LINK_OPEN}Amazon River❘Amazon⟧"), "Amazon")

    def test_helpers(self):
        self.assertEqual(fts_query('What is "photosynthesis"?'), '"photosynthesis"')
        self.assertIn("português", language_hint("Qual é a capital?"))
        self.assertNotIn("português", language_hint("What do plants eat?"))
        history = [{"role": "assistant", "content": "x"}, {"role": "user", "content": "a" * 2000}, {"role": "assistant", "content": "ok"}]
        self.assertEqual(trim_history(history, 400)[0]["role"], "user")


class WikiDumpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.directory = cls.root / "testwiki"
        cls.directory.mkdir()
        make_dump(cls.directory)
        build(cls.directory, workers=1)
        cls.dump = WikiDump(cls.directory)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_build_search_and_read(self):
        status = self.dump.status()
        self.assertTrue(status["ready"])
        self.assertEqual(status["articles"], "3")
        self.assertEqual(status["base_url"], "https://test.wikipedia.org/wiki/")
        results = self.dump.search("photosynthesis plants")
        self.assertEqual(results[0]["title"], "Photosynthesis")
        top = self.dump.search("Brasil")[0]
        self.assertEqual((top["title"], top["exact"]), ("Brazil", True))
        article = self.dump.article("brasil")
        self.assertEqual((article.title, article.redirected_from), ("Brazil", "Brasil"))
        self.assertEqual(article.url, "https://test.wikipedia.org/wiki/Brazil")
        self.assertEqual(self.dump.article("Brasília").title, "Brasília")
        self.assertIsNone(self.dump.article("Nope"))
        self.assertEqual(self.dump.suggest("bra"), ["Brazil", "Brasília", "Brasil"])
        self.assertEqual(self.dump.entities("O que é o Brasil?"), ["Brazil"])
        self.assertEqual(self.dump.entities("como funciona a fotossíntese?"), [])

    def test_answer_packs_context_and_cites(self):
        llm = FakeOllama()
        events = list(answer(llm, self.dump, "qual é a capital do país?", []))
        sources = next(e for e in events if e["type"] == "sources")["sources"]
        self.assertEqual(sources[0]["title"], "Brasília")  # via the model's rewritten query
        named = list(answer(llm, self.dump, "Qual é a capital do Brasil?", []))
        self.assertEqual([s["title"] for s in next(e for e in named if e["type"] == "sources")["sources"]], ["Brazil"])
        self.assertIn("capital: Brasília", llm.seen[-1][-1]["content"])
        prompt = llm.seen[0][-1]["content"]  # first (rewritten-query) answer
        self.assertIn("[1] Brasília", prompt)
        self.assertIn("português", prompt)
        self.assertEqual(events[-1]["stats"]["tokens_per_second"], 6.0)
        pinned = list(answer(llm, self.dump, "When was it colonised?", [], article_title="Brazil"))
        self.assertEqual([s["title"] for s in next(e for e in pinned if e["type"] == "sources")["sources"]], ["Brazil"])
        self.assertIn("1500", llm.seen[-1][-1]["content"])

    def test_routes(self):
        from flask import Blueprint, Flask
        from wiki.web import register_wiki
        from wiki.dump import WikiLibrary

        app = Flask(__name__)
        web = Blueprint("web", __name__)
        register_wiki(web, WikiLibrary(self.root), FakeOllama())
        app.register_blueprint(web, url_prefix="/chat")
        client = app.test_client()
        status = client.get("/chat/api/wiki/status").json
        self.assertTrue(status["model_ready"])
        self.assertEqual(status["dumps"][0]["name"], "testwiki")
        self.assertEqual(client.get("/chat/api/wiki/search?q=photosynthesis").json["results"][0]["title"], "Photosynthesis")
        article = client.get("/chat/api/wiki/article?title=Brasil&raw=1").json
        self.assertEqual(article["title"], "Brazil")
        self.assertIn("'''Brazil'''", article["wikitext"])
        self.assertEqual(client.get("/chat/api/wiki/article?title=Nope").status_code, 404)
        self.assertEqual(client.post("/chat/api/wiki/chat", json={"question": ""}).status_code, 400)
        response = client.post("/chat/api/wiki/chat", json={"question": "Capital do Brasil?", "history": []})
        events = [json.loads(line) for line in response.get_data(as_text=True).splitlines()]
        self.assertEqual(events[-1]["type"], "done")
        self.assertIn("Brasília é a capital [1].", "".join(e.get("text", "") for e in events))
        # The concurrency slot is released after each stream.
        for _ in range(3):
            client.post("/chat/api/wiki/chat", json={"question": "Oi?", "use_wiki": False}).get_data()
        self.assertEqual(client.post("/chat/api/wiki/chat", json={"question": "Oi?", "use_wiki": False}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
