# BBG000BW8S60_fb3c-r1 (RTX, regression, operator diagnosis)

## 1. Verdict
United Technologies (CIK 101829) completed its merger with Raytheon on 2020-04-03, renamed itself Raytheon Technologies
and listed its common stock on the NYSE as RTX from that day. The batch 3 run's ranges (UTX to 2020-04-02, RTX from
2020-04-03) are right; the base's (UTX to 2020-04-08, RTX from 2020-04-09) start RTX four sessions late.

## 2. Evidence
- 8-K of United Technologies, accession 0001140361-20-007906, date of report 2020-04-03 (cached copy): "In connection
  with the Merger, the Company's name was changed to Raytheon Technologies Corporation and its common stock is listed on
  the New York Stock Exchange under the symbol "RTX.""
- Round fb3b's diagnosis of the same regression (record BBG000BW8S60_fb3b-r1, which wrote no report) found the same
  ranges, RTX:2020-04-03.. and UTX:2007-12-20..2020-04-02, and attributed the base's late start to UTX's CUSIP settling
  tail, which f56ff50 stopped counting as ticker sightings. That record called them the old run's; they are the new
  run's (side_b of this case).

## 3. Operator ruling (2026-10-10)
Settled `new_right` in the ledger: the new run's ranges are the filing's.
