#!/usr/bin/env python3

import json
from datetime import datetime
from collections import defaultdict

def parse_ist_date(ist_date_str):
    """Parse IST date string to get month"""
    # Format: "2026-08-29 23:30:00 IST"
    date_part = ist_date_str.split()[0]  # Get "2026-08-29"
    return datetime.strptime(date_part, "%Y-%m-%d")

def analyze_funding_data():
    """Analyze funding data for monthly points"""
    
    # Read funding data files
    try:
        with open('data/funding_1day_lookbacks.json', 'r') as f:
            funding_1day = json.load(f)
        
        print("ANALYZING FUNDING 1-DAY DATA FOR MONTHLY POINTS LOSS")
        print("=" * 70)
        
        # Extract monthly data from funding results
        monthly_data = defaultdict(lambda: {
            'total_points': 0.0,
            'total_pnl': 0.0,
            'total_trades': 0,
            'wins': 0,
            'losses': 0,
            'win_rate': 0.0
        })
        
        # Process each result period
        for result in funding_1day['results']:
            from_date = parse_ist_date(result['from_ist'])
            to_date = parse_ist_date(result['to_ist'])
            
            # Get the ending month for this period
            month_key = f"{to_date.year}-{to_date.month:02d}"
            
            # Add data to monthly totals
            monthly_data[month_key]['total_pnl'] += result['net_pnl']
            monthly_data[month_key]['total_trades'] += result['trades']
            monthly_data[month_key]['wins'] += result['wins']
            monthly_data[month_key]['losses'] += result['losses']
            monthly_data[month_key]['win_rate'] = result['win_rate_pct']
            
            # Calculate points from net_points if available, otherwise estimate
            if 'net_points' in result:
                monthly_data[month_key]['total_points'] += result['net_points']
            else:
                # Estimate points from P/L (rough conversion)
                estimated_points = result['net_pnl'] * 0.8  # Rough estimate
                monthly_data[month_key]['total_points'] += estimated_points
        
        return monthly_data
        
    except FileNotFoundError:
        print("Funding data files not found")
        return {}

def analyze_main_results():
    """Analyze main results file"""
    try:
        with open('data/reports/wI9b968AvW8_results.json', 'r') as f:
            data = json.load(f)
        
        trades = data[0]['trades']
        
        # Group by month
        monthly_data = defaultdict(lambda: {
            'total_points': 0.0,
            'losing_points': 0.0,
            'winning_points': 0.0,
            'total_pnl': 0.0,
            'total_trades': 0,
            'wins': 0,
            'losses': 0
        })
        
        for trade in trades:
            exit_date = datetime.strptime(trade['exit_date'], "%Y-%m-%d %H:%M UTC")
            month_key = f"{exit_date.year}-{exit_date.month:02d}"
            
            points = trade['points']
            pnl = trade['pnl_usd']
            
            monthly_data[month_key]['total_points'] += points
            monthly_data[month_key]['total_pnl'] += pnl
            monthly_data[month_key]['total_trades'] += 1
            
            if pnl < 0:  # Losing trade
                monthly_data[month_key]['losing_points'] += abs(points)
                monthly_data[month_key]['losses'] += 1
            else:  # Winning trade  
                monthly_data[month_key]['winning_points'] += abs(points)
                monthly_data[month_key]['wins'] += 1
        
        return monthly_data
        
    except FileNotFoundError:
        print("Main results file not found")
        return {}

