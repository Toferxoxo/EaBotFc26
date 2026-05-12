import asyncio
import aiohttp
import sqlite3
import time
import re
from statistics import mean
from bs4 import BeautifulSoup

# =====================================================
# CONFIG
# =====================================================

WEBHOOK_URL = "https://discord.com/api/webhooks/1503841297256022038/6RDdh0dwhvCwq3sAokbyX3wHxiSVf6DQ_p_mo4zhJYoHGmKWyinLHwpi70Wxe9FDM442"

CHECK_INTERVAL = 300

MAX_PAGES = 5

MIN_PRICE = 80000

DISCOUNT_THRESHOLD = 0.72

SPREAD_THRESHOLD = 1.35

COOLDOWN_SECONDS = 1800

CONCURRENT_REQUESTS = 25

PLATFORM = "PC"

# =====================================================
# DATABASE
# =====================================================

conn = sqlite3.connect(
    "prices.db",
    check_same_thread=False
)

cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS prices (
    player TEXT,
    platform TEXT,
    price INTEGER,
    timestamp INTEGER
)
""")

conn.commit()

# =====================================================

already_alerted = {}

# =====================================================


def parse_price(value):

    if not value:
        return None

    value = value.replace(",", "")

    digits = re.findall(r"\d+", value)

    if digits:
        return int("".join(digits))

    return None


# =====================================================


def save_price(player, platform, price):

    timestamp = int(time.time())

    cursor.execute(
        """
        INSERT INTO prices
        VALUES (?, ?, ?, ?)
        """,
        (player, platform, price, timestamp)
    )

    conn.commit()


# =====================================================


def get_average_price(player, platform):

    cursor.execute(
        """
        SELECT price
        FROM prices
        WHERE player = ?
        AND platform = ?
        ORDER BY timestamp DESC
        LIMIT 30
        """,
        (player, platform)
    )

    rows = cursor.fetchall()

    if len(rows) < 8:
        return None

    prices = [r[0] for r in rows]

    return int(mean(prices))


# =====================================================


def calculate_score(ratio, spread):

    score = 0

    # ratio score

    if ratio <= 0.50:
        score += 50

    elif ratio <= 0.60:
        score += 40

    elif ratio <= 0.70:
        score += 30

    elif ratio <= 0.80:
        score += 15

    # spread score

    if spread >= 2:
        score += 50

    elif spread >= 1.7:
        score += 35

    elif spread >= 1.5:
        score += 25

    elif spread >= 1.3:
        score += 10

    return min(score, 100)


# =====================================================


async def send_alert(
    session,
    player,
    current,
    average,
    second_lowest,
    ratio,
    spread,
    score,
    url
):

    embed = {
        "title": "🚨 PRICE ERROR DETECTED",
        "description": (
            f"**{player}**\n\n"
            f"🖥 Platform: {PLATFORM}\n"
            f"💰 Lowest BIN: {current:,}\n"
            f"📈 Second Lowest: {second_lowest:,}\n"
            f"📊 Average: {average:,}\n"
            f"🔥 Ratio: {round(ratio * 100)}%\n"
            f"⚡ Spread: {spread:.2f}x\n"
            f"🎯 Score: {score}/100"
        ),
        "url": url,
        "color": 65280
    }

    data = {
        "content": "@here",
        "embeds": [embed]
    }

    async with session.post(
        WEBHOOK_URL,
        json=data
    ) as response:

        if response.status == 204:

            print(f"✅ ALERT [{player}]")

        else:

            print(f"❌ DISCORD ERROR [{player}]")


# =====================================================


async def get_player_links(session, page):

    url = f"https://www.futbin.com/players?page={page}"

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    async with session.get(
        url,
        headers=headers,
        timeout=30
    ) as response:

        html = await response.text()

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    links = set()

    for a in soup.find_all("a", href=True):

        href = a["href"]

        if "/player/" in href:

            links.add(
                "https://www.futbin.com" + href
            )

    return list(links)


# =====================================================


async def check_player(session, url):

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    try:

        async with session.get(
            url,
            headers=headers,
            timeout=30
        ) as response:

            html = await response.text()

    except Exception as e:

        print("❌ REQUEST ERROR", e)

        return

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    title = soup.title.text.strip()

    # =================================================
    # PLATFORM PRICES
    # =================================================

    if PLATFORM == "PC":

        lowest_match = re.search(
            r'PCPrice2\\":\\"([\d,]+)\\"',
            html
        )

    else:

        lowest_match = re.search(
            r'LCPrice2\\":\\"([\d,]+)\\"',
            html
        )

    if not lowest_match:
        return

    current_price = parse_price(
        lowest_match.group(1)
    )

    if not current_price:
        return

    if current_price < MIN_PRICE:
        return

    # =================================================
    # SECOND LOWEST
    # =================================================

    price_matches = re.findall(
        r'([\d]{1,3}(?:,[\d]{3})+)',
        html
    )

    parsed_prices = []

    for p in price_matches:

        value = parse_price(p)

        if value and value >= MIN_PRICE:

            parsed_prices.append(value)

    parsed_prices = sorted(list(set(parsed_prices)))

    if len(parsed_prices) < 2:
        return

    second_lowest = parsed_prices[1]

    spread = second_lowest / current_price

    # =================================================
    # SAVE HISTORY
    # =================================================

    save_price(
        title,
        PLATFORM,
        current_price
    )

    average_price = get_average_price(
        title,
        PLATFORM
    )

    if not average_price:

        print(f"⌛ HISTORY BUILDING [{title[:40]}]")

        return

    ratio = current_price / average_price

    score = calculate_score(
        ratio,
        spread
    )

    print(
        f"👤 {title[:45]} | "
        f"{current_price:,} | "
        f"AVG {average_price:,} | "
        f"SPREAD {spread:.2f} | "
        f"SCORE {score}"
    )

    # =================================================
    # ALERT CONDITIONS
    # =================================================

    if (
        ratio <= DISCOUNT_THRESHOLD
        and spread >= SPREAD_THRESHOLD
        and score >= 50
    ):

        now = time.time()

        if title not in already_alerted:

            already_alerted[title] = 0

        if now - already_alerted[title] >= COOLDOWN_SECONDS:

            print(f"🚨 PRICE ERROR [{title}]")

            await send_alert(
                session,
                title,
                current_price,
                average_price,
                second_lowest,
                ratio,
                spread,
                score,
                url
            )

            already_alerted[title] = now


# =====================================================


async def main():

    print("🔥 ADVANCED EA FC PRICE ERROR SCANNER")

    connector = aiohttp.TCPConnector(
        limit=CONCURRENT_REQUESTS
    )

    async with aiohttp.ClientSession(
        connector=connector
    ) as session:

        while True:

            try:

                all_players = []

                for page in range(1, MAX_PAGES + 1):

                    print(f"📄 PAGE {page}")

                    players = await get_player_links(
                        session,
                        page
                    )

                    print(f"🔎 {len(players)} PLAYERS")

                    all_players.extend(players)

                all_players = list(set(all_players))

                print(
                    f"🎯 TOTAL PLAYERS: {len(all_players)}"
                )

                tasks = []

                for url in all_players:

                    tasks.append(
                        check_player(session, url)
                    )

                await asyncio.gather(*tasks)

            except Exception as e:

                print("❌ MAIN LOOP ERROR:", e)

            print("😴 SLEEPING")

            await asyncio.sleep(CHECK_INTERVAL)


# =====================================================

asyncio.run(main())