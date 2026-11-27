# Updating the 9two3 Quant Desk dashboard after a run

Dashboard: https://claude.ai/artifact/BAKkt3hfBb2MdwVUTpepQM  (slug 5248a3c1-3408-4e20-94b7-391a0b1d739e)

After `python run_daily.py preclose|postclose` (and only if out/SKIP does not exist):

1. upload_asset to the slug: out/status.json, out/orders.json, out/positions.json,
   out/trades.json, out/equity.json (keep these file names).
2. db_list collection "datasets" to get each document's version.
3. db_write with one "update" op per dataset (ifVersion = its version):
   path datasets/<name>, data {"source": {"kind": "file", "url": "<new /_blob/ url>",
   "name": "<name>.json", "format": "json"}, "updated": {"at": "<UTC ISO time>", "by": "Claude"}}
   for name in status, orders, positions, trades, equity.
4. After a monthly backtest refresh, do the same for bt_equity, bt_periods, bt_books.
Never change files/index.html from a scheduled run.
