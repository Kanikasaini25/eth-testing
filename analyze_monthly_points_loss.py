#!/usr/bin/env python3

import json
from datetime import datetime
from collections import defaultdict

# Read the results file
with open('data/reports/wI9b968AvW8_results.json', 'r') as f:
    data = json.load(f)

# Extract trades data
trades = data[0]['trades']

# Group trades by month and calculate monthly points and P/L
monthly_data = defaultdict(lambda: {
    'total_points': 0.0,
    'losing_points': 0.0,
    'winning_points': 0.0,
    'total_pnl': 0.0,
    'losing_trades': 0,
    'winning_trades': 0,
    'total_trades': 0
})

for trade in trades:
    # Parse the exit date to get the month
    exit_date = datetime.strptime(trade['exit_date'], "%Y-%m-%d %H:%M UTC")
    month_key = f"{exit_date.year}-{exit_date.month:02d}"
    
    points = trade['points']
    pnl = trade['pnl_usd']
    
    # Add to monthly totals
    monthly_data[month_key]['total_points'] += points
    monthly_data[month_key]['total_pnl'] += pnl
    monthly_data[month_key]['total_trades'] += 1
    
    # Separate losing and winning trades
    if pnl < 0:  # Losing trade
        monthly_data[month_key]['losing_points'] += abs(points) if points < 0 else -points
        monthly_data[month_key]['losing_trades'] += 1
    else:  # Winning trade
        monthly_data[month_key]['winning_points'] += points if points > 0 else -points
        monthly_data[month_key]['winning_trades'] += 1

# Convert to list and sort by losing points (descending to get biggest losses first)
monthly_results = []
for month, data in monthly_data.items():
    year, month_num = month.split('-')
    month_names = {
        '01': 'January', '02': 'February', '03': 'March', '04': 'April',
        '05': 'May', '06': 'June', '07': 'July', '08': 'August',
        '09': 'September', '10': 'October', '11': 'November', '12': 'December'
    }
    month_name = month_names[month_num]
    
    monthly_results.append({
        'month': f"{month_name} {year}",
        'total_points': data['total_points'],
        'losing_points': data['losing_points'],
        'winning_points': data['winning_points'],
        'total_pnl': data['total_pnl'],
        'losing_trades': data['losing_trades'],
        'winning_trades': data['winning_trades'],
        'total_trades': data['total_trades'],
        'month_key': month
    })

# Sort by losing points (descending) to get biggest point losses first
monthly_results.sort(key=lambda x: x['losing_points'], reverse=True)

print("MONTHLY POINTS LOSS ANALYSIS (Sorted by Biggest Points Loss First)")
print("=" * 85)
print(f"{'Rank':<4} {'Month':<15} {'Total Points':<12} {'Losing Points':<13} {'Winning Points':<14} {'Net P/L ($)':<12}")
print("-" * 85)

for i, result in enumerate(monthly_results, 1):
    print(f"{i:<4} {result['month']:<15} {result['total_points']:<12.2f} {result['losing_points']:<13.2f} {result['winning_points']:<14.2f} ${result['total_pnl']:<11.2f}")

print("\n" + "=" * 85)

# Detailed breakdown
print("\nDETAILED MONTHLY BREAKDOWN:")
print("=" * 85)
for result in monthly_results:
    print(f"\n📅 {result['month']}")
    print(f"   Total Trades: {result['total_trades']} (Wins: {result['winning_trades']}, Losses: {result['losing_trades']})")
    print(f"   Points Lost: {result['losing_points']:.2f}")
    print(f"   Points Won: {result['winning_points']:.2f}")
    print(f"   Net Points: {result['total_points']:.2f}")
    print(f"   Net P/L: ${result['total_pnl']:.2f}")
    
    if result['total_trades'] > 0:
        avg_points_per_trade = result['total_points'] / result['total_trades']
        print(f"   Average Points per Trade: {avg_points_per_trade:.2f}")

print("\n" + "=" * 85)
print(f"📊 SUMMARY:")
total_losing_points = sum(r['losing_points'] for r in monthly_results)
total_winning_points = sum(r['winning_points'] for r in monthly_results)
total_net_points = sum(r['total_points'] for r in monthly_results)
print(f"   Total Points Lost Across All Months: {total_losing_points:.2f}")
print(f"   Total Points Won Across All Months: {total_winning_points:.2f}")
print(f"   Net Points Across All Months: {total_net_points:.2f}")

# Show individual losing trades for the worst month
if monthly_results:
    worst_month = monthly_results[0]
    print(f"\n🔍 LOSING TRADES IN {worst_month['month']} (Biggest Point Loss Month):")
    print("-" * 60)
    print(f"{'Date':<12} {'Points':<8} {'P/L ($)':<10} {'Reason'}")
    print("-" * 60)
    
    month_key = worst_month['month_key']
    for trade in trades:
        exit_date = datetime.strptime(trade['exit_date'], "%Y-%m-%d %H:%M UTC")
        trade_month = f"{exit_date.year}-{exit_date.month:02d}"
        
        if trade_month == month_key and trade['pnl_usd'] < 0:
            date_str = trade['exit_date'][:10]
            print(f"{date_str:<12} {trade['points']:<8.2f} ${trade['pnl_usd']:<9.2f} {trade['exit_reason']}")