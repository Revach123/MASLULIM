from xx.search import parse, search
from xx.download import safe_name


class FakeResp:
    def __init__(self, data): self._d = data
    def raise_for_status(self): pass
    def json(self): return self._d


class FakeSession:
    def __init__(self): self.calls = 0
    def get(self, url, params=None, timeout=0):
        self.calls += 1
        if params["page"] > 1:
            return FakeResp({"results": []})
        return FakeResp({"results": [
            {"id": "abcdef123456", "title": "Sea / view", "url": "http://x/a.jpg", "creator": "Dan",
             "license": "by", "license_version": "4.0", "width": 2000, "height": 1000, "filetype": "jpg"},
            {"id": "small", "title": "tiny", "url": "http://x/b.jpg", "width": 100, "height": 100},
        ]})


def test_search_filters_width():
    res = search("sea", limit=5, min_width=1200, session=FakeSession())
    assert [r.id for r in res] == ["abcdef123456"]
    assert "CC BY 4.0" in res[0].attribution


def test_safe_name():
    img = parse({"id": "abcdef123456", "title": "Sea / view", "url": "u"})
    assert safe_name(img) == "Sea_view_abcdef12.jpg"
