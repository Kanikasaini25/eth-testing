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
        'points': points,
        'pnl': pnl,
        'exit_reason': trade['exit_reason']
    }
    
    # Separate losing and winning trades
    if pnl < 0:  # Losing trade
        monthly_data[month_key]['losing_points'] += abs(points)
        monthly_data[month_key]['losing_trades'].append(trade_info)
        monthly_data[month_key]['losses'] += 1
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
print("=" * 80)

for month_key in sorted_months:
    data = monthly_data[month_key]
    year, month_num = month_key.split('-')
    month_name = f"{month_names[month_num]} {year}"
    
    # Calculate metrics
    avg_points_per_trade = data['total_points'] / data['total_trades'] if data['total_trades'] > 0 else 0
    win_rate = (data['wins'] / data['total_trades'] * 100) if data['total_trades'] > 0 else 0
    
    # Find biggest losses
    losing_trades = sorted(data['losing_trades'], key=lambda x: x['points'])
    top_5_losses = losing_trades[:5]  # Biggest losses (most negative)
    
    # Find loss ranges
    loss_points = [abs(trade['points']) for trade in data['losing_trades']]
    if loss_points:
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
        # Find the date of biggest loss
        biggest_loss_trade = min(data['losing_trades'], key=lambda x: x['points'])
        print(f"Biggest Single Point Loss: {biggest_single_loss:.2f} points (on {biggest_loss_trade['date']})")
        print(f"Most Common Loss Range: {common_range} per losing trade")
    
    # Top 5 biggest losses
    if top_5_losses:
        print(f"\n**Top {min(5, len(top_5_losses))} Biggest Point Losses (Individual Trades):**")
        for i, trade in enumerate(top_5_losses, 1):
            date_short = trade['date'][5:]  # Show MM-DD format
            print(f"{i}. {month_names[date_short[:2]]} {date_short[3:]}: {trade['points']:.2f} points (${trade['pnl']:.2f})")
    
    print("-" * 60)

print(f"\n📋 SUMMARY ACROSS ALL MONTHS:")
print("=" * 60)

# Calculate overall totals
total_points_lost = sum(data['losing_points'] for data in monthly_data.values())
total_points_won = sum(data['winning_points'] for data in monthly_data.values())
total_net_points = sum(data['total_points'] for data in monthly_data.values())
total_net_pnl = sum(data['total_pnl'] for data in monthly_data.values())
total_trades = sum(data['total_trades'] for data in monthly_data.values())
total_wins = sum(data['wins'] for data in monthly_data.values())
total_losses = sum(data['losses'] for data in monthly_data.values())

print(f"📉 Total Points Lost: {total_points_lost:.2f}")
print(f"📈 Total Points Won: {total_points_won:.2f}")
print(f"🎯 Net Points: {total_net_points:+.2f}")
print(f"💰 Net P/L: ${total_net_pnl:+.2f}")
print(f"📊 Total Trades: {total_trades} ({total_wins} wins, {total_losses} losses)")
print(f"🎯 Overall Win Rate: {(total_wins/total_trades*100):.1f}%")

# Find worst and best months
worst_month = max(monthly_data.items(), key=lambda x: x[1]['losing_points'])
best_month = min(monthly_data.items(), key=lambda x: x[1]['losing_points'])

worst_month_name = f"{month_names[worst_month[0][-2:]]} {worst_month[0][:4]}"
best_month_name = f"{month_names[best_month[0][-2:]]} {best_month[0][:4]}"

print(f"\n🔴 Worst Month (Most Points Lost): {worst_month_name} ({worst_month[1]['losing_points']:.2f} points)")
print(f"🟢 Best Month (Least Points Lost): {best_month_name} ({best_month[1]['losing_points']:.2f} points)")