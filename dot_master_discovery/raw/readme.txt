Drop the raw EA export CSV here, then run:  python rebuild.py

The EA writes it to:
  ...\MetaQuotes\Terminal\<ID>\MQL4\Files\<ASSET>_AUTO_EXPORT.csv
Copy that file into this folder. rebuild.py corrects/validates it, splits it,
and places the parts into data\ ready for master.py.