def main():
    print("COMPREHENSIVE MONTHLY POINTS LOSS ANALYSIS")
    print("=" * 70)
    
    # Get data from main results
    main_data = analyze_main_results()
    
    # Since we need historical data, let me create a realistic projection
    # based on your screenshot showing May-September data
    
    # From your screenshot, I can see the monthly win/loss counts:
    screenshot_data = {
        '2026-05': {'wins': 10, 'losses': 19, 'net_result': 422},
        '2026-06': {'wins': 6, 'losses': 37, 'net_result': -26},  # LOSS MONTH
        '2026-07': {'wins': 8, 'losses': 35, 'net_result': 201},
        '2026-08': {'wins': 8, 'losses': 17, 'net_result': 259},
        '2026-09': {'wins': 8, 'losses': 26, 'net_result': 335}
    }
    
    month_names = {
        '05': 'May', '06': 'June', '07': 'July', '08': 'August', '09': 'September'
    }
    
    print("MONTHLY POINTS LOSS ANALYSIS (Based on Screenshot Data)")
    print("=" * 70)
    print(f"{'Month':<12} {'Wins':<5} {'Losses':<7} {'Est. Points Lost':<16} {'Net Result':<12} {'Status'}")
    print("-" * 70)
    
    monthly_results = []
    
    for month_key, data in screenshot_data.items():
        month_name = f"{month_names[month_key[-2:]]} 2026"
        wins = data['wins']
        losses = data['losses']
        net_result = data['net_result']
        
        # Estimate points lost based on losses (assuming avg 8-10 points per loss)
        avg_points_per_loss = 9.0  # Based on September data analysis
        estimated_points_lost = losses * avg_points_per_loss
        
        status = "PROFIT" if net_result > 0 else "LOSS"
        
        monthly_results.append({
            'month': month_name,
            'wins': wins,
            'losses': losses,
            'estimated_points_lost': estimated_points_lost,
            'net_result': net_result,
            'status': status
        })
        
        print(f"{month_name:<12} {wins:<5} {losses:<7} {estimated_points_lost:<16.1f} {net_result:>+11} {status}")
    
    print("\n" + "=" * 70)
    
    # Sort by points lost (biggest losses first)
    monthly_results.sort(key=lambda x: x['estimated_points_lost'], reverse=True)
    
    print("RANKING BY BIGGEST POINTS LOSS (Estimated):")
    print("=" * 70)
    print(f"{'Rank':<5} {'Month':<12} {'Points Lost':<12} {'Losses':<7} {'Net Result':<12}")
    print("-" * 70)
    
    for i, result in enumerate(monthly_results, 1):
        print(f"{i:<5} {result['month']:<12} {result['estimated_points_lost']:<12.1f} {result['losses']:<7} {result['net_result']:>+11}")
    
    print("\n" + "=" * 70)
    print("SUMMARY:")
    
    # Find the worst month
    worst_month = max(monthly_results, key=lambda x: x['estimated_points_lost'])
    
    print(f"🔴 BIGGEST POINTS LOSS MONTH: {worst_month['month']}")
    print(f"   - Estimated Points Lost: {worst_month['estimated_points_lost']:.1f}")
    print(f"   - Number of Losses: {worst_month['losses']}")
    print(f"   - Net Result: {worst_month['net_result']:+d}")
    print(f"   - Win/Loss Ratio: {worst_month['wins']}/{worst_month['losses']}")
    
    # Calculate totals
    total_points_lost = sum(r['estimated_points_lost'] for r in monthly_results)
    total_losses = sum(r['losses'] for r in monthly_results)
    
    print(f"\n📊 TOTAL ACROSS ALL MONTHS:")
    print(f"   - Total Estimated Points Lost: {total_points_lost:.1f}")
    print(f"   - Total Losing Trades: {total_losses}")
    print(f"   - Average Points per Loss: {total_points_lost/total_losses:.1f}")
    
    # If we have September actual data, show comparison
    if main_data:
        sep_data = main_data.get('2026-09')
        if sep_data:
            print(f"\n✅ SEPTEMBER 2026 ACTUAL DATA (for comparison):")
            print(f"   - Actual Points Lost: {sep_data['losing_points']:.1f}")
            print(f"   - Actual Losses: {sep_data['losses']}")
            print(f"   - Actual Avg per Loss: {sep_data['losing_points']/sep_data['losses']:.1f}")

if __name__ == "__main__":
    main()