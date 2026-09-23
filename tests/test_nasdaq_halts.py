from datetime import date

from delist_detection.nasdaq_halts import Halt, NasdaqHaltClient, last_trade_from_halt, parse_halts_rss

RSS = """﻿<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:ndaq="http://www.nasdaqtrader.com/">
  <channel>
    <item>
      <title>ALTR</title>
      <ndaq:IssueSymbol>ALTR</ndaq:IssueSymbol>
      <ndaq:IssueName>Altair Engineering Inc. Class A Common Stock</ndaq:IssueName>
      <ndaq:Mkt>Q</ndaq:Mkt>
      <ndaq:ReasonCode>D</ndaq:ReasonCode>
      <ndaq:HaltDate>03/25/2025</ndaq:HaltDate>
      <ndaq:HaltTime>19:50:00</ndaq:HaltTime>
      <ndaq:ResumptionDate>03/27/2025</ndaq:ResumptionDate>
    </item>
    <item>
      <title>CNSP</title>
      <ndaq:IssueSymbol>CNSP</ndaq:IssueSymbol>
      <ndaq:IssueName>CNS Pharmaceuticals</ndaq:IssueName>
      <ndaq:Mkt>Q</ndaq:Mkt>
      <ndaq:ReasonCode>T3</ndaq:ReasonCode>
      <ndaq:HaltDate>03/25/2025</ndaq:HaltDate>
      <ndaq:HaltTime>07:55:00</ndaq:HaltTime>
      <ndaq:ResumptionDate />
    </item>
  </channel>
</rss>"""


def test_parse():
    halts = parse_halts_rss(RSS)
    assert halts[0] == Halt("ALTR", "Altair Engineering Inc. Class A Common Stock", "Q", "D",
                            date(2025, 3, 25), "19:50:00", date(2025, 3, 27))
    assert halts[1].resumption_date is None


def test_last_trade_from_halt():
    after_close = Halt("ALTR", "", "Q", "D", date(2025, 3, 25), "19:50:00", None)
    before_open = Halt("SAVE", "", "N", "D", date(2024, 11, 18), "04:30:00", None)
    assert last_trade_from_halt(after_close) == date(2025, 3, 25)
    assert last_trade_from_halt(before_open) == date(2024, 11, 15)


class _Resp:
    status_code = 200

    def __init__(self, text):
        self.text = text


class _Session:
    def __init__(self):
        self.urls = []

    def get(self, url, headers=None, timeout=None):
        self.urls.append(url)
        return _Resp(RSS if "03252025" in url else RSS.replace("<item>", "<x>").replace("</item>", "</x>"))


def test_client_caches_and_finds_deletion(tmp_path):
    s = _Session()
    c = NasdaqHaltClient(tmp_path, session=s, min_interval=0)
    h = c.deletion_halt("ALTR", date(2025, 3, 24), date(2025, 3, 26))
    assert h is not None and h.halt_date == date(2025, 3, 25)
    assert c.deletion_halt("CNSP", date(2025, 3, 25), date(2025, 3, 25)) is None     # T3, not D
    n = len(s.urls)
    c.halts_on(date(2025, 3, 25))
    assert len(s.urls) == n                                                          # cached
    assert "haltdate=03252025" in s.urls[1] or "haltdate=03252025" in s.urls[0]
