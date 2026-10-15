#!/usr/bin/env python3
"""Debug script for L4 fallback logic."""

import pandas as pd
import MetaTrader5 as mt5
from liquidity_engine import identify_liquidity_pools
from mt5_handler import get_market_data, connect_mt5

# Connect to MT5
connect_mt5()

# Fetch real data
m15_data = get_market_data('XAUUSD', mt5.TIMEFRAME_M15, 50)
h1_data = get_market_data('XAUUSD', mt5.TIMEFRAME_H1, 60) 
h4_data = get_market_data('XAUUSD', mt5.TIMEFRAME_H4, 100)

print('M15 data shape:', m15_data.shape if m15_data is not None else None)
print('H1 data shape:', h1_data.shape if h1_data is not None else None)
print('H4 data shape:', h4_data.shape if h4_data is not None else None)

if m15_data is not None and len(m15_data) > 0:
    current_price = m15_data.iloc[-1]['close']
    print(f'\nCurrent price: {current_price}')
    
    result = identify_liquidity_pools(m15_data, h1_data=h1_data, h4_data=h4_data, current_price=current_price, side='SELL')
    
    pools = result.get('liquidity_pools', [])
    print(f'\nPools found: {len(pools)}')
    print(f'Sweep pool: {result.get("sweep_pool")}')
    print(f'TP pool: {result.get("tp_pool")}')
    
    # Debug pool distribution
    if pools:
        above = [p for p in pools if p.get('level', 0) > current_price]
        below = [p for p in pools if p.get('level', 0) < current_price]
        print(f'\nPools above price: {len(above)}')
        print(f'Pools below price: {len(below)}')
        
        if above:
            print(f'First above: {above[0]}')
        if below:
            print(f'First below: {below[0]}')
