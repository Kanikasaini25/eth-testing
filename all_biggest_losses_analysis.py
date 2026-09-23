#!/usr/bin/env python3

import json
from datetime import datetime
from collections import defaultdict

# Read the results file
with open('data/reports/wI9b968AvW8_results.json', 'r') as f:
    data = json.load(f)

# Extract trades data
trades = data[0]['trades']

# Group trades by month and analyze in detail
monthly_data = defaultdict(lambda: {
    'total_points': 0.0,
    'losing_points': 0.0,
    'winning_points': 0.0,
    'total_pnl': 0.0,
    'losing_trades': [],
    'winning_trades': [],
    'total_trades': 0,
    'wins': 0,
    'losses': 0
})

# Collect ALL losing trades for global ranking
all_losing_trades = []

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
    
    # Store complete trade info
    trade_info = {
        'date': trade['exit_date'][:10],
        'month': month_key,
        'points': points,
        'pnl': pnl,
        'exit_reason': trade['exit_reason']
    }
    
    # Separate losing and winning trades
    if pnl < 0:  # Losing trade
        monthly_data[month_key]['losing_points'] += abs(points)
        monthly_data[month_key]['losing_trades'].append(trade_info)
        monthly_data[month_key]['losses'] += 1
        all_losing_trades.append(trade_info)
    else:  # Winning trade
        monthly_data[month_key]['winning_points'] += abs(points) if points > 0 else points
        monthly_data[month_key]['winning_trades'].append(trade_info)
        monthly_data[month_key]['wins'] += 1

# Sort months chronologically
sorted_months = sorted(monthly_data.keys())

month_names = {
    '01': 'January', '02': 'February', '03': 'March', '04': 'April',
    '05': 'May', '06': 'June', '07': 'July', '08': 'August',
    '09': 'September', '10': 'October', '11': 'November', '12': 'December'
}

print("📊 COMPREHENSIVE MONTHLY TRADING ANALYSIS")
print("WITH ALL INDIVIDUAL LOSING TRADES")
print("=" * 80)

for month_key in sorted_months:
    data = monthly_data[month_key]
    year, month_num = month_key.split('-')
    month_name = f"{month_names[month_num]} {year}"
    
    # Calculate metrics
    avg_points_per_trade = data['total_points'] / data['total_trades'] if data['total_trades'] > 0 else 0
    win_rate = (data['wins'] / data['total_trades'] * 100) if data['total_trades'] > 0 else 0
    
    # Sort all losing trades by points (most negative first)
    losing_trades = sorted(data['losing_trades'], key=lambda x: x['points'])
    
    # Calculate loss statistics
    if losing_trades:
        loss_points = [abs(trade['points']) for trade in losing_trades]
        min_loss = min(loss_points)
        max_loss = max(loss_points)
        avg_loss = sum(loss_points) / len(loss_points)
        biggest_single_loss = max_loss
        
        # Determine most common loss range
        range_6_10 = sum(1 for p in loss_points if 6 <= p <= 10)
        range_10_15 = sum(1 for p in loss_points if 10 < p <= 15)
        range_0_6 = sum(1 for p in loss_points if 0 < p < 6)
        
        if range_6_10 >= range_10_15 and range_6_10 >= range_0_6:
            common_range = "6 to 10 points"
        elif range_10_15 >= range_0_6:
            common_range = "10 to 15 points"
        else:
            common_range = "0 to 6 points"
    else:
        biggest_single_loss = 0
        common_range = "No losses"
        avg_loss = 0
    
    # Print detailed breakdown
    print(f"\n🗓️  **{month_name.upper()}**")
    print("=" * 60)
    print(f"📉 Total Points Lost: {data['losing_points']:.2f} points")
    print(f"📈 Total Points Won: {data['winning_points']:.2f} points")
    print(f"🎯 Net Points: {data['total_points']:+.2f} points")
    print(f"💰 Net P/L: ${data['total_pnl']:+.2f}")
    
    print(f"\n**Breakdown:**")
    print(f"Total Trades: {data['total_trades']} ({data['wins']} wins, {data['losses']} losses)")
    print(f"Win Rate: {win_rate:.1f}%")
    print(f"Average Points per Trade: {avg_points_per_trade:.2f} points")
    if biggest_single_loss > 0:
        biggest_loss_trade = min(data['losing_trades'], key=lambda x: x['points'])
        print(f"Biggest Single Point Loss: {biggest_single_loss:.2f} points (on {biggest_loss_trade['date']})")
        print(f"Average Loss per Losing Trade: {avg_loss:.2f} points")
        print(f"Most Common Loss Range: {common_range} per losing trade")
    
    # ALL losing trades for this month
    if losing_trades:
        print(f"\n**ALL {len(losing_trades)} BIGGEST POINT LOSSES (Individual Trades):**")
        for i, trade in enumerate(losing_trades, 1):
            date_obj = datetime.strptime(trade['date'], '%Y-%m-%d')
            date_formatted = f"{month_names[f'{date_obj.month:02d}']} {date_obj.day}"
            print(f"{i:2d}. {date_formatted}: {trade['points']:.2f} points (${trade['pnl']:.2f}) - {trade['exit_reason']}")
    
    print("-" * 60)

