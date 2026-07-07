import os
import json
import re
import time
import requests
import subprocess
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

# ============================================
# READ TOKEN FROM ENVIRONMENT VARIABLE
# ============================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TOKEN_HERE")

# ============================================
# DO NOT CHANGE ANYTHING BELOW
# ============================================

TELEGRAM_CHAT_ID = "8594306891"
TRACKING_FILE = "hianime_tracking.json"
MAX_EPISODES_TO_CHECK = 15
MAX_TRACKING_AGE_HOURS = 48

def send_telegram(message):
    """Send Telegram notification"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message}
    try:
        response = requests.post(url, json=payload, timeout=15)
        if response.status_code == 200:
            print("✅ Telegram sent")
            return True
        else:
            print(f"❌ Failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def is_valid_episode(episode_title, episode_url):
    title_lower = episode_title.lower()
    url_lower = episode_url.lower()
    movie_keywords = ['movie', 'film', 'special']
    for keyword in movie_keywords:
        if keyword in title_lower or keyword in url_lower:
            return False, "Movie/Special"
    upcoming_keywords = ['upcoming', 'premiere', 'coming soon']
    for keyword in upcoming_keywords:
        if keyword in title_lower:
            return False, "Upcoming"
    has_episode = False
    ep_patterns = [r'ep\s*(\d+)', r'episode\s*(\d+)', r'e(\d+)']
    for pattern in ep_patterns:
        if re.search(pattern, title_lower) or re.search(pattern, url_lower):
            has_episode = True
            break
    if not has_episode:
        return False, "No episode number"
    return True, "Valid"

def extract_episode_number(title, url):
    text = title.lower() + " " + url.lower()
    patterns = [r'ep\s*(\d+)', r'episode\s*(\d+)', r'e(\d+)']
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return "Unknown"

def get_recent_episodes():
    print("🔄 Checking hianime.bh...")
    episodes = []
    skipped = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        page = context.new_page()
        page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "font"] else route.continue_())
        try:
            page.goto("https://hianime.bh/", timeout=15000, wait_until='domcontentloaded')
            time.sleep(2)
            episode_links = page.locator(".listupd.normal .bsx a")
            count = episode_links.count()
            print(f"📋 Found {count} episodes")
            for i in range(min(count, MAX_EPISODES_TO_CHECK)):
                link = episode_links.nth(i)
                episode_url = link.get_attribute('href')
                episode_title = link.text_content().strip()
                title_div = link.locator(".tt")
                if title_div.count() > 0:
                    title_text = title_div.text_content().strip()
                    if title_text:
                        episode_title = title_text
                if episode_url:
                    if episode_url.startswith('/'):
                        episode_url = f"https://hianime.bh{episode_url}"
                    is_valid, reason = is_valid_episode(episode_title, episode_url)
                    if is_valid:
                        ep_num = extract_episode_number(episode_title, episode_url)
                        episodes.append({'url': episode_url, 'title': episode_title, 'episode': ep_num})
                        print(f"  ✅ {i+1}. {episode_title} (Ep {ep_num})")
                    else:
                        skipped.append(f"{episode_title} - {reason}")
                        print(f"  ⏭️ SKIPPED: {episode_title} - {reason}")
            browser.close()
            return episodes, skipped
        except Exception as e:
            print(f"❌ Error: {e}")
            browser.close()
            return [], []

def get_episode_iframe(episode_url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        page = context.new_page()
        page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "font"] else route.continue_())
        try:
            page.goto(episode_url, timeout=15000, wait_until='domcontentloaded')
            time.sleep(3)
            iframe = page.locator("#pembed iframe")
            if iframe.count() == 0:
                iframe = page.locator(".player iframe")
            if iframe.count() == 0:
                iframe = page.locator("iframe[src*='embed']")
            if iframe.count() > 0:
                iframe_html = iframe.evaluate("el => el.outerHTML")
                browser.close()
                return iframe_html
            else:
                browser.close()
                return None
        except Exception as e:
            browser.close()
            return None

def load_tracking():
    if os.path.exists(TRACKING_FILE):
        with open(TRACKING_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_tracking(data):
    with open(TRACKING_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def cleanup_old_tracking(tracked):
    now = datetime.now()
    to_remove = []
    for url, data in tracked.items():
        if 'first_seen' in data:
            first_seen = datetime.fromisoformat(data['first_seen'])
            age_hours = (now - first_seen).total_seconds() / 3600
            if age_hours > MAX_TRACKING_AGE_HOURS:
                to_remove.append(url)
    for url in to_remove:
        del tracked[url]
    return tracked

def commit_and_push_changes():
    try:
        subprocess.run(["git", "config", "user.name", "github-actions"], check=True)
        subprocess.run(["git", "config", "user.email", "github-actions@github.com"], check=True)
        subprocess.run(["git", "add", TRACKING_FILE], check=True)
        subprocess.run(["git", "commit", "-m", f"Update tracking {datetime.now().isoformat()}"], check=True, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "push"], check=True)
        print("✅ Tracking file updated")
    except Exception as e:
        print(f"⚠️ Could not commit: {e}")

def main():
    print("=" * 60)
    print("🎯 MONITORING HIANIME.BH (GitHub Actions)")
    print("=" * 60)
    
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "YOUR_TOKEN_HERE":
        print("❌ ERROR: TELEGRAM_TOKEN not set!")
        return
    
    tracked = load_tracking()
    tracked = cleanup_old_tracking(tracked)
    episodes, skipped = get_recent_episodes()
    
    if not episodes:
        print("\n❌ No valid episodes found")
        return
    
    print(f"\n📋 Found {len(episodes)} valid episodes")
    new_episodes = False
    iframe_updates = False
    
    for episode in episodes:
        url = episode['url']
        title = episode['title']
        ep_num = episode.get('episode', 'Unknown')
        print(f"\n📺 {title} (Ep {ep_num})")
        
        if url not in tracked:
            print("🆕 NEW EPISODE!")
            iframe = get_episode_iframe(url)
            if iframe:
                msg = f"🎬 NEW EPISODE ON HIANIME.BH!\n\nTitle: {title}\nEpisode: {ep_num}\nURL: {url}\n\nIframe:\n{iframe}"
                send_telegram(msg)
                tracked[url] = {
                    'title': title,
                    'episode': ep_num,
                    'initial_iframe': iframe,
                    'first_seen': datetime.now().isoformat(),
                    'notification_1_sent': True
                }
                new_episodes = True
            else:
                print("⚠️ Could not get iframe")
        else:
            data = tracked[url]
            if data.get('notification_1_sent', False) and not data.get('notification_2_sent', False):
                print("🔄 Checking iframe update...")
                current_iframe = get_episode_iframe(url)
                if current_iframe and current_iframe != data.get('initial_iframe'):
                    print("🔄 IFRAME UPDATED!")
                    msg = f"🔄 IFRAME UPDATED!\n\nTitle: {title}\nEpisode: {ep_num}\nURL: {url}\n\nNew Iframe:\n{current_iframe}"
                    send_telegram(msg)
                    data['notification_2_sent'] = True
                    iframe_updates = True
                else:
                    print("✅ Iframe unchanged")
    
    if new_episodes or iframe_updates:
        save_tracking(tracked)
        commit_and_push_changes()

if __name__ == "__main__":
    main()
