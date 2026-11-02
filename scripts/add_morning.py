
# scripts/add_morning.py
import asyncio
import calendar
import html
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests
import feedparser
import chinese_calendar as cncal
import edge_tts


TZ = ZoneInfo("Asia/Shanghai")
TODAY = datetime.now(TZ).date()
DATE = TODAY.isoformat()
OUT = Path("daily_reports") / DATE

WEATHER_URL = (
    "https://api.open-meteo.com/v1/forecast?"
    + urlencode({
        "latitude": 29.8683,
        "longitude": 121.5440,
        "current": "temperature_2m,apparent_temperature,weather_code",
        "daily": (
            "weather_code,temperature_2m_max,"
            "temperature_2m_min,precipitation_probability_max"
        ),
        "timezone": "Asia/Shanghai",
        "forecast_days": 1,
    })
)

KNOWLEDGE = [
    "STM32的定时器不仅可以生成PWM，还能进行输入捕获和编码器计数。",
    "RS485规定的是电气接口，Modbus RTU规定的是通信协议。",
    "看门狗可以帮助嵌入式设备从部分软件异常中自动恢复。",
    "CRC校验可以检测许多通信错误，但无法代替超时处理。",
    "PID控制中的积分项可以减小稳态误差，但需要防止积分饱和。",
    "锂电池端电压会随负载、电流和温度变化，不能单靠电压精确估算电量。",
    "嵌入式系统进行远程升级时，应考虑固件校验和断电恢复。",
]


def safe(name, function):
    try:
        return function()
    except Exception as exc:
        print(f"[morning] {name} unavailable: {exc}")
        return None


def get_weather():
    response = requests.get(WEATHER_URL, timeout=20)
    response.raise_for_status()
    data = response.json()

    current = data["current"]
    daily = data["daily"]
    rain = daily["precipitation_probability_max"][0]
    low = daily["temperature_2m_min"][0]
    high = daily["temperature_2m_max"][0]

    if rain is None or low is None or high is None:
        raise ValueError("Weather forecast incomplete")

    tips = []
    if rain >= 50:
        tips.append("降雨概率较高，建议携带雨具")
    if low < 10:
        tips.append("早晚偏冷，建议注意保暖")
    if high >= 32:
        tips.append("白天气温较高，注意防暑")
    if not tips:
        tips.append("出门前请结合实时天气安排出行")

    return {
        "now": current["temperature_2m"],
        "low": low,
        "high": high,
        "rain": rain,
        "tip": "；".join(tips),
        "updated": current["time"],
    }


def holiday_name(value):
    if value is None:
        return ""
    return str(getattr(value, "value", value))


def get_holiday():
    # 以已公布并被 chinese_calendar 收录的日期为准
    if cncal.is_workday(TODAY):
        status = (
            "今天是调休工作日"
            if TODAY.weekday() >= 5
            else "今天是工作日"
        )
    else:
        named, name = cncal.get_holiday_detail(TODAY)
        if named and name:
            status = f"今天是假期：{holiday_name(name)}"
        elif TODAY.weekday() < 5:
            status = "今天是调休放假日"
        else:
            status = "今天是休息日"

    upcoming = "暂未找到已收录的近期法定节假日"
    for offset in range(1, 100):
        date = TODAY + timedelta(days=offset)
        try:
            named, name = cncal.get_holiday_detail(date)
        except (NotImplementedError, ValueError):
            upcoming = "后续年度的假期安排尚未收录"
            break

        if named and name:
            upcoming = (
                f"下一个已收录节日：{holiday_name(name)}，"
                f"{date.isoformat()}，还有{offset}天"
            )
            break

    return {
        "status": status,
        "upcoming": upcoming,
    }


def get_exchange_rate():
    url = "https://api.frankfurter.dev/v2/rate/USD/CNY"
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    data = response.json()

    return {
        "rate": round(float(data["rate"]), 4),
        "date": data["date"],
        "source": "Frankfurter",
    }


def get_ningbo_news():
    rss_url = (
        "https://news.google.com/rss/search?"
        + urlencode({
            "q": "宁波",
            "hl": "zh-CN",
            "gl": "CN",
            "ceid": "CN:zh-Hans",
        })
    )

    response = requests.get(
        rss_url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
    )
    response.raise_for_status()

    feed = feedparser.parse(response.content)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    now = datetime.now(timezone.utc)
    result = []
    seen = set()

    for entry in feed.entries:
        parsed = (
            entry.get("published_parsed")
            or entry.get("updated_parsed")
        )
        if not parsed:
            continue

        published = datetime.fromtimestamp(
            calendar.timegm(parsed), timezone.utc
        )
        if not cutoff <= published <= now:
            continue

        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()

        if not title or not link.startswith("https://"):
            continue
        if title in seen:
            continue

        seen.add(title)
        result.append({
            "title": title,
            "url": link,
            "published": published.isoformat(),
        })
        if len(result) >= 5:
            break

    return result


