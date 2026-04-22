# Anthropic API Key Setup — Windows Instructions

## Step 1: Get Your API Key

1. **Visit Anthropic Console:**
   - Go to https://console.anthropic.com/
   - Sign up with your email or log in if you have an account

2. **Create API Key:**
   - Click "API Keys" in the left sidebar
   - Click "Create Key"
   - Give it a name (e.g., "Trading Bot")
   - Click "Create"
   - **Copy the full key** (starts with `sk-ant-`)
   - ⚠️ **Important:** You won't see it again! Save it somewhere safe.

## Step 2: Set Environment Variable on Windows

### Option A: PowerShell (Recommended)

```powershell
# In PowerShell (run as Administrator NOT required)
$env:ANTHROPIC_API_KEY = "sk-ant-your-key-here"

# Verify it's set
Write-Host $env:ANTHROPIC_API_KEY

# Start the bot
python main.py
```

**Note:** This only works for the current PowerShell session. After you close PowerShell, the variable is gone.

### Option B: Permanent Environment Variable (Windows Settings)

1. **Press Windows Key + X** and select "System"
2. Click **Advanced system settings** (left sidebar)
3. Click **Environment Variables** button
4. Under "User variables", click **New**
5. Variable name: `ANTHROPIC_API_KEY`
6. Variable value: `sk-ant-your-key-here`
7. Click **OK** three times
8. **Restart PowerShell or Command Prompt** (important!)
9. Verify: `Write-Host $env:ANTHROPIC_API_KEY`

### Option C: Create .env File (Easiest for Testing)

1. In your bot directory (`c:\zain\ai_trading_bot\`), create a new file named `.env`
2. Add this single line:
   ```
   ANTHROPIC_API_KEY=sk-ant-your-key-here
   ```
3. Save the file
4. Run: `python main.py`

The bot's `config.py` will automatically load the key from `.env`.

**Advantage:** No PowerShell setup needed. Just one file.
**Disadvantage:** .env file contains your secret key, so be careful not to commit it to GitHub.

## Step 3: Test the Setup

### Verify the key is accessible:

```powershell
# In PowerShell
python -c "import os; print(os.getenv('ANTHROPIC_API_KEY'))"
```

You should see your key printed (or empty if not set).

### Start the bot:

```bash
cd c:\zain\ai_trading_bot
python main.py
```

### Expected output (first few lines):

```
========================================================================
Starting XAUUSD trading bot — continuous monitoring mode
========================================================================
MT5 connection established. Starting monitoring loop...
[MONITOR 14:32:15] WAIT | Score: 3.45/12.5 | Conf: 38% (need 49%) | ...
```

## Anthropic Pricing

**Current pricing (as of 2025):**
- Claude 3.5 Sonnet: $3 per 1M input tokens, $15 per 1M output tokens
- The bot uses Claude Sonnet 4 (most cost-effective)
- Each verification call: ~300-500 tokens input, ~100-200 tokens output
- **Cost per trade:** ~$0.0015 USD (very cheap)
- **Cost per 100 trades:** ~$0.15 USD

**No rate limits for most accounts.** You get 5 requests per minute on free trial; paid accounts have higher limits.

## Troubleshooting

### "ModuleNotFoundError: No module named 'anthropic'"

```bash
# Install the package
pip install anthropic>=0.28.0

# Verify
python -c "import anthropic; print(anthropic.__version__)"
```

### "ANTHROPIC_API_KEY not found" or bot runs without AI verification

**Check 1:** Verify key is set
```powershell
Write-Host $env:ANTHROPIC_API_KEY
# Should print your key, not empty
```

**Check 2:** Check .env file exists
```powershell
Get-Content .env  # Should show ANTHROPIC_API_KEY=sk-ant-...
```

**Check 3:** Make sure you're in the right directory
```powershell
cd c:\zain\ai_trading_bot
python main.py
```

### "401 Unauthorized" from Claude API

- Your API key is wrong or expired
- Get a new key from https://console.anthropic.com/api_keys
- Update the .env file or environment variable

### "Rate limited" (429 error)

- You've exceeded API quota
- Free trial: 5 requests/minute
- Paid: Depends on your plan
- Solution: Upgrade to paid account or increase sleep times between checks

## Security Best Practices

⚠️ **NEVER:**
- Commit your API key to GitHub (add `.env` to `.gitignore`)
- Share your key in Slack, email, or forums
- Paste your key in public websites

✅ **DO:**
- Use a `.env` file (not committed)
- Or use Windows environment variables
- Rotate your key monthly
- Use separate keys for different apps

## Getting Help

- **Anthropic Docs:** https://docs.anthropic.com/
- **API Status:** https://status.anthropic.com/
- **Support:** https://support.anthropic.com/

---

Once your key is set, the bot will automatically use Claude for AI verification whenever STAGE 3 runs!
