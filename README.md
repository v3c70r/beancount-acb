
# RSU ACB Calculator

This Python script calculates the Adjusted Cost Base (ACB) for RSU (Restricted Stock Unit) symbols for Canada tax filing purposes from a Beancount journal. It relies on the [pricehist](https://pypi.org/project/pricehist/) and [beancount](https://pypi.org/project/beancount/) packages.

## Usage

```bash
pip install -r requirements.txt
python acb.py -i <journal_file> -s <rsu_symbol>
```