def make_script(report, weather, holiday, rate, news, knowledge):
    parts = [
        f"早上好，今天是{DATE}。"
        "欢迎收听AI每日智能晨报。"
    ]

    if weather:
        parts.append(
            f"宁波当前参考气温{weather['now']}摄氏度。"
            f"今天最低{weather['low']}度，"
            f"最高{weather['high']}度，"
            f"最大降水概率{weather['rain']}%。"
            f"{weather['tip']}。"
        )

    if holiday:
        parts.append(
            f"节假日提醒：{holiday['status']}。"
            f"{holiday['upcoming']}。"
        )

    if news:
        parts.append("接下来是宁波本地资讯。")
        for item in news[:3]:
            parts.append(item["title"] + "。")
    else:
        parts.append("宁波本地资讯暂时没有可核实的新消息。")

    overview = str(report.get("daily_overview") or "")
    if overview:
        parts.append("下面是今天的国内外、科技与财经资讯。")
        parts.append(overview[:750])

    if rate:
        parts.append(
            f"财经参考汇率方面，截至{rate['date']}，"
            f"一美元约合人民币{rate['rate']}元。"
            "这不是实时交易报价。"
        )

    parts.append("最后是每日科技小知识。" + knowledge)
    parts.append(
        "以上内容部分由人工智能整理，"
        "新闻与行情请以原始来源为准。"
        "感谢收听，祝你今天工作顺利。"
    )
    return "\n".join(parts)


async def save_mp3(text, destination):
    speech = edge_tts.Communicate(
        text,
        voice="zh-CN-XiaoxiaoNeural",
        rate="+0%",
    )
    await speech.save(str(destination))


def esc(value):
    return html.escape(str(value), quote=True)


def make_panel(weather, holiday, rate, news, knowledge, report, audio_ok):
    weather_html = (
        f"<p>生成时气温：{esc(weather['now'])}℃，"
        f"今日 {esc(weather['low'])}～{esc(weather['high'])}℃，"
        f"最大降水概率 {esc(weather['rain'])}%</p>"
        f"<p>{esc(weather['tip'])}</p>"
        if weather else "<p>天气暂时无法获取。</p>"
    )

    holiday_html = (
        f"<p>{esc(holiday['status'])}</p>"
        f"<p>{esc(holiday['upcoming'])}</p>"
        if holiday else "<p>节假日数据暂不可用。</p>"
    )

    news_html = (
        "<ol>"
        + "".join(
            f'<li><a href="{esc(item["url"])}" '
            f'target="_blank" rel="noopener noreferrer">'
            f'{esc(item["title"])}</a></li>'
            for item in news
        )
        + "</ol>"
        if news else "<p>暂无可核实的近48小时宁波新闻。</p>"
    )

    rate_html = (
        f"<p>1 USD ≈ {esc(rate['rate'])} CNY</p>"
        f"<small>参考日期：{esc(rate['date'])}，非实时交易价。</small>"
        if rate else "<p>汇率暂时无法获取。</p>"
    )

    market = report.get("trading") or {}
    market_text = str(market.get("market_overview") or "")
    market_html = (
        f"<p>{esc(market_text[:250])}……</p>"
        if market_text else "<p>请查看原有的财经与市场行情栏目。</p>"
    )

    owner, repo = os.getenv(
        "GITHUB_REPOSITORY", "JaxonJiang/DailyBrief"
    ).split("/", 1)

    audio_url = (
        f"https://{owner.lower()}.github.io/"
        f"{repo}/{DATE}/briefing.mp3"
    )

    audio_html = (
        f'<audio controls preload="none" src="{esc(audio_url)}">'
        "浏览器不支持音频播放。</audio>"
        f'<p><a href="{esc(audio_url)}" download>'
        "下载今日 MP3</a></p>"
        if audio_ok else "<p>本次语音暂不可用，文字晨报正常显示。</p>"
    )

    return f"""
<section id="morning-v2" class="morning-v2">
  <h2>☀️ 宁波 AI 晨间播报 · {esc(DATE)}</h2>
  <div class="morning-grid">
    <article class="morning-card">
      <h3>🌤️ 宁波天气</h3>
      <p id="ningbo-live">页面打开时将刷新当前气温</p>
      {weather_html}
      <small>来源：Open-Meteo 模型天气数据</small>
    </article>
    <article class="morning-card">
      <h3>📅 节假日与调休</h3>
      {holiday_html}
    </article>
    <article class="morning-card">
      <h3>🏙️ 宁波本地热点</h3>
      {news_html}
      <small>新闻搜索聚合，点击原文核对。</small>
    </article>
    <article class="morning-card">
      <h3>💹 财经与汇率</h3>
      {rate_html}
      {market_html}
      <small>市场评论为 AI 观点，不构成投资建议。</small>
    </article>
    <article class="morning-card">
      <h3>💡 每日科技知识</h3>
      <p>{esc(knowledge)}</p>
    </article>
    <article class="morning-card">
      <h3>🔊 今日语音晨报</h3>
      {audio_html}
      <small>点击播放器可播放、暂停；iOS 需手动开始播放。</small>
    </article>
  </div>
</section>
"""


