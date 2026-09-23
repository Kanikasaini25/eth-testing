#!/usr/bin/env python3

import json
from datetime import datetime
from collections import defaultdict

# Read the results file
with open('data/reports/wI9b968AvW8_results.json', 'r') as f:
    data = json.load(f)

# Extract trades data
trades = data[0]['trades']

# Group trades by month and calculate monthly P/L
monthly_pnl = defaultdict(float)

for trade in trades:
    # Parse the exit date to get the month
    exit_date = datetime.strptime(trade['exit_date'], "%Y-%m-%d %H:%M UTC")
    month_key = f"{exit_date.year}-{exit_date.month:02d}"
    
    # Add the P/L to the monthly total
    monthly_pnl[month_key] += trade['pnl_usd']

# Convert to list and sort by P/L (ascending to get biggest losses first)
monthly_results = []
for month, pnl in monthly_pnl.items():
    year, month_num = month.split('-')
    month_names = {
        '01': 'January', '02': 'February', '03': 'March', '04': 'April',
        '05': 'May', '06': 'June', '07': 'July', '08': 'August',
        '09': 'September', '10': 'October', '11': 'November', '12': 'December'
    }
    month_name = month_names[month_num]
    
    monthly_results.append({
        'month': f"{month_name} {year}",
        'pnl': pnl,
        'month_key': month
    })

# Sort by P/L (ascending) to get biggest losses first
monthly_results.sort(key=lambda x: x['pnl'])

print("BIGGEST LOSS MONTHS (Sorted by Net P/L - Biggest Losses First)")
print("=" * 65)
print(f"{'Rank':<4} {'Month':<15} {'Net P/L (USD)':<15} {'Status'}")
print("-" * 65)

for i, result in enumerate(monthly_results, 1):
    status = "LOSS" if result['pnl'] < 0 else "PROFIT"
    print(f"{i:<4} {result['month']:<15} ${result['pnl']:<14.2f} {status}")

print("\n" + "=" * 65)
print(f"Total months analyzed: {len(monthly_results)}")

# Also show just the loss months
loss_months = [r for r in monthly_results if r['pnl'] < 0]
if loss_months:
    print(f"Loss months only: {len(loss_months)}")
    print("\nTOP 5 BIGGEST LOSS MONTHS:")
    print("-" * 40)
    for i, result in enumerate(loss_months[:5], 1):
        print(f"{i}. {result['month']}: ${result['pnl']:.2f}")