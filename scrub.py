import pathlib

PUB = pathlib.Path('/home/ubuntu/alpha_engine_public')

# ── web/app.py ─────────────────────────────────────────────────────────────
app_path = PUB / 'web/app.py'
src = app_path.read_text()

replacements_app = [
    ('execute manually in Fidelity',
     'execute manually in your broker'),
    ('executing trades in Fidelity, go to',
     'executing trades in your broker, go to'),
    ('Log your actual Fidelity fills to keep the portfolio in sync',
     'Log your actual broker fills to keep the portfolio in sync'),
    ('Wipe and re-enter your actual Fidelity holdings',
     'Wipe and re-enter your actual holdings'),
    ('Enter each position from your Fidelity account.',
     'Enter each position from your brokerage account.'),
    ("from Fidelity's Positions page.",
     "from your broker's Positions page."),
    ('Your current Fidelity cash balance (SPAXX)',
     'Your current cash balance'),
    ('This is the amount you transfer to Fidelity each payday.',
     'This is the amount you transfer to your broker each payday.'),
    ('transferred the money to Fidelity before executing trades.',
     'transferred the money to your broker before executing trades.'),
    ('Cash (SPAXX)',
     'Cash'),
    ('# TICKER, SHARES, PRICE, DATE',
     '# AAPL, 1.5, 150.00, 2024-01-05'),
]

changed = []
for old, new in replacements_app:
    if old in src:
        src = src.replace(old, new)
        changed.append(('app.py', old[:70], new[:70]))
    else:
        print(f'MISS app.py: {old[:70]}')

app_path.write_text(src)

# ── src/rebalance.py ───────────────────────────────────────────────────────
reb_path = PUB / 'src/rebalance.py'
src = reb_path.read_text()

replacements_reb = [
    ('execute first in Fidelity',
     'execute first in your broker'),
    ('dollar-amount orders in Fidelity',
     'dollar-amount orders in your broker'),
]

for old, new in replacements_reb:
    if old in src:
        src = src.replace(old, new)
        changed.append(('rebalance.py', old, new))
    else:
        print(f'MISS rebalance.py: {old}')

reb_path.write_text(src)

# ── README.md ──────────────────────────────────────────────────────────────
readme_path = PUB / 'README.md'
src = readme_path.read_text()

replacements_readme = [
    ('Log your actual Fidelity fills (dollar-amount buys, share-count buys, sells)',
     'Log your actual broker fills (dollar-amount buys, share-count buys, sells)'),
    ('| Hosting | Oracle Cloud Free Tier (ARM VM) |',
     '| Hosting | Any Linux VPS (e.g. Oracle Cloud Free Tier, DigitalOcean, Hetzner) |'),
    ('A Linux server (Ubuntu 22.04 recommended; Oracle Cloud Free Tier works)',
     'A Linux server (Ubuntu 22.04 recommended; any Linux VPS works)'),
]

for old, new in replacements_readme:
    if old in src:
        src = src.replace(old, new)
        changed.append(('README.md', old[:70], new[:70]))
    else:
        print(f'MISS README.md: {old[:70]}')

readme_path.write_text(src)

# ── Report ─────────────────────────────────────────────────────────────────
print(f'\nApplied {len(changed)} replacements:')
for fname, old, new in changed:
    print(f'  [{fname}] "{old}" -> "{new}"')