CSS = """
<style>
.morning-v2 {
  margin: 1.5rem 0;
  padding: 1.1rem;
  border: 1px solid var(--rule, #6666);
  border-radius: 16px;
}
.morning-v2 h2 {
  font-size: 1.25rem;
  margin: 0 0 1rem;
}
.morning-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.morning-card {
  min-width: 0;
  padding: 16px;
  border-radius: 12px;
  border: 1px solid var(--rule, #6666);
  overflow-wrap: anywhere;
}
.morning-card h3 {
  font-size: 1rem;
  margin: 0 0 10px;
}
.morning-card p, .morning-card li {
  font-size: .9rem;
  line-height: 1.75;
}
.morning-card ol { padding-left: 1.3rem; }
.morning-card small { opacity: .7; }
.morning-card audio {
  width: 100%;
  max-width: 100%;
  margin: 12px 0;
}
@media (max-width: 700px) {
  .morning-grid { grid-template-columns: 1fr; }
  .morning-v2 { padding: 12px; }
}
</style>
"""


def main():
    report_file = OUT / f"{DATE}.json"
    html_file = OUT / f"{DATE}.html"

    report = json.loads(report_file.read_text(encoding="utf-8"))

    weather = safe("weather", get_weather)
    holiday = safe("holiday", get_holiday)
    rate = safe("exchange rate", get_exchange_rate)
    news = safe("Ningbo news", get_ningbo_news) or []

    knowledge = KNOWLEDGE[TODAY.toordinal() % len(KNOWLEDGE)]

    script = make_script(
        report, weather, holiday, rate, news, knowledge
    )

    (OUT / "briefing.txt").write_text(
        script, encoding="utf-8"
    )

    audio_file = OUT / "briefing.mp3"
    audio_ok = False

    try:
        asyncio.run(save_mp3(script, audio_file))
        audio_ok = (
            audio_file.exists() and audio_file.stat().st_size > 0
        )
    except Exception as exc:
        print(f"[morning] TTS failed: {exc}")

    if not audio_ok:
        audio_file.unlink(missing_ok=True)

    content = html_file.read_text(encoding="utf-8")

    marker = '<nav class="tabs"'
    if marker not in content:
        raise RuntimeError("DailyBrief HTML structure changed")

    content = content.replace(
        "</head>", CSS + "\n</head>", 1
    )
    content = content.replace(
        marker,
        make_panel(
            weather, holiday, rate, news,
            knowledge, report, audio_ok
        ) + "\n" + marker,
        1,
    )

    # 每次打开网页时，重新获取宁波当前气温。
    live_script = """
<script>
fetch(WEATHER_URL_PLACEHOLDER, {cache: "no-store"})
.then(r => {
  if (!r.ok) throw new Error("weather unavailable");
  return r.json();
})
.then(data => {
  const t = data.current?.temperature_2m;
  const el = document.getElementById("ningbo-live");
  if (el && typeof t === "number") {
    el.textContent = "打开页面时当前参考气温：" + t + "℃";
  }
})
.catch(() => {
  const el = document.getElementById("ningbo-live");
  if (el) el.textContent = "实时刷新不可用，请参考生成时天气";
});
</script>
""".replace(
        "WEATHER_URL_PLACEHOLDER", json.dumps(WEATHER_URL)
    )

    content = content.replace(
        "</body>", live_script + "\n</body>", 1
    )
    html_file.write_text(content, encoding="utf-8")

    print(
        f"[morning] complete: {DATE}, "
        f"news={len(news)}, mp3={audio_ok}"
    )


if __name__ == "__main__":
    main()