# Global analysis of all losing trades
print(f"\n🌍 GLOBAL ANALYSIS - ALL LOSING TRADES RANKED")
print("=" * 80)

# Sort ALL losing trades by points (biggest losses first)
all_losing_trades_sorted = sorted(all_losing_trades, key=lambda x: x['points'])

print(f"**TOP 20 BIGGEST POINT LOSSES ACROSS ALL MONTHS:**")
print(f"{'Rank':<4} {'Date':<12} {'Month':<12} {'Points':<8} {'P/L ($)':<10} {'Reason'}")
print("-" * 65)

for i, trade in enumerate(all_losing_trades_sorted[:20], 1):
    date_obj = datetime.strptime(trade['date'], '%Y-%m-%d')
    month_year = f"{month_names[f'{date_obj.month:02d}']} {date_obj.year}"
    date_formatted = f"{month_names[f'{date_obj.month:02d}']} {date_obj.day}"
    print(f"{i:<4} {date_formatted:<12} {month_year:<12} {trade['points']:<8.2f} ${trade['pnl']:<9.2f} {trade['exit_reason']}")

print(f"\n📊 GLOBAL STATISTICS:")
print("=" * 50)
total_losing_trades = len(all_losing_trades_sorted)
total_points_lost = sum(abs(trade['points']) for trade in all_losing_trades_sorted)
avg_points_per_loss = total_points_lost / total_losing_trades if total_losing_trades > 0 else 0

worst_trade = all_losing_trades_sorted[0] if all_losing_trades_sorted else None
if worst_trade:
    worst_date = datetime.strptime(worst_trade['date'], '%Y-%m-%d')
    worst_month = f"{month_names[f'{worst_date.month:02d}']} {worst_date.year}"

print(f"📉 Total Losing Trades: {total_losing_trades}")
print(f"📉 Total Points Lost: {total_points_lost:.2f}")
print(f"📊 Average Points per Loss: {avg_points_per_loss:.2f}")
if worst_trade:
    print(f"🔴 Single Worst Trade: {worst_trade['points']:.2f} points on {worst_trade['date']} ({worst_month})")

# Monthly ranking by total points lost
print(f"\n🏆 MONTHLY RANKING BY TOTAL POINTS LOST:")
print("=" * 50)
monthly_ranking = []
for month_key in sorted_months:
    data = monthly_data[month_key]
    year, month_num = month_key.split('-')
    month_name = f"{month_names[month_num]} {year}"
    monthly_ranking.append({
        'month': month_name,
        'points_lost': data['losing_points'],
        'num_losses': data['losses']
    })

# Sort by points lost (descending)
monthly_ranking.sort(key=lambda x: x['points_lost'], reverse=True)

print(f"{'Rank':<5} {'Month':<15} {'Points Lost':<12} {'Num Losses'}")
print("-" * 50)
for i, month_data in enumerate(monthly_ranking, 1):
    print(f"{i:<5} {month_data['month']:<15} {month_data['points_lost']:<12.2f} {month_data['num_losses']}")

print(f"\n🎯 KEY INSIGHTS:")
print("=" * 50)
worst_month_data = monthly_ranking[0]
best_month_data = monthly_ranking[-1]
print(f"🔴 Worst Month: {worst_month_data['month']} ({worst_month_data['points_lost']:.2f} points)")
print(f"🟢 Best Month: {best_month_data['month']} ({best_month_data['points_lost']:.2f} points)")
print(f"📊 Difference: {worst_month_data['points_lost'] - best_month_data['points_lost']:.2f} points")
print(f"📈 Worst vs Best Ratio: {worst_month_data['points_lost'] / best_month_data['points_lost']:.1f}x worse")